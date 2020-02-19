import re

from multiaddr import Multiaddr
from p2pclient.utils import get_unused_tcp_port
import pytest
import trio

from libp2p.peer.peerinfo import PeerInfo, info_from_p2p_addr
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID
from libp2p.tools.factories import HostFactory
from libp2p.tools.interop.envs import GO_BIN_PATH
from libp2p.tools.interop.process import BaseInteractiveProcess
from libp2p.typing import TProtocol

ECHO_PATH = GO_BIN_PATH / "echo"
ECHO_PROTOCOL_ID = TProtocol("/echo/1.0.0")


class EchoProcess(BaseInteractiveProcess):
    port: int
    _peer_info: PeerInfo

    def __init__(
        self, port: int, security_protocol: TProtocol, destination: Multiaddr = None
    ) -> None:
        args = [f"-l={port}"]
        if security_protocol == PLAINTEXT_PROTOCOL_ID:
            args.append("-insecure")
        if destination is not None:
            args.append(f"-d={str(destination)}")

        patterns = [b"I am"]
        if destination is None:
            patterns.append(b"listening for connections")

        self.args = args
        self.cmd = str(ECHO_PATH)
        self.patterns = patterns
        self.bytes_read = bytearray()
        self.event_ready = trio.Event()

        self.port = port
        self._peer_info = None
        self.regex_pat = re.compile(br"I am ([\w\./]+)")

    @property
    def peer_info(self) -> None:
        if self._peer_info is not None:
            return self._peer_info
        if not self.event_ready.is_set():
            raise Exception("process is not ready yet. failed to parse the peer info")
        # Example:
        # b"I am /ip4/127.0.0.1/tcp/56171/ipfs/QmU41TRPs34WWqa1brJEojBLYZKrrBcJq9nyNfVvSrbZUJ\n"
        m = re.search(br"I am ([\w\./]+)", self.bytes_read)
        if m is None:
            raise Exception("failed to find the pattern for the listening multiaddr")
        maddr_bytes_str_ipfs = m.group(1)
        maddr_str = maddr_bytes_str_ipfs.decode().replace("ipfs", "p2p")
        maddr = Multiaddr(maddr_str)
        self._peer_info = info_from_p2p_addr(maddr)
        return self._peer_info


@pytest.mark.trio
async def test_insecure_conn_py_to_go(security_protocol):
    async with HostFactory.create_batch_and_listen(
        1, security_protocol=security_protocol
    ) as hosts:
        go_proc = EchoProcess(get_unused_tcp_port(), security_protocol)
        await go_proc.start()

        host = hosts[0]
        peer_info = go_proc.peer_info
        await host.connect(peer_info)
        s = await host.new_stream(peer_info.peer_id, [ECHO_PROTOCOL_ID])
        data = "data321123\n"
        await s.write(data.encode())
        echoed_resp = await s.read(len(data))
        assert echoed_resp.decode() == data
        await s.close()


@pytest.mark.trio
async def test_insecure_conn_go_to_py(security_protocol):
    async with HostFactory.create_batch_and_listen(
        1, security_protocol=security_protocol
    ) as hosts:
        host = hosts[0]
        expected_data = "Hello, world!\n"
        reply_data = "Replyooo!\n"
        event_handler_finished = trio.Event()

        async def _handle_echo(stream):
            read_data = await stream.read(len(expected_data))
            assert read_data == expected_data.encode()
            event_handler_finished.set()
            await stream.write(reply_data.encode())
            await stream.close()

        host.set_stream_handler(ECHO_PROTOCOL_ID, _handle_echo)
        py_maddr = host.get_addrs()[0]
        go_proc = EchoProcess(get_unused_tcp_port(), security_protocol, py_maddr)
        await go_proc.start()
        await event_handler_finished.wait()
