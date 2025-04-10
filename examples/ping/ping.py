import argparse
import logging
from typing import (
    cast,
)

import multiaddr
import trio

from libp2p.crypto.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
    KeyPair,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.host.basic_host import (
    BasicHost,
)
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.network.swarm import (
    Swarm,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)
from libp2p.peer.peerstore import (
    PeerStore,
)
from libp2p.security.noise.transport import (
    PROTOCOL_ID,
    Transport,
)
from libp2p.stream_muxer.yamux.yamux import (
    Yamux,
)
from libp2p.transport.tcp.tcp import (
    TCP,
)
from libp2p.transport.upgrader import (
    TransportUpgrader,
)

logging.basicConfig(level=logging.DEBUG)

PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")
PING_LENGTH = 32
RESP_TIMEOUT = 60


async def handle_ping(stream: INetStream) -> None:
    while True:
        try:
            payload = await stream.read(PING_LENGTH)
            peer_id = stream.muxed_conn.peer_id
            if payload is not None:
                print(f"received ping from {peer_id}")
                await stream.write(payload)
                print(f"responded with pong to {peer_id}")
        except Exception:
            await stream.reset()
            break


async def send_ping(stream: INetStream) -> None:
    try:
        payload = b"\x01" * PING_LENGTH
        print(f"sending ping to {stream.muxed_conn.peer_id}")
        await stream.write(payload)
        with trio.fail_after(RESP_TIMEOUT):
            response = await stream.read(PING_LENGTH)
        if response == payload:
            print(f"received pong from {stream.muxed_conn.peer_id}")
    except Exception as e:
        print(f"error occurred : {e}")


async def run(port: int, destination: str) -> None:
    localhost_ip = "127.0.0.1"
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    rust_privkey_bytes = bytes.fromhex(
        "6866d018650288fef506b818f04e6aafeadd96d70752fb16ac4b7f0a5f88f18d"
    )
    rust_pubkey_bytes = bytes.fromhex(
        "0d3fb3dc6cc19c6e58d6f61829fd56af9bbd28aa28d76ccb519f56a79bdace2a"
    )
    private_key = Ed25519PrivateKey.from_bytes(rust_privkey_bytes)
    public_key = Ed25519PublicKey.from_bytes(rust_pubkey_bytes)
    key_pair = KeyPair(private_key, public_key)
    peer_id = ID.from_pubkey(key_pair.public_key)
    logging.debug(f"Local Peer ID: {peer_id.pretty()}")
    logging.debug(f"Public Key from Private: {key_pair.public_key.to_bytes().hex()}")

    noise_transport = Transport(key_pair, noise_privkey=key_pair.private_key)
    tcp_transport = TCP()
    peerstore = PeerStore()
    upgrader = TransportUpgrader(
        secure_transports_by_protocol={PROTOCOL_ID: noise_transport},
        muxer_transports_by_protocol={cast(TProtocol, "/yamux/1.0.0"): Yamux},
    )
    swarm = Swarm(
        peer_id=peer_id, peerstore=peerstore, upgrader=upgrader, transport=tcp_transport
    )
    host = BasicHost(network=swarm)

    async with host.run(listen_addrs=[listen_addr]), trio.open_nursery() as nursery:
        if not destination:
            host.set_stream_handler(PING_PROTOCOL_ID, handle_ping)
            cmd = (
                f"Run this from the same folder in another console:\n\n"
                f"ping-demo -p {int(port) + 1} "
                f"-d /ip4/{localhost_ip}/tcp/{port}/p2p/{host.get_id().pretty()}\n"
            )
            print(cmd)
            print("Waiting for incoming connection...")
        else:
            maddr = multiaddr.Multiaddr(destination)
            info = info_from_p2p_addr(maddr)
            await host.connect(info)
            stream = await host.new_stream(info.peer_id, [PING_PROTOCOL_ID])
            nursery.start_soon(send_ping, stream)
            return
        await trio.sleep_forever()


def main() -> None:
    description = """
    This program demonstrates a simple p2p ping application using libp2p.
    To use it, first run 'python ping.py -p <PORT>', where <PORT> is the port number.
    Then, run another instance with 'python ping.py -p <ANOTHER_PORT> -d <DESTINATION>',
    where <DESTINATION> is the multiaddress of the previous listener host.
    """
    example_maddr = (
        "/ip4/127.0.0.1/tcp/8000/p2p/QmQn4SwGkDZKkUEpBRBvTmheQycxAHJUNmVEnjA2v1qe8Q"
    )
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "-p", "--port", default=8000, type=int, help="source port number"
    )
    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help=f"destination multiaddr string, e.g. {example_maddr}",
    )
    args = parser.parse_args()
    if not args.port:
        raise RuntimeError("failed to determine local port")
    try:
        trio.run(run, *(args.port, args.destination))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
