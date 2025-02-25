import logging
from typing import (
    Optional,
)

from multiaddr import (
    Multiaddr,
)

from libp2p.abc import (
    IHost,
    INetStream,
)
from libp2p.custom_types import (
    StreamHandlerFn,
    TProtocol,
)
from libp2p.network.stream.exceptions import (
    StreamClosed,
)
from libp2p.utils import (
    get_agent_version,
)

from .pb.identify_pb2 import (
    Identify,
)

# Not sure I can do this or I break a pattern
# logger = logging.getLogger("libp2p.identity.identify")
logger = logging.getLogger(__name__)

ID = TProtocol("/ipfs/id/1.0.0")
PROTOCOL_VERSION = "ipfs/0.1.0"
AGENT_VERSION = get_agent_version()


def _multiaddr_to_bytes(maddr: Multiaddr) -> bytes:
    return maddr.to_bytes()


def _mk_identify_protobuf(
    host: IHost, observed_multiaddr: Optional[Multiaddr]
) -> Identify:
    public_key = host.get_public_key()
    laddrs = host.get_addrs()
    protocols = host.get_mux().get_protocols()

    observed_addr = observed_multiaddr.to_bytes() if observed_multiaddr else b""
    return Identify(
        protocol_version=PROTOCOL_VERSION,
        agent_version=AGENT_VERSION,
        public_key=public_key.serialize(),
        listen_addrs=map(_multiaddr_to_bytes, laddrs),
        observed_addr=observed_addr,
        protocols=protocols,
    )


def identify_handler_for(host: IHost) -> StreamHandlerFn:
    async def handle_identify(stream: INetStream) -> None:
        # get observed address from ``stream``
        # class Swarm(Service, INetworkService):
        # TODO: Connection and `peer_id` are 1-1 mapping in our implementation,
        # whereas in Go one `peer_id` may point to multiple connections.
        # connections: dict[ID, INetConn]
        # Luca: So I'm assuming that the connection is 1-1 mapping for now
        peer_id = stream.muxed_conn.peer_id  # remote peer_id
        peer_store = host.get_peerstore()  # get the peer store from the host
        remote_peer_multiaddrs = peer_store.addrs(
            peer_id
        )  # get the Multiaddrs for the remote peer_id
        logger.debug("multiaddrs of remote peer is %s", remote_peer_multiaddrs)
        logger.debug("received a request for %s from %s", ID, peer_id)

        # Select the first address if available, else None
        observed_multiaddr = (
            remote_peer_multiaddrs[0] if remote_peer_multiaddrs else None
        )
        protobuf = _mk_identify_protobuf(host, observed_multiaddr)
        response = protobuf.SerializeToString()

        try:
            await stream.write(response)
        except StreamClosed:
            logger.debug("Fail to respond to %s request: stream closed", ID)
        else:
            await stream.close()
            logger.debug("successfully handled request for %s from %s", ID, peer_id)

    return handle_identify
