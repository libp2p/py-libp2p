import asyncio
import time
from typing import Any, List

import multiaddr
from multiaddr import Multiaddr
from p2pclient import Client
import pytest

from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo, info_from_p2p_addr

from .constants import LOCALHOST_IP
from .envs import GO_BIN_PATH

P2PD_PATH = GO_BIN_PATH / "p2pd"


TIMEOUT_DURATION = 30


async def try_until_success(coro_func, timeout=TIMEOUT_DURATION):
    """
    Keep running ``coro_func`` until either it succeed or time is up.

    All arguments of ``coro_func`` should be filled, i.e. it should be
    called without arguments.
    """
    t_start = time.monotonic()
    while True:
        result = await coro_func()
        if result:
            break
        if (time.monotonic() - t_start) >= timeout:
            # timeout
            pytest.fail(f"{coro_func} is still failing after `{timeout}` seconds")
        await asyncio.sleep(0.01)


class P2PDProcess:
    proc: asyncio.subprocess.Process
    cmd: str = str(P2PD_PATH)
    args: List[Any]
    is_proc_running: bool

    _tasks: List["asyncio.Future[Any]"]

    def __init__(
        self,
        control_maddr: Multiaddr,
        is_secure: bool,
        is_pubsub_enabled: bool = True,
        is_gossipsub: bool = True,
        is_pubsub_signing: bool = False,
        is_pubsub_signing_strict: bool = False,
    ) -> None:
        args = [f"-listen={str(control_maddr)}"]
        # NOTE: To support `-insecure`, we need to hack `go-libp2p-daemon`.
        if not is_secure:
            args.append("-insecure=true")
        if is_pubsub_enabled:
            args.append("-pubsub")
            if is_gossipsub:
                args.append("-pubsubRouter=gossipsub")
            else:
                args.append("-pubsubRouter=floodsub")
            if not is_pubsub_signing:
                args.append("-pubsubSign=false")
            if not is_pubsub_signing_strict:
                args.append("-pubsubSignStrict=false")
            # NOTE:
            #   Two other params are possibly what we want to configure:
            #   - gossipsubHeartbeatInterval: GossipSubHeartbeatInitialDelay = 100 * time.Millisecond  # noqa: E501
            #   - gossipsubHeartbeatInitialDelay: GossipSubHeartbeatInterval = 1 * time.Second
            #   Referece: https://github.com/libp2p/go-libp2p-daemon/blob/b95e77dbfcd186ccf817f51e95f73f9fd5982600/p2pd/main.go#L348-L353  # noqa: E501
        self.args = args
        self.is_proc_running = False

        self._tasks = []

    async def wait_until_ready(self):
        lines_head_pattern = (b"Control socket:", b"Peer ID:", b"Peer Addrs:")
        lines_head_occurred = {line: False for line in lines_head_pattern}

        async def read_from_daemon_and_check():
            line = await self.proc.stdout.readline()
            for head_pattern in lines_head_occurred:
                if line.startswith(head_pattern):
                    lines_head_occurred[head_pattern] = True
            return all([value for value in lines_head_occurred.values()])

        await try_until_success(read_from_daemon_and_check)
        # Sleep a little bit to ensure the listener is up after logs are emitted.
        await asyncio.sleep(0.01)

    async def start_printing_logs(self) -> None:
        async def _print_from_stream(
            src_name: str, reader: asyncio.StreamReader
        ) -> None:
            while True:
                line = await reader.readline()
                if line != b"":
                    print(f"{src_name}\t: {line.rstrip().decode()}")
                await asyncio.sleep(0.01)

        self._tasks.append(
            asyncio.ensure_future(_print_from_stream("out", self.proc.stdout))
        )
        self._tasks.append(
            asyncio.ensure_future(_print_from_stream("err", self.proc.stderr))
        )
        await asyncio.sleep(0)

    async def start(self) -> None:
        if self.is_proc_running:
            return
        self.proc = await asyncio.subprocess.create_subprocess_exec(
            self.cmd,
            *self.args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            bufsize=0,
        )
        self.is_proc_running = True
        await self.wait_until_ready()
        await self.start_printing_logs()

    async def close(self) -> None:
        if self.is_proc_running:
            self.proc.terminate()
            await self.proc.wait()
            self.is_proc_running = False
        for task in self._tasks:
            task.cancel()


class Daemon:
    p2pd_proc: P2PDProcess
    control: Client
    peer_info: PeerInfo

    def __init__(
        self, p2pd_proc: P2PDProcess, control: Client, peer_info: PeerInfo
    ) -> None:
        self.p2pd_proc = p2pd_proc
        self.control = control
        self.peer_info = peer_info

    def __repr__(self) -> str:
        return f"<Daemon {self.peer_id.to_string()[2:8]}>"

    @property
    def peer_id(self) -> ID:
        return self.peer_info.peer_id

    @property
    def listen_maddr(self) -> Multiaddr:
        return self.peer_info.addrs[0]

    async def close(self) -> None:
        await self.p2pd_proc.close()
        await self.control.close()


async def make_p2pd(
    daemon_control_port: int,
    client_callback_port: int,
    is_secure: bool,
    is_pubsub_enabled=True,
    is_gossipsub=True,
    is_pubsub_signing=False,
    is_pubsub_signing_strict=False,
) -> Daemon:
    control_maddr = Multiaddr(f"/ip4/{LOCALHOST_IP}/tcp/{daemon_control_port}")
    p2pd_proc = P2PDProcess(
        control_maddr,
        is_secure,
        is_pubsub_enabled,
        is_gossipsub,
        is_pubsub_signing,
        is_pubsub_signing_strict,
    )
    await p2pd_proc.start()
    client_callback_maddr = Multiaddr(f"/ip4/{LOCALHOST_IP}/tcp/{client_callback_port}")
    p2pc = Client(control_maddr, client_callback_maddr)
    await p2pc.listen()
    peer_id, maddrs = await p2pc.identify()
    listen_maddr: Multiaddr = None
    for maddr in maddrs:
        try:
            ip = maddr.value_for_protocol(multiaddr.protocols.P_IP4)
            # NOTE: Check if this `maddr` uses `tcp`.
            maddr.value_for_protocol(multiaddr.protocols.P_TCP)
        except multiaddr.exceptions.ProtocolLookupError:
            continue
        if ip == LOCALHOST_IP:
            listen_maddr = maddr
            break
    assert listen_maddr is not None, "no loopback maddr is found"
    peer_info = info_from_p2p_addr(
        listen_maddr.encapsulate(Multiaddr(f"/p2p/{peer_id.to_string()}"))
    )
    return Daemon(p2pd_proc, p2pc, peer_info)
