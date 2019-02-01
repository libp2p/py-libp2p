from random import randint

from libp2p.stream_muxer.mplex.utils import encode_uvarint, decode_uvarint

def test_uvarint():
    n = randint(100000000000000, 100000000000000000000000000)
    uvarint = encode_uvarint(n)
    n_through_uvarint = int(decode_uvarint(uvarint, 0)[0])
    assert n_through_uvarint == n
