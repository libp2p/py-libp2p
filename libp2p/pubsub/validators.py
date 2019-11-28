from libp2p.crypto.keys import PublicKey


def signature_validator(pubkey: PublicKey, payload: bytes, signature: bytes) -> bool:
    """
    Verify the message against the given public key.

    :param pubkey: the public key which signs the message.
    :param msg: the message signed.
    """
    try:
        return pubkey.verify(payload, signature)
    except Exception:
        return False
