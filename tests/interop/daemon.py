from multiaddr import Multiaddr
from pexpect.spawnbase import SpawnBase

from p2pclient import Client

from libp2p.peer.peerinfo import info_from_p2p_addr, PeerInfo
from libp2p.peer.id import ID

from .constants import PEXPECT_NEW_LINE, LOCALHOST_IP
from .envs import GO_BIN_PATH

P2PD_PATH = GO_BIN_PATH / "p2pd"


class Daemon:
    proc: SpawnBase
    control: Client
    peer_info: PeerInfo

    def __init__(self, proc: SpawnBase, control: Client, peer_info: PeerInfo) -> None:
        self.proc = proc
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


async def make_p2pd(
    proc_factory,
    unused_tcp_port_factory,
    is_secure: bool,
    is_pubsub_enabled=True,
    is_gossipsub=True,
    is_pubsub_signing=False,
    is_pubsub_signing_strict=False,
) -> Daemon:
    control_maddr = Multiaddr(f"/ip4/{LOCALHOST_IP}/tcp/{unused_tcp_port_factory()}")
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
        #   - gossipsubHeartbeatInterval: GossipSubHeartbeatInitialDelay = 100 * time.Millisecond
        #   - gossipsubHeartbeatInitialDelay: GossipSubHeartbeatInterval = 1 * time.Second
        #   Referece: https://github.com/libp2p/go-libp2p-daemon/blob/b95e77dbfcd186ccf817f51e95f73f9fd5982600/p2pd/main.go#L348-L353  # noqa: E501
    proc = proc_factory(str(P2PD_PATH), args)
    await proc.expect(r"Peer ID:\s+(\w+)" + PEXPECT_NEW_LINE, async_=True)
    peer_id_base58 = proc.match.group(1)
    await proc.expect(r"Peer Addrs:", async_=True)
    await proc.expect(
        rf"(/ip4/{LOCALHOST_IP}/tcp/[\w]+)" + PEXPECT_NEW_LINE, async_=True
    )
    daemon_listener_maddr = Multiaddr(proc.match.group(1))
    daemon_pinfo = info_from_p2p_addr(
        daemon_listener_maddr.encapsulate(f"/p2p/{peer_id_base58}")
    )
    client_callback_maddr = Multiaddr(
        f"/ip4/{LOCALHOST_IP}/tcp/{unused_tcp_port_factory()}"
    )
    p2pc = Client(control_maddr, client_callback_maddr)
    return Daemon(proc, p2pc, daemon_pinfo)
