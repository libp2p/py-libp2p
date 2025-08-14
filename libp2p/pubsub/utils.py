import logging

from libp2p.abc import IHost
from libp2p.peer.envelope import consume_envelope
from libp2p.peer.peerstore import create_signed_peer_record
from libp2p.pubsub.pb.rpc_pb2 import RPC

logger = logging.getLogger("pubsub-example.utils")


def maybe_consume_signed_record(msg: RPC, host: IHost) -> bool:
    if msg.HasField("senderRecord"):
        try:
            # Convert the signed-peer-record(Envelope) from
            # protobuf bytes
            envelope, _ = consume_envelope(msg.senderRecord, "libp2p-peer-record")
            # Use the default TTL of 2 hours (7200 seconds)
            if not host.get_peerstore().consume_peer_record(envelope, 7200):
                logger.error("Updating the certified-addr-book was unsuccessful")
        except Exception as e:
            logger.error("Error updating the certified addr book for peer: %s", e)
            return False
    return True


def env_to_send_in_RPC(host: IHost) -> tuple[bytes, bool]:
    listen_addrs_set = {addr for addr in host.get_addrs()}
    local_env = host.get_peerstore().get_local_record()

    if local_env is None:
        # No cached SPR yet -> create one
        return issue_and_cache_local_record(host), True
    else:
        record_addrs_set = local_env._env_addrs_set()
        if record_addrs_set == listen_addrs_set:
            # Perfect match -> reuse the cached envelope
            return local_env.marshal_envelope(), False
        else:
            # Addresses changed -> issue a new SPR and cache it
            return issue_and_cache_local_record(host), True


def issue_and_cache_local_record(host: IHost) -> bytes:
    env = create_signed_peer_record(
        host.get_id(),
        host.get_addrs(),
        host.get_private_key(),
    )
    # Cache it for next time
    host.get_peerstore().set_local_record(env)
    return env.marshal_envelope()
