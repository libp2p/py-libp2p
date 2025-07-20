import argparse
import logging

import multiaddr
import trio

from libp2p import new_host

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("upnp-demo")


async def run(port: int) -> None:
    listen_maddr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")
    host = new_host(enable_upnp=True)

    async with host.run(listen_addrs=[listen_maddr]):
        try:
            logger.info(f"Host started with ID: {host.get_id().pretty()}")
            logger.info(f"Listening on: {host.get_addrs()}")
            logger.info("Host is running. Press Ctrl+C to shut down.")
            logger.info("If UPnP discovery was successful, ports are now mapped.")
            await trio.sleep_forever()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            # UPnP teardown is automatic via host.run()
            logger.info("Shutdown complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="UPnP example for py-libp2p")
    parser.add_argument(
        "-p", "--port", type=int, default=0, help="Local TCP port (0 for random)"
    )
    args = parser.parse_args()

    try:
        trio.run(run, args.port)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
