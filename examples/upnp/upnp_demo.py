import argparse
import logging

import multiaddr
import trio

from libp2p import new_host
from libp2p.discovery.upnp import UpnpManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("upnp-demo")


async def run(port: int) -> None:
    listen_maddr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")
    host = new_host()

    upnp = UpnpManager()
    if not await upnp.discover():
        logger.error(
            "❌ Could not find a UPnP-enabled gateway. "
            "The host will start, but may not be dialable from the public internet."
        )
    else:
        logger.info(f"✅ UPnP gateway found! External IP: {upnp.get_external_ip()}")

    mapped_port = None
    async with host.run(listen_addrs=[listen_maddr]):
        try:
            actual_listen_maddr = host.get_addrs()[0]
            mapped_port = actual_listen_maddr.value_for_protocol("tcp")

            # If discovery was successful, now we can map the port
            if upnp.get_external_ip():
                if await upnp.add_port_mapping(mapped_port):
                    logger.info(f"✅ Port {mapped_port} successfully mapped!")
                else:
                    logger.error(f"❌ Failed to map port {mapped_port}.")

            logger.info(f"Host started with ID: {host.get_id().pretty()}")
            logger.info(f"Listening on: {actual_listen_maddr}")
            logger.info("Host is running. Press Ctrl+C to shut down.")
            await trio.sleep_forever()

        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            if mapped_port and upnp.get_external_ip():
                logger.info("Removing UPnP port mapping...")
                await upnp.remove_port_mapping(mapped_port)
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
