import asyncio
import sys
import logging

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from libp2p.peer.peerinfo import PeerInfo
from multiaddr import Multiaddr

from p2p.node import Libp2pNode
from p2p.dht import DHTNode
from p2p.service_resolver import ServiceResolver

SERVICE_ID = bytes.fromhex(
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
)

TCP_PORT = 9000
PEER_ID = "12D3KooWPcePNNK6uEasXG1YBgRpGUHJsCMompm9Qx9Lt4wBDv6f"

BOOTSTRAP_ADDR = f"/ip4/127.0.0.1/tcp/{TCP_PORT}/p2p/{PEER_ID}"

logger = logging.getLogger("resolve_service")
logging.basicConfig(level=logging.INFO)

def parse_peerinfo_from_multiaddr(ma: Multiaddr):
    components = str(ma).split("/")
    try:
        idx = components.index("p2p")
        peer_id_str = components[idx + 1]
        base_addr = "/" + "/".join(components[1:idx])
        addr = Multiaddr(base_addr)
        return PeerInfo(peer_id=peer_id_str, addrs=[addr])
    except Exception as e:
        raise ValueError("Could not parse p2p multiaddr") from e

async def run_resolver():
    node = None
    dht = None
    bootstrap_peer = None
    try:
        node = Libp2pNode()
        await node.start()
        logger.info(f"Resolver peer ID: {node.peer_id.pretty()}")

        bootstrap_ma = Multiaddr(BOOTSTRAP_ADDR)
        if hasattr(PeerInfo, "from_p2p_addr"):
            bootstrap_peer = PeerInfo.from_p2p_addr(bootstrap_ma)
        else:
            bootstrap_peer = parse_peerinfo_from_multiaddr(bootstrap_ma)

        await asyncio.sleep(0.1)

        dht = DHTNode(node.host)
        try:
            await dht.start(bootstrap_peers=[bootstrap_peer])
        except RuntimeError as err:
            logger.error(f"Error starting DHT or connecting to peer: {err}")
            logger.error("This error can occur if you receive 'must be called from async context'.")
            logger.error(
                "If you are using a library that utilizes 'trio', ensure trio is run with its event loop, "
                "or prefer using a pure asyncio-based libp2p stack."
            )
            raise
        except Exception as err:
            logger.error(f"Unexpected error starting DHT or connecting to peer: {err}")
            raise

        owner_private_key = Ed25519PrivateKey.generate()
        owner_public_key = owner_private_key.public_key()

        resolver = ServiceResolver(
            dht=dht,
            service_id=SERVICE_ID,
            owner_public_key=owner_public_key,
        )

        try:
            peer = await resolver.resolve()
        except Exception as e:
            logger.error(f"Exception during service resolution: {e}")
            raise

        if not peer:
            logger.info("Service not found")
            return

        logger.info("Service resolved:")
        logger.info(f"Peer ID: {peer.peer_id.pretty()}")
        logger.info("Addrs:")
        for addr in peer.addrs:
            logger.info(f"  {addr}")

    except Exception as err:
        pass
    finally:
        if dht:
            await dht.stop()
        if node:
            await node.stop()

def main():
    try:
        asyncio.run(run_resolver())
    except RuntimeError as err:
        logger.error(f"Failed to run asyncio main: {err}")
        logger.error(
            "If you encounter 'must be called from async context', your libp2p or dependencies may require 'trio' context or specific event loop integration."
        )
        sys.exit(1)
    except Exception as err:
        logger.error(f"Unexpected error: {err}")
        sys.exit(1)

if __name__ == "__main__":
    main()