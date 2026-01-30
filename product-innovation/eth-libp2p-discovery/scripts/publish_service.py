import asyncio

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from p2p.node import Libp2pNode
from p2p.dht import DHTNode
from p2p.service_publisher import ServicePublisher


SERVICE_ID = bytes.fromhex(
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
)


async def main():
    node = Libp2pNode()
    await node.start()

    print("Publisher peer ID:", node.peer_id.pretty())
    print("Listening on:", node.peer_info.addrs)

    dht = DHTNode(node.host)
    await dht.start()

    private_key = Ed25519PrivateKey.generate()

    publisher = ServicePublisher(
        dht=dht,
        service_id=SERVICE_ID,
        private_key=private_key,
    )

    await publisher.start_auto_publish(
        peer_id=node.peer_id,
        multiaddrs=list(node.peer_info.addrs),
    )

    print("Service published. Press Ctrl+C to stop.")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
