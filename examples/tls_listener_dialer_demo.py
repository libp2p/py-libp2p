#!/usr/bin/env python3
"""
TLS Listener and Dialer Demo

Usage:
    python examples/tls_listener_dialer_demo.py listener [port]
    python examples/tls_listener_dialer_demo.py dialer <listener_address>
    python examples/tls_listener_dialer_demo.py
"""

import sys
import trio
import multiaddr
from libp2p import new_host, generate_new_rsa_identity
from libp2p.security.tls.transport import TLSTransport, PROTOCOL_ID
from libp2p.peer.peerinfo import info_from_p2p_addr


async def run_listener(port: int = 8000):
    key_pair = generate_new_rsa_identity()
    tls_transport = TLSTransport(key_pair)
    sec_opt = {PROTOCOL_ID: tls_transport}
    host = new_host(key_pair=key_pair, sec_opt=sec_opt)
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    async with host.run(listen_addrs=[listen_addr]):
        addrs = host.get_addrs()
        print(f"Listener running at: {addrs[0]}")
        print(f"Peer ID: {host.get_id()}")
        try:
            await trio.sleep_forever()
        except KeyboardInterrupt:
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

    async with host.run(listen_addrs=[]):
        try:
            await host.connect(peer_info)
            print(f"Connected to {peer_info.peer_id}")
            await trio.sleep(5)
            await host.close()
        except Exception as e:
            print(f"Connection failed: {e}")
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

    async with trio.open_nursery() as nursery:
        async with listener_host.run(listen_addrs=[listen_addr]):
            listener_addrs = listener_host.get_addrs()
            print(f"Listener: {listener_addrs[0]}")

            await trio.sleep(1)

            async with dialer_host.run(listen_addrs=[]):
                peer_info = info_from_p2p_addr(listener_addrs[0])
                await dialer_host.connect(peer_info)
                print(f"Dialer connected to {peer_info.peer_id}")

                await trio.sleep(2)

                await dialer_host.close()
                await listener_host.close()
                nursery.cancel_scope.cancel()


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "listener":
            port = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
            trio.run(run_listener, port)
        elif sys.argv[1] == "dialer":
            if len(sys.argv) < 3:
                print("Usage: python examples/tls_listener_dialer_demo.py dialer <listener_address>")
                sys.exit(1)
            trio.run(run_dialer, sys.argv[2])
        else:
            print(f"Unknown command: {sys.argv[1]}")
            sys.exit(1)
    else:
        trio.run(run_full_test)


if __name__ == "__main__":
    main()

