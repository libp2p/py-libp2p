import asyncio
from .PubsubNotifee import PubsubNotifee

"""
For now, because I'm on a plane and don't have access to the go repo/protobuf stuff,
this is going to be the message format for the two types: subscription and talk

subscription indicates subscribing or unsubscribing from a topic
talk is sending a message on topic(s)

subscription format:
subscription
'from'
<one of 'sub', 'unsub'>:'topicid'
<one of 'sub', 'unsub'>:'topicid'
...

Ex.
subscription
my_peer_id
sub:topic1
sub:topic2
unsub:fav_topic

talk format:
talk
'from'
[topic_ids comma-delimited]
'data'

Ex.
talk
my_peer_id
topic1,topics_are_cool,foo
I like tacos
"""

class Pubsub():

    def __init__(self, host, router):
        """
        Construct a new Pubsub object, which is responsible for handling all
        Pubsub-related messages and relaying messages as appropriate to the
        Pubsub router (which is responsible for choosing who to send messages to).
        Since the logic for choosing peers to send pubsub messages to is
        in the router, the same Pubsub impl can back floodsub, gossipsub, etc.
        """
        self.host = host
        self.router = router

        # Register a notifee
        self.handle_peer_queue = asyncio.Queue()
        self.host.get_network().notify(PubsubNotifee(self.handle_peer_queue))

        # Register stream handlers for each pubsub router protocol to handle
        # the pubsub streams opened on those protocols
        self.protocols = self.router.get_protocols()
        for protocol in protocols:
            self.host.set_stream_handler(protocol, self.stream_handler)

        # TODO: determine if these need to be asyncio queues, or if could possibly
        # be ordinary blocking queues
        self.incoming_msgs_from_peers = asyncio.Queue()
        self.outgoing_messages = asyncio.Queue()

        # TODO: Make a cache (LRU cache?)
        self.seen_messages = []

        # Map of topics we are subscribed to to handler functions
        # for when the given topic receives a message
        self.my_topics = {}

        # Map of topic to peers to keep track of what peers are subscribed to
        self.peer_topics = {}

        # Create peers map
        # Note: this is the list of all peers who we have a pubsub stream to
        self.peers = {}

        # Call handle peer to keep waiting for updates to peer queue
        asyncio.ensure_future(handle_peer_queue)

    def get_hello_packet(self):
        # Generate subscription message with all topics we are subscribed to
        msg = self.host.get_id()
        l = len(self.my_topics)
        if l > 0:
            msg += '\n'
        for i in range(l):
            msg += "sub:" + topic
            if i < len(self.my_topics) - 1:
                msg += '\n'
        return msg

    def get_message_type(self, message):
        comps = message.split('\n')
        return comps[0]

    async def continously_read_stream(self, stream):
        while True:
            incoming = (await stream.read()).decode()

            if incoming not in self.seen_messages
                msg_comps = incoming.split('\n')
                msg_type = msg_comps[0]
                msg_origin = msg_comps[1]
                if msg_type == "subscription":
                    handle_subscription(incoming)
                elif msg_type == "talk":
                    handle_talk(incoming)

                # TODO: Do stuff with incoming unseen message

                # Add message to seen
                self.seen_messages.append(incoming)

                # Publish message using router's publish
                self.router.publish(msg_origin, incoming)
            # Force context switch
            asyncio.sleep(0)

    async def stream_handler(self, stream):
        # Add peer
        # Map peer to stream
        peer_id = stream.mplex_conn.peer_id
        self.peers[peer_id] = stream
        self.router.add_peer(peer_id, stream.get_protocol())

        # Send hello packet
        hello = self.get_hello_packet()
        await stream.write(hello.encode())

        # Pass stream off to stream reader
        asyncio.ensure_future(self.continously_read_stream(stream))

    async def handle_peer_queue(self):
        while True:
            peer_id = handle_peer_queue.get()

            # Open a stream to peer on existing connection
            # (we know connection exists since that's the only way
            # an element gets added to handle_peer_queue)
            stream = await self.host.new_stream(peer_id, self.protocols)

            # Add Peer
            # Map peer to stream
            self.peers[peer_id] = stream
            self.router.add_peer(peer_id, stream.get_protocol())

            # Send hello packet
            hello = self.get_hello_packet()
            await stream.write(hello.encode())

            # Pass stream off to stream reader
            asyncio.ensure_future(self.continously_read_stream(stream))

            # Force context switch
            asyncio.sleep(0)

    # This is for a subscription message incoming from a peer
    def handle_subscription(self, subscription):
        # Determine want to subscribe or unsubscribe
        msg_comps = subscription.split('\n')
        msg_origin = msg_comps[1]

        for i in range(2, len(msg_comps)):
            sub_comps = msg_comps[i].split(":")
            sub_option = sub_comps[0]
            topic_id = sub_comps[1]

            if sub_option == "sub":
                # Add peer to topic 
                if msg_origin not in self.peer_topics[topic_id]:
                    self.peer_topics[topic_id].append(msg_origin)

    def handle_talk(self, talk):
        msg_comps = talk.split('\n')
        msg_origin = msg_comps[1]
        topics = msg_comps[2].split(',')

        # Check if this message has any topics that we are subscribed to
        for topic in topics:
            if topic in self.my_topics:
                # we are subscribed to a topic this message was sent for
                self.my_topics[topic](talk)
                break

    def subscribe(self, topic_id, on_msg_received):
        # Map topic_id to handler
        self.my_topics[topic_id] = on_msg_received

        # Create subscribe message
        sub_msg = self.host.get_id() + "\nsub:" + topic_id

        # Send out subscribe message to all peers
        await message_all_peers(sub_msg)

        # Tell router we are joining this topic
        self.router.join(topic_id)

    def unsubscribe(self, topic_id):
        # Remove topic_id from map if present
        if topic_id in self.my_topics:
            del self.my_topics[topic_id]

        # Create unsubscribe message
        unsub_msg = self.host.get_id() + "\nunsub:" + topic_id
        
        # Send out unsubscribe message to all peers
        await message_all_peers(unsub_msg)

        # Tell router we are leaving this topic
        self.router.leave(topic_id)

    async def message_all_peers(self, msg):
        # Broadcast a message to all peers

        # Encode message for sending
        encoded_msg = msg.encode()

        for peer in self.peers:
            stream = self.peers[peer]

            # Send message
            await stream.write(encoded_msg)

