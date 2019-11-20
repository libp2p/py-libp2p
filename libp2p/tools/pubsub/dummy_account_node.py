import asyncio
from typing import Dict
import uuid

from libp2p.host.host_interface import IHost
from libp2p.pubsub.floodsub import FloodSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.tools.constants import LISTEN_MADDR
from libp2p.tools.factories import FloodsubFactory, PubsubFactory

CRYPTO_TOPIC = "ethereum"

# Message format:
# Sending crypto: <source>,<dest>,<amount as integer>
#                 Ex. send,aspyn,alex,5
# Set crypto: <dest>,<amount as integer>
#                 Ex. set,rob,5
# Determine message type by looking at first item before first comma


class DummyAccountNode:
    """
    Node which has an internal balance mapping, meant to serve as a dummy
    crypto blockchain.

    There is no actual blockchain, just a simple map indicating how much
    crypto each user in the mappings holds
    """

    libp2p_node: IHost
    pubsub: Pubsub
    floodsub: FloodSub

    def __init__(self, libp2p_node: IHost, pubsub: Pubsub, floodsub: FloodSub):
        self.libp2p_node = libp2p_node
        self.pubsub = pubsub
        self.floodsub = floodsub
        self.balances: Dict[str, int] = {}
        self.node_id = str(uuid.uuid1())

    @classmethod
    async def create(cls) -> "DummyAccountNode":
        """
        Create a new DummyAccountNode and attach a libp2p node, a floodsub, and
        a pubsub instance to this new node.

        We use create as this serves as a factory function and allows us
        to use async await, unlike the init function
        """

        pubsub = PubsubFactory(router=FloodsubFactory())
        await pubsub.host.get_network().listen(LISTEN_MADDR)
        return cls(libp2p_node=pubsub.host, pubsub=pubsub, floodsub=pubsub.router)

    async def handle_incoming_msgs(self) -> None:
        """Handle all incoming messages on the CRYPTO_TOPIC from peers."""
        while True:
            incoming = await self.q.get()
            msg_comps = incoming.data.decode("utf-8").split(",")

            if msg_comps[0] == "send":
                self.handle_send_crypto(msg_comps[1], msg_comps[2], int(msg_comps[3]))
            elif msg_comps[0] == "set":
                self.handle_set_crypto(msg_comps[1], int(msg_comps[2]))

    async def setup_crypto_networking(self) -> None:
        """Subscribe to CRYPTO_TOPIC and perform call to function that handles
        all incoming messages on said topic."""
        self.q = await self.pubsub.subscribe(CRYPTO_TOPIC)

        asyncio.ensure_future(self.handle_incoming_msgs())

    async def publish_send_crypto(
        self, source_user: str, dest_user: str, amount: int
    ) -> None:
        """
        Create a send crypto message and publish that message to all other
        nodes.

        :param source_user: user to send crypto from
        :param dest_user: user to send crypto to
        :param amount: amount of crypto to send
        """
        msg_contents = "send," + source_user + "," + dest_user + "," + str(amount)
        await self.pubsub.publish(CRYPTO_TOPIC, msg_contents.encode())

    async def publish_set_crypto(self, user: str, amount: int) -> None:
        """
        Create a set crypto message and publish that message to all other
        nodes.

        :param user: user to set crypto for
        :param amount: amount of crypto
        """
        msg_contents = "set," + user + "," + str(amount)
        await self.pubsub.publish(CRYPTO_TOPIC, msg_contents.encode())

    def handle_send_crypto(self, source_user: str, dest_user: str, amount: int) -> None:
        """
        Handle incoming send_crypto message.

        :param source_user: user to send crypto from
        :param dest_user: user to send crypto to
        :param amount: amount of crypto to send
        """
        if source_user in self.balances:
            self.balances[source_user] -= amount
        else:
            self.balances[source_user] = -amount

        if dest_user in self.balances:
            self.balances[dest_user] += amount
        else:
            self.balances[dest_user] = amount

    def handle_set_crypto(self, dest_user: str, amount: int) -> None:
        """
        Handle incoming set_crypto message.

        :param dest_user: user to set crypto for
        :param amount: amount of crypto
        """
        self.balances[dest_user] = amount

    def get_balance(self, user: str) -> int:
        """
        Get balance in crypto for a particular user.

        :param user: user to get balance for
        :return: balance of user
        """
        if user in self.balances:
            return self.balances[user]
        else:
            return -1
