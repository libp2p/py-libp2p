#!/usr/bin/env python3
"""Local QUIC upload probe: log CWND / RTT during a 64 MiB transfer."""

from __future__ import annotations

import logging
import os
import time

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.transport.quic.config import QUICTransportConfig
from libp2p.transport.quic.connection import QUICConnection

UPLOAD_BYTES = 64 * 1024 * 1024
CHUNK = 64 * 1024


async def _run() -> None:
    os.environ.setdefault("LIBP2P_QUIC_CC_STATS", "1")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("libp2p.transport.quic.connection").setLevel(logging.INFO)

    listener_kp = create_new_key_pair()
    dialer_kp = create_new_key_pair()
    quic_cfg = QUICTransportConfig()
    listen_addrs = [multiaddr.Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1")]

    listener = new_host(
        key_pair=listener_kp, enable_quic=True, quic_transport_opt=quic_cfg
    )
    dialer = new_host(key_pair=dialer_kp, enable_quic=True, quic_transport_opt=quic_cfg)

    async def handle(stream) -> None:  # type: ignore[no-untyped-def]
        received = 0
        while received < UPLOAD_BYTES:
            data = await stream.read(CHUNK)
            if not data:
                break
            received += len(data)
        await stream.close()

    listener.set_stream_handler("/perf/probe/1.0.0", handle)

    async with listener.run(listen_addrs=listen_addrs):
        peer_addr = listener.get_addrs()[0].encapsulate(
            multiaddr.Multiaddr(f"/p2p/{listener.get_id()}")
        )
        async with dialer.run(listen_addrs=[]):
            info = info_from_p2p_addr(peer_addr)
            await dialer.connect(info)
            stream = await dialer.new_stream(listener.get_id(), ["/perf/probe/1.0.0"])

            net_conns = dialer.get_network().connections
            swarm_conn = next(iter(net_conns.values()))
            if isinstance(swarm_conn, list):
                swarm_conn = swarm_conn[0]
            muxed = swarm_conn.muxed_conn
            assert isinstance(muxed, QUICConnection)

            payload = b"x" * CHUNK
            sent = 0
            t0 = time.perf_counter()
            samples: list[dict[str, float | int | None]] = []
            while sent < UPLOAD_BYTES:
                n = min(CHUNK, UPLOAD_BYTES - sent)
                await stream.write(payload[:n])
                sent += n
                if len(samples) < 20 or sent % (8 * 1024 * 1024) < CHUNK:
                    samples.append(muxed.get_congestion_stats())
            if hasattr(stream, "close_write"):
                await stream.close_write()
            else:
                await stream.close()
            elapsed = time.perf_counter() - t0
            gbps = (UPLOAD_BYTES * 8) / elapsed / 1e9
            print(f"uploaded={UPLOAD_BYTES} elapsed={elapsed:.3f}s gbps={gbps:.3f}")
            print("sample_count", len(samples))
            for i, s in enumerate(samples[:15]):
                print(f"sample[{i}] {s}")
            print("last", samples[-1] if samples else None)
            if samples:
                cwnd = int(samples[-1].get("congestion_window") or 0)
                srtt = float(samples[-1].get("smoothed_rtt") or 0.0)
                if srtt > 0 and cwnd:
                    print(f"implied_bdp_gbps≈{(cwnd * 8 / srtt) / 1e9:.3f}")


if __name__ == "__main__":
    trio.run(_run)
