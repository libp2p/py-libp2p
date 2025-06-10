import logging

import multiaddr
import redis
import trio

from interop.arch import (
    RedisClient,
    build_host,
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

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("ping_debug.log", mode="w", encoding="utf-8"),
    ],
)

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
                print(f"[INFO] Wailting for ping data from {peer_id}...")
                logging.debug(f"Stream state: {stream}")
                data = await stream.read(PING_LENGTH)

                if not data:
                    print(
                        f"[INFO] No data received,conneciton likely closed by {peer_id}"
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


async def send_ping(stream: INetStream, count: int = 1) -> None:
    """Send a sequence of pings compatible with rust-libp2p."""
    peer_id = stream.muxed_conn.peer_id
    print(f"[INFO] Starting ping sequence to {peer_id} ({count} pings)")

    import os
    import time

    rtts = []

    for i in range(1, count + 1):
        try:
            # Generate random 32-byte payload as per ping protcol spec
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
                print(f"[PING {i}] Successful RTT: {rtt:.2f}ms")
            else:
                print(f"[ERROR] Ping {i} failed: response mismatch or incomplete")
                if response:
                    logging.debug(f"Expecte: {payload.hex()}")
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
        print(f"   RTT: min={min_rtt:.2f}ms, avg={avg_rtt:.2f}ms, max={max_rtt:.2f}ms")
    else:
        print(f"\n[STATS] All pings failed ({count} attempts)")


async def run_test(
    transport, ip, port, is_dialer, test_timeout, redis_addr, sec_protocol, muxer
):
    redis_client = RedisClient(
        redis.Redis(host="localhost", port=int(redis_addr), db=0)
    )
    (host, listen_addr) = await build_host(transport, ip, port, sec_protocol, muxer)
    async with host.run(listen_addrs=[listen_addr]):
        if not is_dialer:
            print("[INFO] Starting py-libp2p ping server...")

            print(f"[INFO] Registering ping handler for protocol: {PING_PROTOCOL_ID}")
            host.set_stream_handler(PING_PROTOCOL_ID, handle_ping)

            # Also register alternative protocol IDs for better compatibilty
            alt_protcols = [
                TProtocol("/ping/1.0.0"),
                TProtocol("/libp2p/ping/1.0.0"),
            ]

            for alt_proto in alt_protcols:
                print(f"[INFO] Also registering handler for: {alt_proto}")
                host.set_stream_handler(alt_proto, handle_ping)

            print("[INFO] Server started successfully!")
            print(f"[INFO] Peer ID: {host.get_id()}")
            print(f"[INFO] Listening: /ip4/{ip}/tcp/{port}")
            print(f"[INFO] Primary Protocol: {PING_PROTOCOL_ID}")

            ma = f"{listen_addr}/p2p/{host.get_id().pretty()}"
            redis_client.rpush("listenerAddr", ma)

            print("[INFO] Pushed address to Redis database")
            await trio.sleep_forever()
        else:
            print("[INFO] Starting py-libp2p ping client...")

            print("[INFO] Fetching remote address from Redis database...")
            redis_addr = redis_client.brpop("listenerAddr", timeout=5)
            destination = redis_addr[0].decode()
            maddr = multiaddr.Multiaddr(destination)
            info = info_from_p2p_addr(maddr)
            target_peer_id = info.peer_id

            print(f"[INFO] Our Peer ID: {host.get_id()}")
            print(f"[INFO] Target: {destination}")
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
                print("[ERROR] Ensure the target peer supports one of these protocols")
                for proto in protocols_to_try:
                    print(f"[ERROR]   - {proto}")
                return 1

            await send_ping(stream)

            await stream.close()
            print("[INFO] Stream closed successfully")

        print("\n[INFO] Client stopped")
        return 0
