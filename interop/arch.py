from dataclasses import (
    dataclass,
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
import libp2p.security.secio.transport as secio
from libp2p.stream_muxer.mplex.mplex import (
    MPLEX_PROTOCOL_ID,
    Mplex,
)


def generate_new_rsa_identity() -> KeyPair:
    return create_new_key_pair()


async def build_host(transport: str, ip: str, port: str, sec_protocol: str, muxer: str):
    match (sec_protocol, muxer):
        case ("insecure", "mplex"):
            key_pair = create_new_key_pair()
            host = new_host(
                key_pair,
                {MPLEX_PROTOCOL_ID: Mplex},
                {
                    TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair),
                    TProtocol(secio.ID): secio.Transport(key_pair),
                },
            )
            muladdr = multiaddr.Multiaddr(f"/ip4/{ip}/tcp/{port}")
            return (host, muladdr)
        case _:
            raise ValueError("Protocols not supported")


@dataclass
class RedisClient:
    client: redis.Redis

    def blpop(self, key: str, timeout: float) -> list[str]:
        result = self.client.blpop([key], timeout)
        return [result[1]] if result else []

    def rpush(self, key: str, value: str) -> None:
        self.client.rpush(key, value)


async def main():
    client = RedisClient(redis.Redis(host="localhost", port=6379, db=0))
    client.rpush("test", "hello")
    print(client.blpop("test", timeout=5))


if __name__ == "__main__":
    trio.run(main)
