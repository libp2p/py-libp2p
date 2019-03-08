from libp2p import new_node
from pubsub.message import create_message_talk

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
    async def create():
        self = DummyAccountNode()
        libp2p_node = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
        self.libp2p_node = libp2p_node

        self.floodsub = FloodSub(SUPPORTED_PUBSUB_PROTOCOLS)
        self.pubsub = Pubsub(self.libp2p_node, self.floodsub, "a")
        return self

    async def setup_crypto_networking():
        self.q = await pubsub_b.subscribe(CRYPTO_TOPIC)

        while True:
            # Force context switch
            asyncio.sleep(0)

            message_raw = await self.q.get()
            message = create_message_talk(message_raw)
            contents = message.data

            msg_comps = contents.split(",")
            if msg_comps[0] == "send":
                handle_send_crypto(msg_comps[1], msg_comps[2], int(msg_comps[3]))
            elif msg_comps[1] == "set":
                handle_set_crypto_for_user(msg_comps[1], int(msg_comps[2]))

    async def publish_send_crypto(source_user, dest_user, amount):
        """
        Create a send crypto message and publish that message to all other nodes
        """
        my_id = str(self.libp2p_node.get_id())
        msg_contents = "send," + source_user + "," + dest_user + "," + str(amount)
        msg = MessageTalk(my_id, my_id, [CRYPTO_TOPIC], msg_contents)
        await self.floodsub.publish(my_id, msg.to_str())

    async def publish_set_crypto(user, amount):
        """
        Create a set crypto message and publish that message to all other nodes
        """
        my_id = str(self.libp2p_node.get_id())
        msg_contents = "set," + user + "," + str(amount)
        msg = MessageTalk(my_id, my_id, [CRYPTO_TOPIC], msg_contents)
        await self.floodsub.publish(my_id, msg.to_str())

    def handle_send_crypto(source_user, dest_user, amount):
        """
        Handle incoming send_crypto message
        """
        if source_user in self.balances:
            self.balances[source_user] -= amount
        else:
            self.balances[source_user] = -amount

        if dest_user in self.balances:
            self.balances[dest_user] += amount
        else:
            self.balances[dest_user] = amount

    def handle_set_crypto_for_user(dest_user, amount):
        """
        Handle incoming set_crypto message
        """
        self.balances[dest_user] = amount

    def get_balance_for_user(user):
        """
        Get balance in crypto for a particular user
        """
        return self.balances[user]

