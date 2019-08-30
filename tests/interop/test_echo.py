import asyncio

from multiaddr import Multiaddr
import pytest

from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.typing import TProtocol

from .constants import PEXPECT_NEW_LINE
from .envs import GO_BIN_PATH

ECHO_PATH = GO_BIN_PATH / "echo"
ECHO_PROTOCOL_ID = TProtocol("/echo/1.0.0")


async def make_echo_proc(
    proc_factory, port: int, is_secure: bool, destination: Multiaddr = None
):
    args = [f"-l={port}"]
    if not is_secure:
        args.append("-insecure")
    if destination is not None:
        args.append(f"-d={str(destination)}")
    echo_proc = proc_factory(str(ECHO_PATH), args)
    await echo_proc.expect(r"I am ([\w\./]+)" + PEXPECT_NEW_LINE, async_=True)
    maddr_str_ipfs = echo_proc.match.group(1)
    maddr_str = maddr_str_ipfs.replace("ipfs", "p2p")
    maddr = Multiaddr(maddr_str)
    go_pinfo = info_from_p2p_addr(maddr)
    if destination is None:
        await echo_proc.expect("listening for connections", async_=True)
    return echo_proc, go_pinfo


@pytest.mark.parametrize("num_hosts", (1,))
@pytest.mark.asyncio
async def test_insecure_conn_py_to_go(
    hosts, proc_factory, is_host_secure, unused_tcp_port
):
    go_proc, go_pinfo = await make_echo_proc(
        proc_factory, unused_tcp_port, is_host_secure
    )

    host = hosts[0]
    await host.connect(go_pinfo)
    await go_proc.expect("swarm listener accepted connection", async_=True)
    s = await host.new_stream(go_pinfo.peer_id, [ECHO_PROTOCOL_ID])

    await go_proc.expect("Got a new stream!", async_=True)
    data = "data321123\n"
    await s.write(data.encode())
    await go_proc.expect(f"read: {data[:-1]}", async_=True)
    echoed_resp = await s.read(len(data))
    assert echoed_resp.decode() == data
    await s.close()


@pytest.mark.parametrize("num_hosts", (1,))
@pytest.mark.asyncio
async def test_insecure_conn_go_to_py(
    hosts, proc_factory, is_host_secure, unused_tcp_port
):
    host = hosts[0]
    expected_data = "Hello, world!\n"
    reply_data = "Replyooo!\n"
    event_handler_finished = asyncio.Event()

    async def _handle_echo(stream):
        read_data = await stream.read(len(expected_data))
        assert read_data == expected_data.encode()
        event_handler_finished.set()
        await stream.write(reply_data.encode())
        await stream.close()

    host.set_stream_handler(ECHO_PROTOCOL_ID, _handle_echo)
    py_maddr = host.get_addrs()[0]
    go_proc, _ = await make_echo_proc(
        proc_factory, unused_tcp_port, is_host_secure, py_maddr
    )
    await go_proc.expect("connect with peer", async_=True)
    await go_proc.expect("opened stream", async_=True)
    await event_handler_finished.wait()
    await go_proc.expect(f"read reply: .*{reply_data.rstrip()}.*", async_=True)
