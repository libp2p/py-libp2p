import base64

import Crypto.PublicKey.RSA as RSA

from libp2p.crypto.pb import crypto_pb2 as pb
from libp2p.crypto.rsa import (
    RSAPrivateKey,
)
from libp2p.peer.id import (
    ID,
)

# ``PRIVATE_KEY_PROTOBUF_SERIALIZATION`` is a protobuf holding an RSA private key.
PRIVATE_KEY_PROTOBUF_SERIALIZATION = """
CAAS4AQwggJcAgEAAoGBAL7w+Wc4VhZhCdM/+Hccg5Nrf4q9NXWwJylbSrXz/unFS24wyk6pEk0zi3W
7li+vSNVO+NtJQw9qGNAMtQKjVTP+3Vt/jfQRnQM3s6awojtjueEWuLYVt62z7mofOhCtj+VwIdZNBo
/EkLZ0ETfcvN5LVtLYa8JkXybnOPsLvK+PAgMBAAECgYBdk09HDM7zzL657uHfzfOVrdslrTCj6p5mo
DzvCxLkkjIzYGnlPuqfNyGjozkpSWgSUc+X+EGLLl3WqEOVdWJtbM61fewEHlRTM5JzScvwrJ39t7o6
CCAjKA0cBWBd6UWgbN/t53RoWvh9HrA2AW5YrT0ZiAgKe9y7EMUaENVJ8QJBAPhpdmb4ZL4Fkm4OKia
NEcjzn6mGTlZtef7K/0oRC9+2JkQnCuf6HBpaRhJoCJYg7DW8ZY+AV6xClKrgjBOfERMCQQDExhnzu2
dsQ9k8QChBlpHO0TRbZBiQfC70oU31kM1AeLseZRmrxv9Yxzdl8D693NNWS2JbKOXl0kMHHcuGQLMVA
kBZ7WvkmPV3aPL6jnwp2pXepntdVnaTiSxJ1dkXShZ/VSSDNZMYKY306EtHrIu3NZHtXhdyHKcggDXr
qkBrdgErAkAlpGPojUwemOggr4FD8sLX1ot2hDJyyV7OK2FXfajWEYJyMRL1Gm9Uk1+Un53RAkJneqp
JGAzKpyttXBTIDO51AkEA98KTiROMnnU8Y6Mgcvr68/SMIsvCYMt9/mtwSBGgl80VaTQ5Hpaktl6Xbh
VUt5Wv0tRxlXZiViCGCD1EtrrwTw==
""".replace("\n", "")

EXPECTED_PEER_ID = "QmRK3JgmVEGiewxWbhpXLJyjWuGuLeSTMTndA1coMHEy5o"


# NOTE: this test checks that we can recreate the expected peer id given a private key
# serialization, taken from the Go implementation of libp2p.
def test_peer_id_interop():
    private_key_protobuf_bytes = base64.b64decode(PRIVATE_KEY_PROTOBUF_SERIALIZATION)
    private_key_protobuf = pb.PrivateKey()
    private_key_protobuf.ParseFromString(private_key_protobuf_bytes)

    private_key_data = private_key_protobuf.data

    private_key_impl = RSA.import_key(private_key_data)
    private_key = RSAPrivateKey(private_key_impl)
    public_key = private_key.get_public_key()

    peer_id = ID.from_pubkey(public_key)
    assert peer_id == EXPECTED_PEER_ID
