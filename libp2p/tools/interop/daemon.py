from typing import AsyncIterator

from async_generator import asynccontextmanager
import multiaddr
from multiaddr import Multiaddr
from p2pclient import Client
import trio

from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo, info_from_p2p_addr

from .constants import LOCALHOST_IP
from .envs import GO_BIN_PATH
from .process import BaseInteractiveProcess

P2PD_PATH = GO_BIN_PATH / "p2pd"


class P2PDProcess(BaseInteractiveProcess):
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
        self.proc = None
        self.cmd = str(P2PD_PATH)
        self.args = args
        self.patterns = (b"Control socket:", b"Peer ID:", b"Peer Addrs:")
        self.bytes_read = bytearray()
        self.event_ready = trio.Event()


class Daemon:
    p2pd_proc: BaseInteractiveProcess
    control: Client
    peer_info: PeerInfo

    def __init__(
        self, p2pd_proc: BaseInteractiveProcess, control: Client, peer_info: PeerInfo
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


@asynccontextmanager
async def make_p2pd(
    daemon_control_port: int,
    client_callback_port: int,
    is_secure: bool,
    is_pubsub_enabled: bool = True,
    is_gossipsub: bool = True,
    is_pubsub_signing: bool = False,
    is_pubsub_signing_strict: bool = False,
) -> AsyncIterator[Daemon]:
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

    async with p2pc.listen():
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
        yield Daemon(p2pd_proc, p2pc, peer_info)
