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
from libp2p.peer.peerstore import env_to_send_in_RPC
from libp2p.utils import (
    decode_varint_with_size,
    get_agent_version,
    varint,
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
    protocols = tuple(str(p) for p in host.get_mux().get_protocols() if p is not None)

    # Create a signed peer-record for the remote peer
    envelope_bytes, _ = env_to_send_in_RPC(host)

    observed_addr = observed_multiaddr.to_bytes() if observed_multiaddr else b""
    return Identify(
        protocol_version=PROTOCOL_VERSION,
        agent_version=AGENT_VERSION,
        public_key=public_key.serialize(),
        listen_addrs=map(_multiaddr_to_bytes, laddrs),
        observed_addr=observed_addr,
        protocols=protocols,
        signedPeerRecord=envelope_bytes,
    )


def parse_identify_response(response: bytes) -> Identify:
    """
    Parse identify response that could be either:
    - Old format: raw protobuf
    - New format: length-prefixed protobuf

    This function provides backward and forward compatibility.
    """
    # Try new format first: length-prefixed protobuf
    if len(response) >= 1:
        length, varint_size = decode_varint_with_size(response)
        if varint_size > 0 and length > 0 and varint_size + length <= len(response):
            protobuf_data = response[varint_size : varint_size + length]
            try:
                identify_response = Identify()
                identify_response.ParseFromString(protobuf_data)
                # Sanity check: must have agent_version (protocol_version is optional)
                if identify_response.agent_version:
                    return identify_response
            except Exception:
                pass  # Fall through to old format

    # Fall back to old format: raw protobuf
    try:
        identify_response = Identify()
        identify_response.ParseFromString(response)
        return identify_response
    except Exception as e:
        logger.error(f"Failed to parse identify response: {e}")
        logger.error(f"Response length: {len(response)}")
        logger.error(f"Response hex: {response.hex()}")
        raise


def identify_handler_for(
    host: IHost, use_varint_format: bool = True
) -> StreamHandlerFn:
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

        except Exception as e:
            logger.error("Error getting remote address: %s", e)
            remote_address = None

        protobuf = _mk_identify_protobuf(host, observed_multiaddr)
        response = protobuf.SerializeToString()

        try:
            if use_varint_format:
                # Send length-prefixed protobuf message (new format)
                # Combine length prefix and response into a single write to avoid races
                length_prefix = varint.encode_uvarint(len(response))
                full_response = length_prefix + response
                await stream.write(full_response)
            else:
                # Send raw protobuf message (old format for backward compatibility)
                await stream.write(response)
        except StreamClosed:
            logger.debug("Fail to respond to %s request: stream closed", ID)
            return  # Exit early if stream is closed
        except Exception as e:
            logger.error("Error sending identify response to %s: %s", peer_id, e)
            return  # Exit early on any error
        else:
            # Only close the stream after all writes are successful
            try:
                await stream.close()
                logger.debug("successfully handled request for %s from %s", ID, peer_id)
            except Exception as e:
                logger.debug("Error closing stream: %s", e)

    return handle_identify
