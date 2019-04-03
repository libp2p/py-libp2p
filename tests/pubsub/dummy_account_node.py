import asyncio
import multiaddr
import uuid

from utils import message_id_generator, generate_RPC_packet
from libp2p import new_node
from libp2p.pubsub.pubsub import Pubsub
from libp2p.pubsub.floodsub import FloodSub

SUPPORTED_PUBSUB_PROTOCOLS = ["/floodsub/1.0.0"]
CRYPTO_TOPIC = "ethereum"

# Message format:
# Sending crypto: <source>,<dest>,<amount as integer>
#                 Ex. send,aspyn,alex,5
# Set crypto: <dest>,<amount as integer>
#                 Ex. set,rob,5
# Determine message type by looking at first item before first comma

class DummyAccountNode():
    """
    Node which has an internal balance mapping, meant to serve as 
    a dummy crypto blockchain. There is no actual blockchain, just a simple
    map indicating how much crypto each user in the mappings holds
    """

    def __init__(self):
        self.balances = {}
        self.next_msg_id_func = message_id_generator(0)
        self.node_id = str(uuid.uuid1())

    @classmethod
    async def create(cls):
        """
        Create a new DummyAccountNode and attach a libp2p node, a floodsub, and a pubsub
        instance to this new node

        We use create as this serves as a factory function and allows us
        to use async await, unlike the init function
        """
        self = DummyAccountNode()

        libp2p_node = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
        await libp2p_node.get_network().listen(multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0"))

        self.libp2p_node = libp2p_node

        self.floodsub = FloodSub(SUPPORTED_PUBSUB_PROTOCOLS)
        self.pubsub = Pubsub(self.libp2p_node, self.floodsub, "a")
        return self

    async def handle_incoming_msgs(self):
        """
        Handle all incoming messages on the CRYPTO_TOPIC from peers
        """
        while True:
            incoming = await self.q.get()
            msg_comps = incoming.data.decode('utf-8').split(",")

            if msg_comps[0] == "send":
                self.handle_send_crypto(msg_comps[1], msg_comps[2], int(msg_comps[3]))
            elif msg_comps[0] == "set":
                self.handle_set_crypto(msg_comps[1], int(msg_comps[2]))

    async def setup_crypto_networking(self):
        """
        Subscribe to CRYPTO_TOPIC and perform call to function that handles
        all incoming messages on said topic
        """
        self.q = await self.pubsub.subscribe(CRYPTO_TOPIC)

        asyncio.ensure_future(self.handle_incoming_msgs())

    async def publish_send_crypto(self, source_user, dest_user, amount):
        """
        Create a send crypto message and publish that message to all other nodes
        :param source_user: user to send crypto from
        :param dest_user: user to send crypto to
        :param amount: amount of crypto to send
        """
        my_id = str(self.libp2p_node.get_id())
        msg_contents = "send," + source_user + "," + dest_user + "," + str(amount)
        packet = generate_RPC_packet(my_id, [CRYPTO_TOPIC], msg_contents, self.next_msg_id_func())
        await self.floodsub.publish(my_id, packet.SerializeToString())

    async def publish_set_crypto(self, user, amount):
        """
        Create a set crypto message and publish that message to all other nodes
        :param user: user to set crypto for
        :param amount: amount of crypto
        """
        my_id = str(self.libp2p_node.get_id())
        msg_contents = "set," + user + "," + str(amount)
        packet = generate_RPC_packet(my_id, [CRYPTO_TOPIC], msg_contents, self.next_msg_id_func())

        await self.floodsub.publish(my_id, packet.SerializeToString())

    def handle_send_crypto(self, source_user, dest_user, amount):
        """
        Handle incoming send_crypto message
        :param source_user: user to send crypto from
        :param dest_user: user to send crypto to
        :param amount: amount of crypto to send 
        """
        print("handle send " + self.node_id)
        if source_user in self.balances:
            self.balances[source_user] -= amount
        else:
            self.balances[source_user] = -amount

        if dest_user in self.balances:
            self.balances[dest_user] += amount
        else:
            self.balances[dest_user] = amount

    def handle_set_crypto(self, dest_user, amount):
        """
        Handle incoming set_crypto message
        :param dest_user: user to set crypto for
        :param amount: amount of crypto
        """
        print("handle set " + self.node_id)
        self.balances[dest_user] = amount

    def get_balance(self, user):
        """
        Get balance in crypto for a particular user
        :param user: user to get balance for
        :return: balance of user
        """
        if user in self.balances:
            return self.balances[user]
        else:
            return -1

