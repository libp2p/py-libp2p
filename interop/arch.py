from dataclasses import (
    dataclass,
)
import logging

from cryptography.hazmat.primitives.asymmetric import (
    x25519,
)
import multiaddr
import redis
import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.keys import (
    KeyPair,
)
from libp2p.crypto.rsa import (
    create_new_key_pair,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.security.insecure.transport import (
    PLAINTEXT_PROTOCOL_ID,
    InsecureTransport,
)
from libp2p.security.noise.transport import (
    Transport as NoiseTransport,
)
import libp2p.security.secio.transport as secio
from libp2p.stream_muxer.mplex.mplex import (
    MPLEX_PROTOCOL_ID,
    Mplex,
)
from libp2p.stream_muxer.yamux.yamux import (
    PROTOCOL_ID as YAMUX_PROTOCOL_ID,
    Yamux,
)

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("ping_debug.log", mode="w", encoding="utf-8"),
    ],
)


def generate_new_rsa_identity() -> KeyPair:
    return create_new_key_pair()


def create_noise_keypair():
    """Create a Noise protocol keypair for secure communication"""
    try:
        x25519_private_key = x25519.X25519PrivateKey.generate()

        class NoisePrivateKey:
            def __init__(self, key):
                self._key = key

            def to_bytes(self):
                return self._key.private_bytes_raw()

            def public_key(self):
                return NoisePublicKey(self._key.public_key())

            def get_public_key(self):
                return NoisePublicKey(self._key.public_key())

        class NoisePublicKey:
            def __init__(self, key):
                self._key = key

            def to_bytes(self):
                return self._key.public_bytes_raw()

        return NoisePrivateKey(x25519_private_key)
    except Exception as e:
        logging.error(f"Failed to create Noise keypair: {e}")
        return None


async def build_host(transport: str, ip: str, port: str, sec_protocol: str, muxer: str):
    match (sec_protocol, muxer):
        case ("insecure", "mplex"):
            key_pair = create_new_key_pair()
            host = new_host(
                key_pair,
                {TProtocol(MPLEX_PROTOCOL_ID): Mplex},
                {
                    TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair),
                    TProtocol(secio.ID): secio.Transport(key_pair),
                },
            )
            muladdr = multiaddr.Multiaddr(f"/ip4/{ip}/tcp/{port}")
            return (host, muladdr)
        case ("insecure", "yamux"):
            key_pair = create_new_key_pair()
            host = new_host(
                key_pair,
                {TProtocol(YAMUX_PROTOCOL_ID): Yamux},
                {
                    TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair),
                    TProtocol(secio.ID): secio.Transport(key_pair),
                },
            )
            muladdr = multiaddr.Multiaddr(f"/ip4/{ip}/tcp/{port}")
            return (host, muladdr)
        case ("noise", "yamux"):
            key_pair = generate_new_rsa_identity()
            logging.debug("Generated RSA keypair")

            noise_privkey = create_noise_keypair()
            if not noise_privkey:
                print("[ERROR] Failed to create Noise keypair")
                return 1
            logging.debug("Generated Noise keypair")

            noise_transport = NoiseTransport(key_pair, noise_privkey)
            logging.debug(f"Noise transport initialized: {noise_transport}")
            sec_opt = {TProtocol("/noise"): noise_transport}
            muxer_opt = {TProtocol(YAMUX_PROTOCOL_ID): Yamux}

            logging.info(f"Using muxer: {muxer_opt}")

            host = new_host(key_pair=key_pair, sec_opt=sec_opt, muxer_opt=muxer_opt)
            muladdr = multiaddr.Multiaddr(f"/ip4/{ip}/tcp/{port}")
            return (host, muladdr)
        case _:
            raise ValueError("Protocols not supported")


@dataclass
class RedisClient:
    client: redis.Redis

    def brpop(self, key: str, timeout: float) -> list[str]:
        result = self.client.brpop([key], timeout)
        return [result[1]] if result else []

    def rpush(self, key: str, value: str) -> None:
        self.client.rpush(key, value)


async def main():
    client = RedisClient(redis.Redis(host="localhost", port=6379, db=0))
    client.rpush("test", "hello")
    print(client.blpop("test", timeout=5))


if __name__ == "__main__":
    trio.run(main)
