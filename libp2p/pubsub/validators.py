from libp2p.crypto.keys import PublicKey

from .pb import rpc_pb2


def signature_validator(pubkey: PublicKey, msg: rpc_pb2.Message) -> bool:
    """
    Verify the message against the given public key.

    :param pubkey: the public key which signs the message.
    :param msg: the message signed.
    """
    try:
        pubkey.verify(msg.SerializeToString(), msg.signature)
    except Exception:
        return False
    return True
