import asyncio
from libp2p import new_node
from pubsub.message import create_message_talk
from pubsub.pubsub import Pubsub
from pubsub.floodsub import FloodSub
from pubsub.message import MessageTalk

SUPPORTED_PUBSUB_PROTOCOLS = ["/floodsub/1.0.0"]
CRYPTO_TOPIC = "ethereum"

# Message format:
# Sending crypto: <source>,<dest>,<amount as integer>
#                 Ex. send,aspyn,alex,5
# Set crypto: <dest>,<amount as integer>
#                 Ex. set,rob,5
# Determine message type by looking at first item before first comma

class DummyAccountNode():
    def __init__(self):
        self.balances = {}

    @classmethod
    async def create(cls):
        self = DummyAccountNode()
        libp2p_node = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
        self.libp2p_node = libp2p_node

        self.floodsub = FloodSub(SUPPORTED_PUBSUB_PROTOCOLS)
        self.pubsub = Pubsub(self.libp2p_node, self.floodsub, "a")
        return self

    async def listen_to_stuff(self):
        while True:
            # Force context switch
            await asyncio.sleep(0)
            message_raw = await self.q.get()
            message = create_message_talk(message_raw)
            contents = message.data

            msg_comps = contents.split(",")
            if msg_comps[0] == "send":
                handle_send_crypto(msg_comps[1], msg_comps[2], int(msg_comps[3]))
            elif msg_comps[1] == "set":
                handle_set_crypto_for_user(msg_comps[1], int(msg_comps[2]))

    async def setup_crypto_networking(self):
        self.q = await self.pubsub.subscribe(CRYPTO_TOPIC)

        # This does not work but it's meant to setup another thread to loop on
        # and yes I do mean thread (look in docs)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.listen_to_stuff())
        loop.close()

    async def publish_send_crypto(self, source_user, dest_user, amount):
        """
        Create a send crypto message and publish that message to all other nodes
        """
        my_id = str(self.libp2p_node.get_id())
        msg_contents = "send," + source_user + "," + dest_user + "," + str(amount)
        msg = MessageTalk(my_id, my_id, [CRYPTO_TOPIC], msg_contents)
        await self.floodsub.publish(my_id, msg.to_str())

    async def publish_set_crypto(self, user, amount):
        """
        Create a set crypto message and publish that message to all other nodes
        """
        my_id = str(self.libp2p_node.get_id())
        msg_contents = "set," + user + "," + str(amount)
        msg = MessageTalk(my_id, my_id, [CRYPTO_TOPIC], msg_contents)
        await self.floodsub.publish(my_id, msg.to_str())

    def handle_send_crypto(self, source_user, dest_user, amount):
        """
        Handle incoming send_crypto message
        """
        print("HIT ME")
        if source_user in self.balances:
            self.balances[source_user] -= amount
        else:
            self.balances[source_user] = -amount

        if dest_user in self.balances:
            self.balances[dest_user] += amount
        else:
            self.balances[dest_user] = amount
        print("HIT ME2")

    def handle_set_crypto_for_user(self, dest_user, amount):
        """
        Handle incoming set_crypto message
        """
        print("HIT ME3")
        self.balances[dest_user] = amount
        print("HIT ME4")

    def get_balance(self, user):
        """
        Get balance in crypto for a particular user
        """
        if user in self.balances:
            return self.balances[user]
        else:
            return -1

