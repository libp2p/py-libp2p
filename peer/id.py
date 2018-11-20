import base58
import multihash

# MaxInlineKeyLength is the maximum length a key can be for it to be inlined in
# the peer ID.
# * When `len(pubKey.Bytes()) <= MaxInlineKeyLength`, the peer ID is the
#   identity multihash hash of the public key.
# * When `len(pubKey.Bytes()) > MaxInlineKeyLength`, the peer ID is the
#   sha2-256 multihash of the public key.
MAX_INLINE_KEY_LENGTH = 42


class ID:

    def __init__(self, id_str):
        self._id_str = id_str

    def pretty(self):
        return base58.b58encode(self._id_str).decode()

    def __str__(self):
        pid = self.pretty()
        if len(pid) <= 10:
            return "<peer.ID %s>" % pid
        return "<peer.ID %s*%s>" % (pid[:2], pid[len(pid)-6:])

    __repr__ = __str__


def id_b58_encode(id):
    """
    return a b58-encoded string
    """
    return base58.b58encode(id._id_str).decode()


def id_b58_decode(s):
    """
    return a base58-decoded peer ID
    """
    id_str = base58.b58decode(s)
    return ID(id_str)


def id_from_public_key(key):
    # export into binary format
    b = key.exportKey("DER")

    algo = multihash.Func.sha2_256
    # TODO: seems identity is not yet supported in pymultihash
    # if len(b) <= MAX_INLINE_KEY_LENGTH:
    #     algo multihash.func.identity

    mh = multihash.digest(b, algo)
    return ID(mh.encode('base64'))


def id_from_private_key(key):
    return id_from_public_key(key.publickey())
