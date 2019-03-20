import asyncio
from .PubsubNotifee import PubsubNotifee
from .message import MessageTalk, MessageSub
from .message import create_message_talk, create_message_sub
from. message import generate_message_id

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
msg_sender_peer_id
origin_peer_id
sub:topic1
sub:topic2
unsub:fav_topic
talk format:
talk
'from'
'origin'
[topic_ids comma-delimited]
'data'
Ex.
talk
msg_sender_peer_id
origin_peer_id
topic1,topics_are_cool,foo
I like tacos
"""

class Pubsub():

    def __init__(self, host, router, my_id):
        """
        Construct a new Pubsub object, which is responsible for handling all
        Pubsub-related messages and relaying messages as appropriate to the
        Pubsub router (which is responsible for choosing who to send messages to).
        Since the logic for choosing peers to send pubsub messages to is
        in the router, the same Pubsub impl can back floodsub, gossipsub, etc.
        """
        self.host = host
        self.router = router
        self.my_id = my_id

        # Attach this new Pubsub object to the router
        self.router.attach(self)

        # Register a notifee
        self.peer_queue = asyncio.Queue()
        self.host.get_network().notify(PubsubNotifee(self.peer_queue))

        # Register stream handlers for each pubsub router protocol to handle
        # the pubsub streams opened on those protocols
        self.protocols = self.router.get_protocols()
        for protocol in self.protocols:
            self.host.set_stream_handler(protocol, self.stream_handler)

        # TODO: determine if these need to be asyncio queues, or if could possibly
        # be ordinary blocking queues
        self.incoming_msgs_from_peers = asyncio.Queue()
        self.outgoing_messages = asyncio.Queue()

        # TODO: Make seen_messages a cache (LRU cache?)
        self.seen_messages = []

        # Map of topics we are subscribed to to handler functions
        # for when the given topic receives a message
        self.my_topics = {}

        # Map of topic to peers to keep track of what peers are subscribed to
        self.peer_topics = {}

        # Create peers map, which maps peer_id (as string) to stream (to a given peer)
        self.peers = {}

        # Call handle peer to keep waiting for updates to peer queue
        asyncio.ensure_future(self.handle_peer_queue())

    def get_hello_packet(self):
        """
        Generate subscription message with all topics we are subscribed to
        """
        subs_map = {}
        for topic in self.my_topics:
            subs_map[topic] = True
        sub_msg = MessageSub(str(self.host.get_id()), str(self.host.get_id()), subs_map, generate_message_id())
        return sub_msg.to_str()

    async def continously_read_stream(self, stream):
        """
        Read from input stream in an infinite loop. Process
        messages from other nodes, which for now are considered MessageTalk
        and MessageSub messages.
        TODO: Handle RPC messages instead of my Aspyn's own custom message format
        :param stream: stream to continously read from
        """
        while True:
            incoming = (await stream.read()).decode()
            msg_comps = incoming.split('\n')
            msg_type = msg_comps[0]

            msg_sender = msg_comps[1]
            msg_origin = msg_comps[2]
            msg_id = msg_comps[3]
            print("HIT ME1")
            if msg_id not in self.seen_messages:
                print("HIT ME")
                # Do stuff with incoming unseen message
                should_publish = True
                if msg_type == "subscription":
                    self.handle_subscription(incoming)

                    # We don't need to relay the subscription to our
                    # peers because a given node only needs its peers
                    # to know that it is subscribed to the topic (doesn't
                    # need everyone to know)
                    should_publish = False
                elif msg_type == "talk":
                    await self.handle_talk(incoming)

                # Add message id to seen
                self.seen_messages.append(msg_id)

                # Publish message using router's publish
                if should_publish:
                    msg = create_message_talk(incoming)

                    # Adjust raw_msg to that the message sender
                    # is now our peer_id
                    msg.from_id = str(self.host.get_id())

                    await self.router.publish(msg_sender, msg.to_str())
            
            # Force context switch
            await asyncio.sleep(0)

    async def stream_handler(self, stream):
        """
        Stream handler for pubsub. Gets invoked whenever a new stream is created
        on one of the supported pubsub protocols.
        :param stream: newly created stream
        """
        # Add peer
        # Map peer to stream
        peer_id = stream.mplex_conn.peer_id
        self.peers[str(peer_id)] = stream
        self.router.add_peer(peer_id, stream.get_protocol())

        # Send hello packet
        hello = self.get_hello_packet()
        await stream.write(hello.encode())
        # Pass stream off to stream reader
        asyncio.ensure_future(self.continously_read_stream(stream))

    async def handle_peer_queue(self):
        """
        Continuously read from peer queue and each time a new peer is found,
        open a stream to the peer using a supported pubsub protocol
        TODO: Handle failure for when the peer does not support any of the
        pubsub protocols we support
        """
        while True:
            peer_id = await self.peer_queue.get()

            # Open a stream to peer on existing connection
            # (we know connection exists since that's the only way
            # an element gets added to peer_queue)
            stream = await self.host.new_stream(peer_id, self.protocols)

            # Add Peer
            # Map peer to stream
            self.peers[str(peer_id)] = stream
            self.router.add_peer(peer_id, stream.get_protocol())

            # Send hello packet
            hello = self.get_hello_packet()
            await stream.write(hello.encode())

            # Pass stream off to stream reader
            asyncio.ensure_future(self.continously_read_stream(stream))

            # Force context switch
            await asyncio.sleep(0)

    def handle_subscription(self, subscription):
        """
        Handle an incoming subscription message from a peer. Update internal
        mapping to mark the peer as subscribed or unsubscribed to topics as
        defined in the subscription message
        :param subscription: raw data constituting a subscription message
        """
        sub_msg = create_message_sub(subscription)
        if len(sub_msg.subs_map) > 0:
            print("handle_subscription my_id: " + self.my_id + ", subber: " + sub_msg.origin_id)
        for topic_id in sub_msg.subs_map:
            # Look at each subscription in the msg individually
            if sub_msg.subs_map[topic_id]:
                if topic_id not in self.peer_topics:
                    # Create topic list if it did not yet exist
                    self.peer_topics[topic_id] = [sub_msg.origin_id]
                elif sub_msg.origin_id not in self.peer_topics[topic_id]:
                    # Add peer to topic 
                    self.peer_topics[topic_id].append(sub_msg.origin_id)
            else:
                # TODO: Remove peer from topic
                pass

    async def handle_talk(self, talk):
        """
        Handle incoming Talk message from a peer. A Talk message contains some 
        custom message that is published on a given topic(s)
        :param talk: raw data constituting a talk message
        """
        msg = create_message_talk(talk)

        # Check if this message has any topics that we are subscribed to
        for topic in msg.topics:
            if topic in self.my_topics:
                # we are subscribed to a topic this message was sent for,
                # so add message to the subscription output queue 
                # for each topic
                await self.my_topics[topic].put(talk)

    async def subscribe(self, topic_id):
        """
        Subscribe ourself to a topic
        :param topic_id: topic_id to subscribe to
        """
        # Map topic_id to blocking queue
        self.my_topics[topic_id] = asyncio.Queue()

        # Create subscribe message
        sub_msg = MessageSub(str(self.host.get_id()),  
            str(self.host.get_id()), {topic_id: True}, generate_message_id())

        # Send out subscribe message to all peers
        await self.message_all_peers(sub_msg.to_str())

        # Tell router we are joining this topic
        self.router.join(topic_id)

        # Return the asyncio queue for messages on this topic
        return self.my_topics[topic_id]

    async def unsubscribe(self, topic_id):
        """
        Unsubscribe ourself from a topic
        :param topic_id: topic_id to unsubscribe from
        """

        # Remove topic_id from map if present
        if topic_id in self.my_topics:
            del self.my_topics[topic_id]

        # Create unsubscribe message
        unsub_msg = MessageSub(str(self.host.get_id()), str(self.host.get_id()), \
            {topic_id: False}, generate_message_id())
        
        # Send out unsubscribe message to all peers
        await self.message_all_peers(unsub_msg.to_str())

        # Tell router we are leaving this topic
        self.router.leave(topic_id)

    async def message_all_peers(self, raw_msg):
        """
        Broadcast a message to peers
        :param raw_msg: raw contents of the message to broadcast
        """

        # Encode message for sending
        encoded_msg = raw_msg.encode()

        # Broadcast message
        for peer in self.peers:
            stream = self.peers[peer]

            # Write message to stream
            await stream.write(encoded_msg)