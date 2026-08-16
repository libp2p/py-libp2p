"""
Tests for Noise prologue construction and DataChannelReadWriter.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import trio

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.x25519 import create_new_key_pair as create_x25519_key_pair
from libp2p.peer.id import ID
from libp2p.transport.webrtc.certificate import WebRTCCertificate
from libp2p.transport.webrtc.constants import (
    MAX_MESSAGE_SIZE,
    MAX_PAYLOAD_SIZE,
    NOISE_PROLOGUE_PREFIX,
)
from libp2p.transport.webrtc.exceptions import WebRTCHandshakeError
from libp2p.transport.webrtc.noise_handshake import (
    DataChannelReadWriter,
    build_noise_prologue,
    perform_noise_handshake,
)
from libp2p.transport.webrtc.pb.webrtc_pb2 import Message
from libp2p.transport.webrtc.stream import _frame


class TestBuildNoisePrologue:
    def test_prologue_starts_with_prefix(self):
        dialer_fp = b"\x01" * 32
        server_fp = b"\x02" * 32
        prologue = build_noise_prologue(dialer_fp, server_fp)
        assert prologue.startswith(NOISE_PROLOGUE_PREFIX)

    def test_prologue_contains_multihash_encoded_fingerprints(self):
        dialer_fp = b"\xaa" * 32
        server_fp = b"\xbb" * 32
        prologue = build_noise_prologue(dialer_fp, server_fp)
        # After prefix: dialer_mh (34 bytes) + server_mh (34 bytes)
        after_prefix = prologue[len(NOISE_PROLOGUE_PREFIX) :]
        assert len(after_prefix) == 68  # 34 + 34
        # Verify multihash headers
        assert after_prefix[0] == 0x12  # SHA-256 code
        assert after_prefix[1] == 32  # digest length
        assert after_prefix[2:34] == dialer_fp
        assert after_prefix[34] == 0x12
        assert after_prefix[35] == 32
        assert after_prefix[36:68] == server_fp

    def test_prologue_total_length(self):
        dialer_fp = b"\x00" * 32
        server_fp = b"\xff" * 32
        prologue = build_noise_prologue(dialer_fp, server_fp)
        # prefix (20) + dialer_mh (34) + server_mh (34) = 88
        expected = len(NOISE_PROLOGUE_PREFIX) + 34 + 34
        assert len(prologue) == expected

    def test_prologue_is_asymmetric(self):
        """Swapping dialer/server produces different prologues."""
        fp_a = b"\x01" * 32
        fp_b = b"\x02" * 32
        p1 = build_noise_prologue(fp_a, fp_b)
        p2 = build_noise_prologue(fp_b, fp_a)
        assert p1 != p2

    def test_prologue_with_real_fingerprints(self):
        cert_a = WebRTCCertificate.generate()
        cert_b = WebRTCCertificate.generate()
        prologue = build_noise_prologue(cert_a.fingerprint, cert_b.fingerprint)
        assert len(prologue) == len(NOISE_PROLOGUE_PREFIX) + 68


class TestDataChannelReadWriter:
    @pytest.mark.trio
    async def test_write_frames_as_stream_message(self):
        """Wire format = uvarint-prefixed webrtc.pb.Message (spec/go/js)."""
        send_cb = AsyncMock()
        rw = DataChannelReadWriter(
            send_cb=send_cb, recv_cb=AsyncMock(), is_initiator=True
        )
        await rw.write(b"hello")
        send_cb.assert_called_once_with(_frame(Message(message=b"hello")))

    @pytest.mark.trio
    async def test_write_chunks_large_payloads(self):
        send_cb = AsyncMock()
        rw = DataChannelReadWriter(
            send_cb=send_cb, recv_cb=AsyncMock(), is_initiator=True
        )
        await rw.write(b"x" * (MAX_PAYLOAD_SIZE + 1))
        assert send_cb.await_count == 2
        for call in send_cb.await_args_list:
            assert len(call.args[0]) <= MAX_MESSAGE_SIZE

    @pytest.mark.trio
    async def test_read_unframes_stream_message(self):
        recv_cb = AsyncMock(return_value=_frame(Message(message=b"data-from-peer")))
        rw = DataChannelReadWriter(
            send_cb=AsyncMock(), recv_cb=recv_cb, is_initiator=False
        )
        assert await rw.read() == b"data-from-peer"

    @pytest.mark.trio
    async def test_read_stops_at_fin(self):
        frames = [
            _frame(Message(message=b"ab")),
            _frame(Message(flag=Message.FIN)),
        ]
        rw = DataChannelReadWriter(
            send_cb=AsyncMock(),
            recv_cb=AsyncMock(side_effect=frames),
            is_initiator=False,
        )
        assert await rw.read(4) == b"ab"  # short read: peer finished

    @pytest.mark.trio
    async def test_read_rejects_malformed_frame(self):
        rw = DataChannelReadWriter(
            send_cb=AsyncMock(),
            recv_cb=AsyncMock(return_value=b"\xff\xff\xff"),
            is_initiator=False,
        )
        with pytest.raises(WebRTCHandshakeError):
            await rw.read(1)

    @pytest.mark.trio
    async def test_close_is_noop(self):
        rw = DataChannelReadWriter(
            send_cb=AsyncMock(),
            recv_cb=AsyncMock(),
            is_initiator=True,
        )
        await rw.close()  # Should not raise

    def test_is_initiator_property(self):
        rw = DataChannelReadWriter(
            send_cb=AsyncMock(),
            recv_cb=AsyncMock(),
            is_initiator=True,
        )
        assert rw.is_initiator is True

    def test_transport_addresses_empty(self):
        rw = DataChannelReadWriter(
            send_cb=AsyncMock(),
            recv_cb=AsyncMock(),
            is_initiator=True,
        )
        assert rw.get_transport_addresses() == []

    @pytest.mark.trio
    async def test_read_n_splits_and_joins_channel_messages(self):
        """
        ``read(n)`` must honour ``n``: the Noise packet reader asks for the
        2-byte length prefix first, then the payload, while a data channel
        delivers whole messages.
        """
        messages = [_frame(Message(message=m)) for m in (b"\x00\x03abc", b"de", b"fgh")]
        recv_cb = AsyncMock(side_effect=messages)
        rw = DataChannelReadWriter(
            send_cb=AsyncMock(), recv_cb=recv_cb, is_initiator=False
        )
        assert await rw.read(2) == b"\x00\x03"  # prefix only, rest buffered
        assert await rw.read(3) == b"abc"  # from buffer, no recv
        assert recv_cb.await_count == 1
        assert await rw.read(4) == b"defg"  # spans two channel messages
        assert await rw.read() == b"h"  # n=None drains the remainder


def _memory_channel_pair() -> tuple[DataChannelReadWriter, DataChannelReadWriter]:
    """Two DataChannelReadWriters wired back-to-back over trio memory channels."""
    a_to_b_send, a_to_b_recv = trio.open_memory_channel[bytes](16)
    b_to_a_send, b_to_a_recv = trio.open_memory_channel[bytes](16)

    async def _send_a(data: bytes) -> None:
        await a_to_b_send.send(data)

    async def _recv_a() -> bytes:
        return await b_to_a_recv.receive()

    async def _send_b(data: bytes) -> None:
        await b_to_a_send.send(data)

    async def _recv_b() -> bytes:
        return await a_to_b_recv.receive()

    dialer = DataChannelReadWriter(_send_a, _recv_a, is_initiator=False)
    server = DataChannelReadWriter(_send_b, _recv_b, is_initiator=True)
    return dialer, server


class TestPerformNoiseHandshake:
    @pytest.mark.trio
    async def test_spec_roles_server_initiates_dialer_responds(self):
        """
        Server = Noise initiator without knowing the dialer's ID; dialer =
        responder. Both use the role-ordered prologue and learn the peer's ID.
        """
        dialer_kp, server_kp = create_new_key_pair(), create_new_key_pair()
        dialer_id, server_id = (
            ID.from_pubkey(dialer_kp.public_key),
            ID.from_pubkey(server_kp.public_key),
        )
        dialer_cert, server_cert = (
            WebRTCCertificate.generate(),
            (WebRTCCertificate.generate()),
        )
        dialer_rw, server_rw = _memory_channel_pair()
        seen: dict[str, ID] = {}

        async def _server() -> None:
            seen["server"] = await perform_noise_handshake(
                conn=server_rw,
                local_peer=server_id,
                libp2p_privkey=server_kp.private_key,
                noise_static_key=create_x25519_key_pair().private_key,
                dialer_fingerprint=dialer_cert.fingerprint,
                server_fingerprint=server_cert.fingerprint,
                is_initiator=True,
                remote_peer=None,
            )

        async def _dialer() -> None:
            seen["dialer"] = await perform_noise_handshake(
                conn=dialer_rw,
                local_peer=dialer_id,
                libp2p_privkey=dialer_kp.private_key,
                noise_static_key=create_x25519_key_pair().private_key,
                dialer_fingerprint=dialer_cert.fingerprint,
                server_fingerprint=server_cert.fingerprint,
                is_initiator=False,
            )

        with trio.fail_after(10):
            async with trio.open_nursery() as nursery:
                nursery.start_soon(_server)
                nursery.start_soon(_dialer)

        assert seen["server"] == dialer_id
        assert seen["dialer"] == server_id

    @pytest.mark.trio
    async def test_prologue_mismatch_fails(self):
        """A side that gets the fingerprint order wrong cannot complete."""
        dialer_kp, server_kp = create_new_key_pair(), create_new_key_pair()
        dialer_cert, server_cert = (
            WebRTCCertificate.generate(),
            (WebRTCCertificate.generate()),
        )
        dialer_rw, server_rw = _memory_channel_pair()
        errors: list[BaseException] = []

        async def _run(rw, kp, is_initiator, dialer_fp, server_fp) -> None:
            try:
                await perform_noise_handshake(
                    conn=rw,
                    local_peer=ID.from_pubkey(kp.public_key),
                    libp2p_privkey=kp.private_key,
                    noise_static_key=create_x25519_key_pair().private_key,
                    dialer_fingerprint=dialer_fp,
                    server_fingerprint=server_fp,
                    is_initiator=is_initiator,
                )
            except WebRTCHandshakeError as e:
                errors.append(e)

        with trio.move_on_after(10):
            async with trio.open_nursery() as nursery:
                nursery.start_soon(
                    _run,
                    server_rw,
                    server_kp,
                    True,
                    dialer_cert.fingerprint,
                    server_cert.fingerprint,
                )
                # dialer swaps the order -> different prologue -> decrypt fails
                nursery.start_soon(
                    _run,
                    dialer_rw,
                    dialer_kp,
                    False,
                    server_cert.fingerprint,
                    dialer_cert.fingerprint,
                )
                # first failure aborts; cancel the peer stuck waiting
                while not errors:
                    await trio.sleep(0.01)
                nursery.cancel_scope.cancel()

        assert errors
