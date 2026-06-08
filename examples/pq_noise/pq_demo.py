"""
Live two-node demo: Noise XXhfs (X-Wing KEM) over TCP.

Starts a listener and a dialer in the same process using a trio nursery,
connects them over loopback TCP, performs the PQ Noise handshake, and
exchanges a round-trip message.

Run with:
    python examples/pq_noise/pq_demo.py
"""

import logging
import time

import multiaddr
import trio

# liboqs auto-installer uses print() internally so cannot be suppressed via logging,
# but it falls back to kyber-py automatically once the install countdown finishes.

from libp2p import new_host
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.keys import KeyPair
from libp2p.crypto.x25519 import X25519PrivateKey
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.security.noise.pq.transport_pq import PROTOCOL_ID as PQ_PROTOCOL_ID
from libp2p.security.noise.pq.transport_pq import TransportPQ
from libp2p.utils.address_validation import find_free_port

logging.basicConfig(level=logging.WARNING)

STREAM_PROTO = TProtocol("/pq-demo/1.0.0")
MSG = b"post-quantum hello!"


def _make_pq_host(listen_port: int | None = None):
    kp_raw = create_new_key_pair()
    kp = KeyPair(kp_raw.private_key, kp_raw.public_key)
    noise_key = X25519PrivateKey.new()
    transport = TransportPQ(libp2p_keypair=kp, noise_privkey=noise_key)
    sec_opt = {PQ_PROTOCOL_ID: transport}

    listen_addrs = None
    if listen_port is not None:
        listen_addrs = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{listen_port}")]

    return new_host(key_pair=kp, sec_opt=sec_opt, listen_addrs=listen_addrs)


async def run() -> None:
    port = find_free_port()

    listener = _make_pq_host(listen_port=port)
    dialer = _make_pq_host()

    received: list[bytes] = []
    handshake_done = trio.Event()

    async def handle_stream(stream: INetStream) -> None:
        data = await stream.read(len(MSG))
        received.append(data)
        await stream.write(b"pq-ack:" + data)
        await stream.close()
        handshake_done.set()

    t_start = time.perf_counter()

    async with listener.run(listen_addrs=[multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{port}")]):
        listener.set_stream_handler(STREAM_PROTO, handle_stream)
        listener_id = listener.get_id().to_string()
        listener_addr = f"/ip4/127.0.0.1/tcp/{port}/p2p/{listener_id}"

        print(f"[listener] PeerID : {listener_id}")
        print(f"[listener] Address: {listener_addr}")

        async with dialer.run(listen_addrs=[]):
            dialer_id = dialer.get_id().to_string()
            print(f"[dialer]   PeerID : {dialer_id}")

            info = info_from_p2p_addr(multiaddr.Multiaddr(listener_addr))
            # Note: liboqs-python auto-installer runs once per process on systems
            # without a pre-built liboqs binary. After the ~7s countdown it falls
            # back to the pure-Python kyber-py backend. The handshake itself is
            # correct either way.
            print("[dialer]   Connecting (XXhfs handshake starting)...")
            t_connect = time.perf_counter()
            await dialer.connect(info)
            t_connected = time.perf_counter()
            print(f"[dialer]   Connected in {(t_connected - t_connect)*1000:.1f} ms")

            stream = await dialer.new_stream(info.peer_id, [STREAM_PROTO])
            await stream.write(MSG)
            reply = await stream.read(len(b"pq-ack:") + len(MSG))
            await stream.close()
            t_done = time.perf_counter()

            await handshake_done.wait()

    total_ms = (t_done - t_start) * 1000
    connect_ms = (t_connected - t_connect) * 1000

    print()
    print("=" * 55)
    print("  PQ Noise XXhfs (X-Wing KEM) -- live node integration")
    print("=" * 55)
    print(f"  Handshake + connect : {connect_ms:6.1f} ms")
    print(f"  Total (start->ack)  : {total_ms:6.1f} ms")
    print(f"  Message sent        : {MSG!r}")
    print(f"  Reply received      : {reply!r}")
    print()

    assert received == [MSG], f"Listener got {received!r}, expected {[MSG]!r}"
    assert reply == b"pq-ack:" + MSG, f"Unexpected reply: {reply!r}"
    print("  PASS -- PQ-secured round-trip succeeded")
    print("=" * 55)


if __name__ == "__main__":
    trio.run(run)
