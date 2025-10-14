import trio

from libp2p import new_host, generate_new_rsa_identity
from libp2p.security.tls.transport import TLSTransport
from libp2p.utils.address_validation import get_available_interfaces


async def main() -> None:
    # Generate a new key pair for this host
    key_pair = generate_new_rsa_identity()
    
    listen_addrs = get_available_interfaces(0)
    print("Starting TLS-enabled libp2p host...")
    host = new_host(
        key_pair=key_pair,
        sec_opt={"/tls/1.0.0": TLSTransport(key_pair)}
    )

    async with host.run(listen_addrs=listen_addrs):
        print(f"Host started with Peer ID: {host.get_id()}")
        for addr in host.get_addrs():
            print(f"Listening securely on: {addr}")

        print("TLS is now active for this peer. Press Ctrl+C to stop.")
        try:
            await trio.sleep(5)
        except KeyboardInterrupt:
            pass

    print("Host shut down cleanly.")


if __name__ == "__main__":
    trio.run(main)

