import argparse
import logging

from cryptography.hazmat.primitives.asymmetric import (
    x25519,
)
import multiaddr
import trio

from libp2p import (
    generate_new_rsa_identity,
    new_host,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)
from libp2p.security.noise.transport import Transport as NoiseTransport
from libp2p.stream_muxer.yamux.yamux import (
    Yamux,
)
from libp2p.stream_muxer.yamux.yamux import PROTOCOL_ID as YAMUX_PROTOCOL_ID

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("ping_debug.log", mode="w", encoding="utf-8"),
    ],
)

# Standard libp2p ping protocol - this is what rust-libp2p uses by default
PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")
PING_LENGTH = 32
RESP_TIMEOUT = 60


async def handle_ping(stream: INetStream) -> None:
    """Handle incoming ping requests from rust-libp2p clients"""
    peer_id = stream.muxed_conn.peer_id
    print(f"[INFO] New ping stream opened by {peer_id}")
    logging.info(f"Ping handler called for peer {peer_id}")

    ping_count = 0

    try:
        while True:
            try:
                print(f"[INFO] Waiting for ping data from {peer_id}...")
                logging.debug(f"Stream state: {stream}")
                data = await stream.read(PING_LENGTH)

                if not data:
                    print(
                        f"[INFO] No data received,"
                        f" connection likely closed by {peer_id}"
                    )
                    logging.debug("No data received, stream closed")
                    break

                if len(data) == 0:
                    print(f"[INFO] Empty data received, connection closed by {peer_id}")
                    logging.debug("Empty data received")
                    break

                ping_count += 1
                print(
                    f"[PING {ping_count}] Received ping from {peer_id}:"
                    f" {len(data)} bytes"
                )
                logging.debug(f"Ping data: {data.hex()}")

                # Echo the data back (this is what ping protocol does)
                await stream.write(data)
                print(f"[PING {ping_count}] Echoed ping back to {peer_id}")

            except Exception as e:
                print(f"[ERROR] Error in ping loop with {peer_id}: {e}")
                logging.exception("Ping loop error")
                break

    except Exception as e:
        print(f"[ERROR] Error handling ping from {peer_id}: {e}")
        logging.exception("Ping handler error")
    finally:
        try:
            print(f"[INFO] Closing ping stream with {peer_id}")
            await stream.close()
        except Exception as e:
            logging.debug(f"Error closing stream: {e}")

    print(f"[INFO] Ping session completed with {peer_id} ({ping_count} pings)")


async def send_ping_sequence(stream: INetStream, count: int = 5) -> None:
    """Send a sequence of pings compatible with rust-libp2p."""
    peer_id = stream.muxed_conn.peer_id
    print(f"[INFO] Starting ping sequence to {peer_id} ({count} pings)")

    import os
    import time

    rtts = []

    for i in range(1, count + 1):
        try:
            # Generate random 32-byte payload as per ping protocol spec
            payload = os.urandom(PING_LENGTH)
            print(f"[PING {i}/{count}] Sending ping to {peer_id}")
            logging.debug(f"Sending payload: {payload.hex()}")
            start_time = time.time()

            await stream.write(payload)

            with trio.fail_after(RESP_TIMEOUT):
                response = await stream.read(PING_LENGTH)

            end_time = time.time()
            rtt = (end_time - start_time) * 1000

            if (
                response
                and len(response) >= PING_LENGTH
                and response[:PING_LENGTH] == payload
            ):
                rtts.append(rtt)
                print(f"[PING {i}] Successful! RTT: {rtt:.2f}ms")
            else:
                print(f"[ERROR] Ping {i} failed: response mismatch or incomplete")
                if response:
                    logging.debug(f"Expected: {payload.hex()}")
                    logging.debug(f"Received: {response.hex()}")

            if i < count:
                await trio.sleep(1)

        except trio.TooSlowError:
            print(f"[ERROR] Ping {i} timed out after {RESP_TIMEOUT}s")
        except Exception as e:
            print(f"[ERROR] Ping {i} failed: {e}")
            logging.exception(f"Ping {i} error")

    # Print statistics
    if rtts:
        avg_rtt = sum(rtts) / len(rtts)
        min_rtt = min(rtts)
        max_rtt = max(rtts)  # Fixed typo: was max_rtts
        success_count = len(rtts)
        loss_rate = ((count - success_count) / count) * 100

        print("\n[STATS] Ping Statistics:")
        print(
            f"   Packets: Sent={count}, Received={success_count},"
            f" Lost={count - success_count}"
        )
        print(f"   Loss rate: {loss_rate:.1f}%")
        print(
            f"   RTT: min={min_rtt:.2f}ms, avg={avg_rtt:.2f}ms," f" max={max_rtt:.2f}ms"
        )
    else:
        print(f"\n[STATS] All pings failed ({count} attempts)")


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


async def run_server(port: int) -> None:
    """Run ping server that accepts connections from rust-libp2p clients."""
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    key_pair = generate_new_rsa_identity()
    logging.debug("Generated RSA keypair")

    noise_privkey = create_noise_keypair()
    if not noise_privkey:
        print("[ERROR] Failed to create Noise keypair")
        return
    logging.debug("Generated Noise keypair")

    noise_transport = NoiseTransport(key_pair, noise_privkey=noise_privkey)
    logging.debug(f"Noise transport initialized: {noise_transport}")
    sec_opt = {TProtocol("/noise"): noise_transport}
    muxer_opt = {TProtocol(YAMUX_PROTOCOL_ID): Yamux}

    logging.info(f"Using muxer: {muxer_opt}")

    host = new_host(key_pair=key_pair, sec_opt=sec_opt, muxer_opt=muxer_opt)

    print("[INFO] Starting py-libp2p ping server...")

    async with host.run(listen_addrs=[listen_addr]):
        print(f"[INFO] Registering ping handler for protocol: {PING_PROTOCOL_ID}")
        host.set_stream_handler(PING_PROTOCOL_ID, handle_ping)

        # Also register alternative protocol IDs for better compatibility
        alt_protocols = [
            TProtocol("/ping/1.0.0"),
            TProtocol("/libp2p/ping/1.0.0"),
        ]

        for alt_proto in alt_protocols:
            print(f"[INFO] Also registering handler for: {alt_proto}")
            host.set_stream_handler(alt_proto, handle_ping)

        print("[INFO] Server started successfully!")
        print(f"[INFO] Peer ID: {host.get_id()}")
        print(f"[INFO] Listening: /ip4/0.0.0.0/tcp/{port}")
        print(f"[INFO] Primary Protocol: {PING_PROTOCOL_ID}")
        print("[INFO] Security: Noise encryption")
        print("[INFO] Muxer: Yamux stream multiplexing")

        print("\n[INFO] Registered protocols:")
        print(f"   - {PING_PROTOCOL_ID}")
        for proto in alt_protocols:
            print(f"   - {proto}")

        peer_id = host.get_id()
        print("\n[TEST] Test with rust-libp2p:")
        print(f"   cargo run -- /ip4/127.0.0.1/tcp/{port}/p2p/{peer_id}")

        print("\n[TEST] Test with py-libp2p:")
        print(f"   python ping.py client /ip4/127.0.0.1/tcp/{port}/p2p/{peer_id}")

        print("\n[INFO] Waiting for connections...")
        print("Press Ctrl+C to exit")

        await trio.sleep_forever()


async def run_client(destination: str, count: int = 5) -> None:
    """Run ping client to test connectivity with another peer."""
    listen_addr = multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/0")

    key_pair = generate_new_rsa_identity()
    logging.debug("Generated RSA keypair")

    noise_privkey = create_noise_keypair()
    if not noise_privkey:
        print("[ERROR] Failed to create Noise keypair")
        return 1
    logging.debug("Generated Noise keypair")

    noise_transport = NoiseTransport(key_pair, noise_privkey=noise_privkey)
    logging.debug(f"Noise transport initialized: {noise_transport}")
    sec_opt = {TProtocol("/noise"): noise_transport}
    muxer_opt = {TProtocol(YAMUX_PROTOCOL_ID): Yamux}

    logging.info(f"Using muxer: {muxer_opt}")

    host = new_host(key_pair=key_pair, sec_opt=sec_opt, muxer_opt=muxer_opt)

    print("[INFO] Starting py-libp2p ping client...")

    async with host.run(listen_addrs=[listen_addr]):
        print(f"[INFO] Our Peer ID: {host.get_id()}")
        print(f"[INFO] Target: {destination}")
        print("[INFO] Security: Noise encryption")
        print("[INFO] Muxer: Yamux stream multiplexing")

        try:
            maddr = multiaddr.Multiaddr(destination)
            info = info_from_p2p_addr(maddr)
            target_peer_id = info.peer_id

            print(f"[INFO] Target Peer ID: {target_peer_id}")
            print("[INFO] Connecting to peer...")

            await host.connect(info)
            print("[INFO] Connection established!")

            # Try protocols in order of preference
            # Start with the standard libp2p ping protocol
            protocols_to_try = [
                PING_PROTOCOL_ID,  # /ipfs/ping/1.0.0 - standard protocol
                TProtocol("/ping/1.0.0"),  # Alternative
                TProtocol("/libp2p/ping/1.0.0"),  # Another alternative
            ]

            stream = None

            for proto in protocols_to_try:
                try:
                    print(f"[INFO] Trying to open stream with protocol: {proto}")
                    stream = await host.new_stream(target_peer_id, [proto])
                    print(f"[INFO] Stream opened with protocol: {proto}")
                    break
                except Exception as e:
                    print(f"[ERROR] Failed to open stream with {proto}: {e}")
                    logging.debug(f"Protocol {proto} failed: {e}")
                    continue

            if not stream:
                print("[ERROR] Failed to open stream with any ping protocol")
                print("[ERROR] Ensure the target peer supports one of these protocols:")
                for proto in protocols_to_try:
                    print(f"[ERROR]   - {proto}")
                return 1

            await send_ping_sequence(stream, count)

            await stream.close()
            print("[INFO] Stream closed successfully")

        except Exception as e:
            print(f"[ERROR] Client error: {e}")
            logging.exception("Client error")
            import traceback

            traceback.print_exc()
            return 1

    print("\n[INFO] Client stopped")
    return 0


def main() -> None:
    """Main function with argument parsing."""
    description = """
    py-libp2p ping tool for interoperability testing with rust-libp2p.
    Uses Noise encryption and Yamux multiplexing for compatibility.

    Server mode: Listens for ping requests from rust-libp2p or py-libp2p clients.
    Client mode: Sends ping requests to rust-libp2p or py-libp2p servers.

    The tool implements the standard libp2p ping protocol (/ipfs/ping/1.0.0)
    which exchanges 32-byte random payloads and measures round-trip time.
    """

    example_maddr = (
        "/ip4/127.0.0.1/tcp/8000/p2p/QmQn4SwGkDZKkUEpBRBvTmheQycxAHJUNmVEnjA2v1qe8Q"
    )

    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  python ping.py server                    # Start server on port 8000
  python ping.py server --port 9000        # Start server on port 9000
  python ping.py client {example_maddr}
  python ping.py client {example_maddr} --count 10

Protocols supported:
  - /ipfs/ping/1.0.0 (primary, rust-libp2p default)
  - /ping/1.0.0 (alternative)
  - /libp2p/ping/1.0.0 (alternative)
        """,
    )

    subparsers = parser.add_subparsers(dest="mode", help="Operation mode")

    server_parser = subparsers.add_parser("server", help="Run as ping server")
    server_parser.add_argument(
        "--port", "-p", type=int, default=8000, help="Port to listen on (default: 8000)"
    )

    client_parser = subparsers.add_parser("client", help="Run as ping client")
    client_parser.add_argument("destination", help="Target peer multiaddr")
    client_parser.add_argument(
        "--count",
        "-c",
        type=int,
        default=5,
        help="Number of pings to send (default: 5)",
    )

    args = parser.parse_args()

    if not args.mode:
        parser.print_help()
        return 1

    try:
        if args.mode == "server":
            trio.run(run_server, args.port)
        elif args.mode == "client":
            return trio.run(run_client, args.destination, args.count)
    except KeyboardInterrupt:
        print("\n[INFO] Goodbye!")
        return 0
    except Exception as e:
        print(f"[ERROR] Fatal error: {e}")
        logging.exception("Fatal error")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
