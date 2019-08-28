import asyncio
import os
import pathlib
import sys

from multiaddr import Multiaddr
import pexpect
import pytest

from libp2p import generate_new_rsa_identity, new_node
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport
from libp2p.typing import TProtocol
from tests.configs import LISTEN_MADDR


GOPATH = pathlib.Path(os.environ["GOPATH"])
ECHO_PATH = GOPATH / "bin" / "echo"
ECHO_PROTOCOL_ID = TProtocol("/echo/1.0.0")
NEW_LINE = "\r\n"


@pytest.mark.asyncio
async def test_insecure_conn_py_to_go(unused_tcp_port):
    try:
        go_proc = pexpect.spawn(
            str(ECHO_PATH),
            [f"-l={unused_tcp_port}", "-insecure"],
            logfile=sys.stdout,
            encoding="utf-8",
        )
        await go_proc.expect(r"I am ([\w\./]+)" + NEW_LINE, async_=True)
        maddr_str = go_proc.match.group(1)
        maddr_str = maddr_str.replace("ipfs", "p2p")
        maddr = Multiaddr(maddr_str)
        go_pinfo = info_from_p2p_addr(maddr)
        await go_proc.expect("listening for connections", async_=True)

        key_pair = generate_new_rsa_identity()
        insecure_tpt = InsecureTransport(key_pair)
        host = await new_node(
            key_pair=key_pair, sec_opt={PLAINTEXT_PROTOCOL_ID: insecure_tpt}
        )
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
    finally:
        go_proc.close()


@pytest.mark.asyncio
async def test_insecure_conn_go_to_py(unused_tcp_port):
    key_pair = generate_new_rsa_identity()
    insecure_tpt = InsecureTransport(key_pair)
    host = await new_node(
        key_pair=key_pair, sec_opt={PLAINTEXT_PROTOCOL_ID: insecure_tpt}
    )
    await host.get_network().listen(LISTEN_MADDR)
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
    go_proc = pexpect.spawn(
        str(ECHO_PATH),
        [f"-l={unused_tcp_port}", "-insecure", f"-d={str(py_maddr)}"],
        logfile=sys.stdout,
        encoding="utf-8",
    )
    try:
        await go_proc.expect(r"I am ([\w\./]+)" + NEW_LINE, async_=True)
        await go_proc.expect("connect with peer", async_=True)
        await go_proc.expect("opened stream", async_=True)
        await event_handler_finished.wait()
        await go_proc.expect(f"read reply: .*{reply_data.rstrip()}.*", async_=True)
    finally:
        go_proc.close()
