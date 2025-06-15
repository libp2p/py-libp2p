import logging

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


def _remote_address_to_multiaddr(
    remote_address: tuple[str, int] | None,
) -> Multiaddr | None:
    """Convert a (host, port) tuple to a Multiaddr."""
    if remote_address is None:
        return None

    host, port = remote_address

    # Check if the address is IPv6 (contains ':')
    if ":" in host:
        # IPv6 address
        return Multiaddr(f"/ip6/{host}/tcp/{port}")
    else:
        # IPv4 address
        return Multiaddr(f"/ip4/{host}/tcp/{port}")


def _mk_identify_protobuf(
    host: IHost, observed_multiaddr: Multiaddr | None
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
        peer_id = (
            stream.muxed_conn.peer_id
        )  # remote peer_id is in class Mplex (mplex.py )
        observed_multiaddr: Multiaddr | None = None
        # Get the remote address
        try:
            remote_address = stream.get_remote_address()
            # Convert to multiaddr
            if remote_address:
                observed_multiaddr = _remote_address_to_multiaddr(remote_address)

            logger.debug(
                "Connection from remote peer %s, address: %s, multiaddr: %s",
                peer_id,
                remote_address,
                observed_multiaddr,
            )
        except Exception as e:
            logger.error("Error getting remote address: %s", e)
            remote_address = None

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
