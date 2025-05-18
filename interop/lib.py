from dataclasses import (
    dataclass,
)
import json
import time

from loguru import (
    logger,
)
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
        print(f"error occurred: {e}")


async def run_test(
    transport, ip, port, is_dialer, test_timeout, redis_addr, sec_protocol, muxer
):
    logger.info("Starting run_test")

    redis_client = RedisClient(
        redis.Redis(host="localhost", port=int(redis_addr), db=0)
    )
    (host, listen_addr) = await build_host(transport, ip, port, sec_protocol, muxer)
    logger.info(f"Running ping test local_peer={host.get_id()}")

    async with host.run(listen_addrs=[listen_addr]), trio.open_nursery() as nursery:
        if not is_dialer:
            host.set_stream_handler(PING_PROTOCOL_ID, handle_ping)
            ma = f"{listen_addr}/p2p/{host.get_id().pretty()}"
            redis_client.rpush("listenerAddr", ma)

            logger.info(f"Test instance, listening: {ma}")
        else:
            redis_addr = redis_client.brpop("listenerAddr", timeout=5)
            destination = redis_addr[0].decode()
            maddr = multiaddr.Multiaddr(destination)
            info = info_from_p2p_addr(maddr)

            handshake_start = time.perf_counter()

            await host.connect(info)
            stream = await host.new_stream(info.peer_id, [PING_PROTOCOL_ID])

            logger.info("Remote conection established")
            nursery.start_soon(send_ping, stream)

            handshake_plus_ping = (time.perf_counter() - handshake_start) * 1000.0

            logger.info(f"handshake time: {handshake_plus_ping:.2f}ms")
            return

        await trio.sleep_forever()


@dataclass
class Report:
    handshake_plus_one_rtt_millis: float
    ping_rtt_millis: float

    def gen_report(self):
        return json.dumps(self.__dict__)
