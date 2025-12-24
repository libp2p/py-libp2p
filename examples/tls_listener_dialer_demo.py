#!/usr/bin/env python3
"""
TLS Listener and Dialer Demo with "ping-pong" test.

Usage:
    python examples/tls_listener_dialer_demo.py listener [port]
    python examples/tls_listener_dialer_demo.py dialer <listener_address>
    python examples/tls_listener_dialer_demo.py
"""

import sys

import multiaddr
import trio

from libp2p import generate_new_rsa_identity, new_host
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.security.tls.transport import PROTOCOL_ID, TLSTransport

PING_PROTOCOL = "/tls/ping/1.0.0"


async def handle_ping(stream):
    try:
        while True:
            data = await stream.read(4)
            if not data:
                break
            await stream.write(b"pong")
            await stream.close()
            break
    except Exception as e:
        print(f"Ping handler error: {e}")
        try:
            await stream.close()
        except Exception:
            pass


async def run_listener(port: int = 8000):
    key_pair = generate_new_rsa_identity()
    tls_transport = TLSTransport(key_pair)
    sec_opt = {PROTOCOL_ID: tls_transport}
    host = new_host(key_pair=key_pair, sec_opt=sec_opt)
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    # Safe context manager handling
    # since new_host.run may not support __aenter__ natively in dev
    host_run_ctx = host.run(listen_addrs=[listen_addr])

    try:
        await host_run_ctx.__aenter__()
        host.set_stream_handler(TProtocol(PING_PROTOCOL), handle_ping)
        addrs = host.get_addrs()
        print(f"Listener running at: {addrs[0]}")
        print(f"Peer ID: {host.get_id()}")
        print(f'Waiting for ping requests on protocol: "{PING_PROTOCOL}"')
        try:
            await trio.sleep_forever()
        except KeyboardInterrupt:
            pass
    finally:
        await host_run_ctx.__aexit__(None, None, None)
        await host.close()


async def run_dialer(listener_address: str):
    key_pair = generate_new_rsa_identity()
    tls_transport = TLSTransport(key_pair)
    sec_opt = {PROTOCOL_ID: tls_transport}
    host = new_host(key_pair=key_pair, sec_opt=sec_opt)

    try:
        maddr = multiaddr.Multiaddr(listener_address)
        peer_info = info_from_p2p_addr(maddr)
    except Exception as e:
        print(f"Error parsing address: {e}")
        return

    host_run_ctx = host.run(listen_addrs=[])
    try:
        await host_run_ctx.__aenter__()
        await host.connect(peer_info)
        print(f"Connected to {peer_info.peer_id}")

        # Perform a ping-pong activity
        try:
            stream = await host.new_stream(
                peer_info.peer_id, [TProtocol(PING_PROTOCOL)]
            )
            print("Sending: ping")
            await stream.write(b"ping")
            data = await stream.read(4)
            print(f"Got reply: {data!r}")
            await stream.close()
        except Exception as e:
            print(f"Ping-pong failed: {e}")

        await trio.sleep(2)
        await host.close()
    except Exception as e:
        print(f"Connection failed: {e}")
    finally:
        await host_run_ctx.__aexit__(None, None, None)
        await host.close()


async def run_full_test():
    listener_key_pair = generate_new_rsa_identity()
    dialer_key_pair = generate_new_rsa_identity()

    listener_tls = TLSTransport(listener_key_pair)
    dialer_tls = TLSTransport(dialer_key_pair)

    listener_tls.trust_peer_cert_pem(dialer_tls.get_certificate_pem())
    dialer_tls.trust_peer_cert_pem(listener_tls.get_certificate_pem())

    listener_sec_opt = {PROTOCOL_ID: listener_tls}
    dialer_sec_opt = {PROTOCOL_ID: dialer_tls}

    listener_host = new_host(key_pair=listener_key_pair, sec_opt=listener_sec_opt)
    dialer_host = new_host(key_pair=dialer_key_pair, sec_opt=dialer_sec_opt)

    listen_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8000")

    l_run_ctx = listener_host.run(listen_addrs=[listen_addr])
    d_run_ctx = dialer_host.run(listen_addrs=[])

    async with trio.open_nursery() as nursery:
        await l_run_ctx.__aenter__()
        listener_host.set_stream_handler(TProtocol(PING_PROTOCOL), handle_ping)
        listener_addrs = listener_host.get_addrs()
        print(f"Listener: {listener_addrs[0]}")

        await trio.sleep(1)

        await d_run_ctx.__aenter__()
        try:
            peer_info = info_from_p2p_addr(listener_addrs[0])
            await dialer_host.connect(peer_info)
            print(f"Dialer connected to {peer_info.peer_id}")

            # Ping-pong activity
            try:
                stream = await dialer_host.new_stream(
                    peer_info.peer_id, [TProtocol(PING_PROTOCOL)]
                )
                print("Dialer sending: ping")
                await stream.write(b"ping")
                data = await stream.read(4)
                print(f"Dialer got reply: {data!r}")
                await stream.close()
            except Exception as e:
                print(f"Ping-pong failed: {e}")

            await trio.sleep(4)
        finally:
            await d_run_ctx.__aexit__(None, None, None)
            await dialer_host.close()
            await l_run_ctx.__aexit__(None, None, None)
            await listener_host.close()
            nursery.cancel_scope.cancel()


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "listener":
            port = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
            trio.run(run_listener, port)
        elif sys.argv[1] == "dialer":
            if len(sys.argv) < 3:
                sys.exit(1)
            trio.run(run_dialer, sys.argv[2])
        else:
            print(f"Unknown command: {sys.argv[1]}")
            sys.exit(1)
    else:
        trio.run(run_full_test)


if __name__ == "__main__":
    main()
