"""
Message construction helpers for rendezvous protocol.
"""

from multiaddr import Multiaddr

from libp2p.peer.id import ID as PeerID

from .pb.rendezvous_pb2 import Message


def create_register_message(
    namespace: str, peer_id: PeerID, addrs: list[Multiaddr], ttl: int
) -> Message:
    """Create a REGISTER message."""
    msg = Message()
    msg.type = Message.REGISTER

    # Create PeerInfo
    peer_info = msg.register.peer
    peer_info.id = peer_id.to_bytes()
    for addr in addrs:
        peer_info.addrs.append(addr.to_bytes())

    msg.register.ns = namespace
    msg.register.ttl = ttl

    return msg


def create_register_response_message(
    status: Message.ResponseStatus.ValueType, status_text: str = "", ttl: int = 0
) -> Message:
    """Create a REGISTER_RESPONSE message."""
    msg = Message()
    msg.type = Message.REGISTER_RESPONSE
    msg.registerResponse.status = status
    msg.registerResponse.statusText = status_text
    msg.registerResponse.ttl = ttl
    return msg


def create_unregister_message(namespace: str, peer_id: PeerID) -> Message:
    """Create an UNREGISTER message."""
    msg = Message()
    msg.type = Message.UNREGISTER
    msg.unregister.ns = namespace
    msg.unregister.id = peer_id.to_bytes()
    return msg


def create_discover_message(
    namespace: str, limit: int = 0, cookie: bytes = b""
) -> Message:
    """Create a DISCOVER message."""
    msg = Message()
    msg.type = Message.DISCOVER
    msg.discover.ns = namespace
    msg.discover.limit = limit
    msg.discover.cookie = cookie
    return msg


def create_discover_response_message(
    registrations: list[Message.Register],
    cookie: bytes = b"",
    status: Message.ResponseStatus.ValueType = Message.ResponseStatus.OK,
    status_text: str = "",
) -> Message:
    """Create a DISCOVER_RESPONSE message."""
    msg = Message()
    msg.type = Message.DISCOVER_RESPONSE
    msg.discoverResponse.registrations.extend(registrations)
    msg.discoverResponse.cookie = cookie
    msg.discoverResponse.status = status
    msg.discoverResponse.statusText = status_text
    return msg


def parse_peer_info(peer_info: Message.PeerInfo) -> tuple[PeerID, list[Multiaddr]]:
    """Parse PeerInfo from protobuf message."""
    peer_id = PeerID(peer_info.id)
    addrs = [Multiaddr(addr_bytes) for addr_bytes in peer_info.addrs]
    return peer_id, addrs
