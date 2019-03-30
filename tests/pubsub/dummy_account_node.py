import asyncio
import uuid
import multiaddr

from libp2p import new_node
from libp2p.pubsub.pb import rpc_pb2_grpc
from libp2p.pubsub.pb import rpc_pb2
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
            rpc_incoming = rpc_pb2.RPC()
            rpc_incoming.ParseFromString(incoming)
            for message in rpc_incoming.publish:
                msg_comps = message.split(",")
                if msg_comps[0] == "send":
                    self.handle_send_crypto(msg_comps[1], msg_comps[2], int(msg_comps[3]))
                elif msg_comps[0] == "set":
                    self.handle_set_crypto_for_user(msg_comps[1], int(msg_comps[2]))

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
        packet = generate_RPC_packet(my_id, [CRYPTO_TOPIC], msg_contents, generate_message_id())
        await self.floodsub.publish(my_id, msg.SerializeToString())

    async def publish_set_crypto(self, user, amount):
        """
        Create a set crypto message and publish that message to all other nodes
        :param user: user to set crypto for
        :param amount: amount of crypto
        """
        my_id = str(self.libp2p_node.get_id())
        msg_contents = "set," + user + "," + str(amount)
        packet = generate_RPC_packet(my_id, [CRYPTO_TOPIC], msg_contents, generate_message_id())

        await self.floodsub.publish(my_id, packet.SerializeToString())

    def handle_send_crypto(self, source_user, dest_user, amount):
        """
        Handle incoming send_crypto message
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

    def handle_set_crypto_for_user(self, dest_user, amount):
        """
        Handle incoming set_crypto message
        :param dest_user: user to set crypto for
        :param amount: amount of crypto
        """
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

def generate_message_id():
    """
    Generate a unique message id
    :return: messgae id
    """
    return str(uuid.uuid1())

def generate_RPC_packet(origin_id, topics, msg_content, msg_id):
    packet = rpc_pb2.RPC()
    packet.publish.extend([rpc_pb2.Message(
        from_id=origin_id.encode('utf-8'),
        seqno=msg_id.encode('utf-8'),
        data=msg_content.encode('utf-8'),
        topicIDs=topics.encode('utf-8'))
        ])

    for topic in topics:
        packet.subscriptions.extend([rpc_pb2.RPC.SubOpts(
            subscribe=True,
            topicid = topic.encode('utf-8')
            )])

    return packet
