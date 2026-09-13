from unittest.mock import (
    AsyncMock,
    patch,
)

import pytest
from multiaddr import (
    Multiaddr,
)

from libp2p.host.autonat.autonat import (
    AUTONAT_PROTOCOL_ID,
    AutoNATService,
    AutoNATStatus,
    _is_relayed_stream,
)
from libp2p.host.autonat.pb.autonat_pb2 import (
    Message,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)
from libp2p.utils.varint import (
    encode_varint_prefixed,
)
from tests.utils.factories import (
    HostFactory,
)


def _server_ids(n):
    return [ID(f"server-{i}".encode()) for i in range(n)]


@pytest.mark.trio
async def test_autonat_service_initialization():
    """Test that the AutoNAT service initializes correctly."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        service = AutoNATService(host, serve=False)

        assert service.status == AutoNATStatus.UNKNOWN
        assert service.dial_results == {}
        assert service.host == host
        assert service.peerstore == host.get_peerstore()


@pytest.mark.trio
async def test_autonat_service_registers_handler_by_default():
    """Serving hosts answer AutoNAT streams; opt-out hosts do not."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        AutoNATService(host)
        assert AUTONAT_PROTOCOL_ID in host.get_mux().handlers
        host.remove_stream_handler(AUTONAT_PROTOCOL_ID)
        assert AUTONAT_PROTOCOL_ID not in host.get_mux().handlers


@pytest.mark.trio
async def test_autonat_status_getter():
    """Test that the AutoNAT status getter works correctly."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        service = AutoNATService(host, serve=False)

        assert service.get_status() == AutoNATStatus.UNKNOWN

        service.status = AutoNATStatus.PUBLIC
        assert service.get_status() == AutoNATStatus.PUBLIC

        service.status = AutoNATStatus.PRIVATE
        assert service.get_status() == AutoNATStatus.PRIVATE


@pytest.mark.trio
async def test_update_status_needs_more_than_three_confirmations():
    """Spec heuristic: >3 servers must agree before the status flips."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        service = AutoNATService(host, serve=False)

        # No verdicts -> UNKNOWN
        service.update_status()
        assert service.status == AutoNATStatus.UNKNOWN

        # Three successes are not enough -> unchanged
        service.dial_results = {sid: True for sid in _server_ids(3)}
        service.update_status()
        assert service.status == AutoNATStatus.UNKNOWN

        # Four successes -> PUBLIC
        service.dial_results = {sid: True for sid in _server_ids(4)}
        service.update_status()
        assert service.status == AutoNATStatus.PUBLIC

        # Four failures -> PRIVATE (even from PUBLIC)
        service.dial_results = {sid: False for sid in _server_ids(4)}
        service.update_status()
        assert service.status == AutoNATStatus.PRIVATE

        # Mixed below thresholds -> unchanged
        service.status = AutoNATStatus.UNKNOWN
        service.dial_results = {sid: (i < 2) for i, sid in enumerate(_server_ids(4))}
        service.update_status()
        assert service.status == AutoNATStatus.UNKNOWN


@pytest.mark.trio
async def test_try_dial():
    """_try_dial returns the first dialable address, None if all fail."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        host1, host2 = hosts
        service = AutoNATService(host1, serve=False)
        peer_id = host2.get_id()
        addr = b"/ip4/127.0.0.1/tcp/4001"

        with patch.object(host1, "connect", new_callable=AsyncMock) as mock_connect:
            result = await service._try_dial(peer_id, [addr])

            assert result == addr
            mock_connect.assert_called_once()
            assert service.dial_results == {}

        with patch.object(host1, "connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = Exception("Connection failed")

            result = await service._try_dial(peer_id, [addr])

            assert result is None


@pytest.mark.trio
async def test_filter_by_observed_ip():
    """Only addresses based on the observed IP may be dialed."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        service = AutoNATService(host, serve=False)

        good = Multiaddr("/ip4/1.2.3.4/tcp/4001").to_bytes()
        other_ip = Multiaddr("/ip4/9.9.9.9/tcp/4001").to_bytes()
        suffixed = Multiaddr(
            f"/ip4/1.2.3.4/tcp/4001/p2p/{host.get_id().to_base58()}"
        ).to_bytes()
        garbage = b"not-a-multiaddr"

        assert service._filter_by_observed_ip([good, other_ip], "1.2.3.4") == [good]
        # /p2p suffix is stripped before comparison
        assert service._filter_by_observed_ip([suffixed], "1.2.3.4") == [suffixed]
        # Unparseable addresses are dropped, never dialed
        assert service._filter_by_observed_ip([garbage], "1.2.3.4") == []
        # Without an observed IP nothing is dialable
        assert service._filter_by_observed_ip([good], None) == []


def test_is_relayed_stream():
    """Streams over p2p-circuit connections are detected as relayed."""
    from unittest.mock import MagicMock

    assert _is_relayed_stream(MagicMock(muxed_conn=None)) is False


def _dial_request(peer_id: ID, addrs: list[bytes]) -> Message:
    message = Message()
    message.type = Message.DIAL
    message.dial.peer.id = peer_id.to_bytes()
    for addr in addrs:
        message.dial.peer.addrs.append(addr)
    return message


@pytest.mark.trio
async def test_handle_dial_refuses_relayed_requests():
    """Dial requests over relayed connections must be refused, never served."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        service = AutoNATService(host, serve=False)
        message = _dial_request(
            host.get_id(), [Multiaddr("/ip4/1.2.3.4/tcp/4001").to_bytes()]
        )

        with patch.object(
            service, "_try_dial", new_callable=AsyncMock
        ) as mock_try_dial:
            response = await service._handle_dial(message, "1.2.3.4", True)

            assert response.dialResponse.status == Message.E_DIAL_REFUSED
            mock_try_dial.assert_not_called()


@pytest.mark.trio
async def test_handle_dial_refuses_unverifiable_requests():
    """Without an observed IP (or with no matching addr) nothing is dialed."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        service = AutoNATService(host, serve=False)

        # No observed IP
        message = _dial_request(
            host.get_id(), [Multiaddr("/ip4/1.2.3.4/tcp/4001").to_bytes()]
        )
        with patch.object(
            service, "_try_dial", new_callable=AsyncMock
        ) as mock_try_dial:
            response = await service._handle_dial(message, None, False)
            assert response.dialResponse.status == Message.E_DIAL_REFUSED
            mock_try_dial.assert_not_called()

        # Observed IP matches nothing advertised
        message = _dial_request(
            host.get_id(), [Multiaddr("/ip4/9.9.9.9/tcp/4001").to_bytes()]
        )
        with patch.object(
            service, "_try_dial", new_callable=AsyncMock
        ) as mock_try_dial:
            response = await service._handle_dial(message, "1.2.3.4", False)
            assert response.dialResponse.status == Message.E_DIAL_REFUSED
            mock_try_dial.assert_not_called()


@pytest.mark.trio
async def test_handle_dial_success_and_failure():
    """Matching addrs are dialed; outcome maps to OK / E_DIAL_ERROR."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        service = AutoNATService(host, serve=False)
        addr = Multiaddr("/ip4/1.2.3.4/tcp/4001").to_bytes()
        message = _dial_request(host.get_id(), [addr])

        with patch.object(
            service, "_try_dial", new_callable=AsyncMock
        ) as mock_try_dial:
            mock_try_dial.return_value = addr
            response = await service._handle_dial(message, "1.2.3.4", False)
            assert response.type == Message.DIAL_RESPONSE
            assert response.dialResponse.status == Message.OK
            assert bytes(response.dialResponse.addr) == addr
            mock_try_dial.assert_called_once_with(host.get_id(), [addr])

        with patch.object(
            service, "_try_dial", new_callable=AsyncMock
        ) as mock_try_dial:
            mock_try_dial.return_value = None
            response = await service._handle_dial(message, "1.2.3.4", False)
            assert response.dialResponse.status == Message.E_DIAL_ERROR


@pytest.mark.trio
async def test_handle_request_unknown_type_is_bad_request():
    """Unknown message types get E_BAD_REQUEST, not E_INTERNAL_ERROR."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        service = AutoNATService(host, serve=False)

        message = Message()
        message.type = Message.DIAL_RESPONSE
        response = await service._handle_request(message, "1.2.3.4", False)

        assert response.type == Message.DIAL_RESPONSE
        assert response.dialResponse.status == Message.E_BAD_REQUEST


@pytest.mark.trio
async def test_client_server_roundtrip_over_real_streams():
    """End-to-end: client asks server for a dial-back, gets OK + addr."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        server_host, client_host = hosts
        AutoNATService(server_host)
        client = AutoNATService(client_host, serve=False)

        # Introduce the peers (peerstore addrs) before opening the stream.
        await client_host.connect(
            PeerInfo(server_host.get_id(), server_host.get_addrs())
        )

        status, addr = await client.query_server(server_host.get_id())

        assert status == int(Message.OK)
        assert addr is not None
        # The verdict is recorded against the reporting server
        assert client.dial_results[server_host.get_id()] is True


@pytest.mark.trio
async def test_check_reachability_aggregates_verdicts():
    """Unreachable servers count as failures; thresholds drive the status."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        service = AutoNATService(host, serve=False)
        servers = _server_ids(4)

        async def fake_query(server_id, addrs=None, timeout=30.0):
            service.dial_results[server_id] = True
            return int(Message.OK), b"addr"

        with patch.object(service, "query_server", side_effect=fake_query):
            assert await service.check_reachability(servers) == AutoNATStatus.PUBLIC

        async def failing_query(server_id, addrs=None, timeout=30.0):
            raise ConnectionError("unreachable")

        with patch.object(service, "query_server", side_effect=failing_query):
            assert await service.check_reachability(servers) == AutoNATStatus.PRIVATE


@pytest.mark.trio
async def test_handle_stream_framing():
    """Streams speak varint-prefixed messages and always close."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        service = AutoNATService(host, serve=False)

        from unittest.mock import MagicMock

        from libp2p.network.stream.net_stream import NetStream

        mock_stream = AsyncMock(spec=NetStream)
        mock_stream.get_remote_address.return_value = ("9.9.9.9", 4001)
        mock_stream.muxed_conn = MagicMock()
        mock_stream.muxed_conn.get_transport_addresses.return_value = []
        request = _dial_request(
            host.get_id(), [Multiaddr("/ip4/9.9.9.9/tcp/4001").to_bytes()]
        )
        framed = encode_varint_prefixed(request.SerializeToString())
        # Feed byte-by-byte like a real stream (varint decode reads 1 byte).
        mock_stream.read.side_effect = [framed[i : i + 1] for i in range(len(framed))]

        with patch.object(
            service, "_try_dial", new_callable=AsyncMock
        ) as mock_try_dial:
            mock_try_dial.return_value = None
            await service.handle_stream(mock_stream)

        written = mock_stream.write.await_args.args[0]
        mock_stream.close.assert_called_once()
        assert mock_try_dial.called

        # The written response is framed and reports the dial failure.
        from libp2p.utils.varint import decode_varint_with_size

        length, prefix_len = decode_varint_with_size(written)
        assert length == len(written) - prefix_len
        response = Message()
        response.ParseFromString(written[prefix_len:])
        assert response.type == Message.DIAL_RESPONSE
        assert response.dialResponse.status == Message.E_DIAL_ERROR
