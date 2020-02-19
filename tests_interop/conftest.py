import anyio
from async_exit_stack import AsyncExitStack
from p2pclient.datastructures import StreamInfo
from p2pclient.utils import get_unused_tcp_port
import pytest
import trio

from libp2p.io.abc import ReadWriteCloser
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID
from libp2p.tools.factories import HostFactory, PubsubFactory
from libp2p.tools.interop.daemon import make_p2pd
from libp2p.tools.interop.utils import connect


@pytest.fixture
def security_protocol():
    return PLAINTEXT_PROTOCOL_ID


@pytest.fixture
def num_p2pds():
    return 1


@pytest.fixture
def is_gossipsub():
    return True


@pytest.fixture
def is_pubsub_signing():
    return True


@pytest.fixture
def is_pubsub_signing_strict():
    return True


@pytest.fixture
async def p2pds(
    num_p2pds,
    security_protocol,
    is_gossipsub,
    is_pubsub_signing,
    is_pubsub_signing_strict,
):
    async with AsyncExitStack() as stack:
        p2pds = [
            await stack.enter_async_context(
                make_p2pd(
                    get_unused_tcp_port(),
                    get_unused_tcp_port(),
                    security_protocol,
                    is_gossipsub=is_gossipsub,
                    is_pubsub_signing=is_pubsub_signing,
                    is_pubsub_signing_strict=is_pubsub_signing_strict,
                )
            )
            for _ in range(num_p2pds)
        ]
        try:
            yield p2pds
        finally:
            for p2pd in p2pds:
                await p2pd.close()


@pytest.fixture
async def pubsubs(num_hosts, security_protocol, is_gossipsub, is_pubsub_signing_strict):
    if is_gossipsub:
        yield PubsubFactory.create_batch_with_gossipsub(
            num_hosts,
            security_protocol=security_protocol,
            strict_signing=is_pubsub_signing_strict,
        )
    else:
        yield PubsubFactory.create_batch_with_floodsub(
            num_hosts, security_protocol, strict_signing=is_pubsub_signing_strict
        )


class DaemonStream(ReadWriteCloser):
    stream_info: StreamInfo
    stream: anyio.abc.SocketStream

    def __init__(self, stream_info: StreamInfo, stream: anyio.abc.SocketStream) -> None:
        self.stream_info = stream_info
        self.stream = stream

    async def close(self) -> None:
        await self.stream.close()

    async def read(self, n: int = None) -> bytes:
        return await self.stream.receive_some(n)

    async def write(self, data: bytes) -> None:
        return await self.stream.send_all(data)


@pytest.fixture
async def is_to_fail_daemon_stream():
    return False


@pytest.fixture
async def py_to_daemon_stream_pair(p2pds, security_protocol, is_to_fail_daemon_stream):
    async with HostFactory.create_batch_and_listen(
        1, security_protocol=security_protocol
    ) as hosts:
        assert len(p2pds) >= 1
        host = hosts[0]
        p2pd = p2pds[0]
        protocol_id = "/protocol/id/123"
        stream_py = None
        stream_daemon = None
        event_stream_handled = trio.Event()
        await connect(host, p2pd)

        async def daemon_stream_handler(stream_info, stream):
            nonlocal stream_daemon
            stream_daemon = DaemonStream(stream_info, stream)
            event_stream_handled.set()
            await trio.hazmat.checkpoint()

        await p2pd.control.stream_handler(protocol_id, daemon_stream_handler)
        # Sleep for a while to wait for the handler being registered.
        await trio.sleep(0.01)

        if is_to_fail_daemon_stream:
            # FIXME: This is a workaround to make daemon reset the stream.
            #   We intentionally close the listener on the python side, it makes the connection from
            #   daemon to us fail, and therefore the daemon resets the opened stream on their side.
            #   Reference: https://github.com/libp2p/go-libp2p-daemon/blob/b95e77dbfcd186ccf817f51e95f73f9fd5982600/stream.go#L47-L50  # noqa: E501
            #   We need it because we want to test against `stream_py` after the remote side(daemon)
            #   is reset. This should be removed after the API `stream.reset` is exposed in daemon
            #   some day.
            await p2pds[0].control.control.close()
        stream_py = await host.new_stream(p2pd.peer_id, [protocol_id])
        if not is_to_fail_daemon_stream:
            await event_stream_handled.wait()
        # NOTE: If `is_to_fail_daemon_stream == True`, then `stream_daemon == None`.
        yield stream_py, stream_daemon
