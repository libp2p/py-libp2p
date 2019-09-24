import asyncio
import sys
from typing import Union

from p2pclient.datastructures import StreamInfo
import pexpect
import pytest

from libp2p.io.abc import ReadWriteCloser
from tests.configs import LISTEN_MADDR
from tests.factories import (
    FloodsubFactory,
    GossipsubFactory,
    HostFactory,
    PubsubFactory,
)
from tests.pubsub.configs import GOSSIPSUB_PARAMS

from .daemon import Daemon, make_p2pd
from .utils import connect


@pytest.fixture
def is_host_secure():
    return False


@pytest.fixture
def num_hosts():
    return 3


@pytest.fixture
async def hosts(num_hosts, is_host_secure):
    _hosts = HostFactory.create_batch(num_hosts, is_secure=is_host_secure)
    await asyncio.gather(
        *[_host.get_network().listen(LISTEN_MADDR) for _host in _hosts]
    )
    try:
        yield _hosts
    finally:
        # TODO: It's possible that `close` raises exceptions currently,
        #   due to the connection reset things. Though we don't care much about that when
        #   cleaning up the tasks, it is probably better to handle the exceptions properly.
        await asyncio.gather(
            *[_host.close() for _host in _hosts], return_exceptions=True
        )


@pytest.fixture
def proc_factory():
    procs = []

    def call_proc(cmd, args, logfile=None, encoding=None):
        if logfile is None:
            logfile = sys.stdout
        if encoding is None:
            encoding = "utf-8"
        proc = pexpect.spawn(cmd, args, logfile=logfile, encoding=encoding)
        procs.append(proc)
        return proc

    try:
        yield call_proc
    finally:
        for proc in procs:
            proc.close()


@pytest.fixture
def num_p2pds():
    return 1


@pytest.fixture
def is_gossipsub():
    return True


@pytest.fixture
async def p2pds(num_p2pds, is_host_secure, is_gossipsub, unused_tcp_port_factory):
    p2pds: Union[Daemon, Exception] = await asyncio.gather(
        *[
            make_p2pd(
                unused_tcp_port_factory(),
                unused_tcp_port_factory(),
                is_host_secure,
                is_gossipsub=is_gossipsub,
            )
            for _ in range(num_p2pds)
        ],
        return_exceptions=True,
    )
    p2pds_succeeded = tuple(p2pd for p2pd in p2pds if isinstance(p2pd, Daemon))
    if len(p2pds_succeeded) != len(p2pds):
        # Not all succeeded. Close the succeeded ones and print the failed ones(exceptions).
        await asyncio.gather(*[p2pd.close() for p2pd in p2pds_succeeded])
        exceptions = tuple(p2pd for p2pd in p2pds if isinstance(p2pd, Exception))
        raise Exception(f"not all p2pds succeed: first exception={exceptions[0]}")
    try:
        yield p2pds
    finally:
        await asyncio.gather(*[p2pd.close() for p2pd in p2pds])


@pytest.fixture
def pubsubs(num_hosts, hosts, is_gossipsub):
    if is_gossipsub:
        routers = GossipsubFactory.create_batch(num_hosts, **GOSSIPSUB_PARAMS._asdict())
    else:
        routers = FloodsubFactory.create_batch(num_hosts)
    _pubsubs = tuple(
        PubsubFactory(host=host, router=router) for host, router in zip(hosts, routers)
    )
    yield _pubsubs
    # TODO: Clean up


class DaemonStream(ReadWriteCloser):
    stream_info: StreamInfo
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter

    def __init__(
        self,
        stream_info: StreamInfo,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self.stream_info = stream_info
        self.reader = reader
        self.writer = writer

    async def close(self) -> None:
        self.writer.close()
        await self.writer.wait_closed()

    async def read(self, n: int = -1) -> bytes:
        return await self.reader.read(n)

    async def write(self, data: bytes) -> int:
        return self.writer.write(data)


@pytest.fixture
async def is_to_fail_daemon_stream():
    return False


@pytest.fixture
async def py_to_daemon_stream_pair(hosts, p2pds, is_to_fail_daemon_stream):
    assert len(hosts) >= 1
    assert len(p2pds) >= 1
    host = hosts[0]
    p2pd = p2pds[0]
    protocol_id = "/protocol/id/123"
    stream_py = None
    stream_daemon = None
    event_stream_handled = asyncio.Event()
    await connect(host, p2pd)

    async def daemon_stream_handler(stream_info, reader, writer):
        nonlocal stream_daemon
        stream_daemon = DaemonStream(stream_info, reader, writer)
        event_stream_handled.set()

    await p2pd.control.stream_handler(protocol_id, daemon_stream_handler)
    # Sleep for a while to wait for the handler being registered.
    await asyncio.sleep(0.01)

    if is_to_fail_daemon_stream:
        # FIXME: This is a workaround to make daemon reset the stream.
        #   We intentionally close the listener on the python side, it makes the connection from
        #   daemon to us fail, and therefore the daemon resets the opened stream on their side.
        #   Reference: https://github.com/libp2p/go-libp2p-daemon/blob/b95e77dbfcd186ccf817f51e95f73f9fd5982600/stream.go#L47-L50  # noqa: E501
        #   We need it because we want to test against `stream_py` after the remote side(daemon)
        #   is reset. This should be removed after the API `stream.reset` is exposed in daemon
        #   some day.
        listener = p2pds[0].control.control.listener
        listener.close()
        await listener.wait_closed()
    stream_py = await host.new_stream(p2pd.peer_id, [protocol_id])
    if not is_to_fail_daemon_stream:
        await event_stream_handled.wait()
    # NOTE: If `is_to_fail_daemon_stream == True`, then `stream_daemon == None`.
    yield stream_py, stream_daemon
