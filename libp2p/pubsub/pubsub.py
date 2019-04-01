import asyncio
import uuid

from .pb import rpc_pb2_grpc
from .pb import rpc_pb2
from .pubsub_notifee import PubsubNotifee


class Pubsub():
    # pylint: disable=too-many-instance-attributes

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

        packet = rpc_pb2.RPC()
        message = rpc_pb2.Message(
            from_id=str(self.host.get_id()).encode('utf-8'),
            seqno=str(generate_message_id()).encode('utf-8')
            )
        packet.publish.extend([message])
        for topic_id in self.my_topics:
            packet.subscriptions.extend([rpc_pb2.RPC.SubOpts(
                subscribe=True, topicid=topic_id)])

        return packet.SerializeToString()

    async def continuously_read_stream(self, stream):
        """
        Read from input stream in an infinite loop. Process
        messages from other nodes
        :param stream: stream to continously read from
        """

        # TODO check on types here
        peer_id = str(stream.mplex_conn.peer_id)

        while True:
            incoming = (await stream.read())
            rpc_incoming = rpc_pb2.RPC()
            rpc_incoming.ParseFromString(incoming)

            print ("IN PUBSUB CONTINUOUSLY READ")
            print (rpc_incoming)
            print ("###########################")

            should_publish = True

            if rpc_incoming.publish:
                # deal with RPC.publish
                for message in rpc_incoming.publish:
                    self.seen_messages.append(message.seqno)
                    await self.handle_talk(peer_id, message)
                    

            if rpc_incoming.subscriptions:
                # deal with RPC.subscriptions
                # We don't need to relay the subscription to our
                # peers because a given node only needs its peers
                # to know that it is subscribed to the topic (doesn't
                # need everyone to know)
                should_publish = False

                # TODO check that peer_id is the same as origin_id
                from_id = str(rpc_incoming.publish[0].from_id.decode('utf-8'))
                for message in rpc_incoming.subscriptions:
                    if message.subscribe:
                        self.handle_subscription(from_id, message)

            if should_publish:
                # relay message to peers with router
                await self.router.publish(peer_id, incoming)

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

        await stream.write(hello)
        # Pass stream off to stream reader
        asyncio.ensure_future(self.continuously_read_stream(stream))

    async def handle_peer_queue(self):
        """
        Continuously read from peer queue and each time a new peer is found,
        open a stream to the peer using a supported pubsub protocol
        TODO: Handle failure for when the peer does not support any of the
        pubsub protocols we support
        """
        while True:
            print ("PUBSUB HANDLE PEER QUEUE")
            peer_id = await self.peer_queue.get()
            print (peer_id)
            print ("++++++++++++++++++++++++")

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
            await stream.write(hello)

            # Pass stream off to stream reader
            asyncio.ensure_future(self.continuously_read_stream(stream))

            # Force context switch
            await asyncio.sleep(0)

    def handle_subscription(self, peer_id, sub_message):
        """
        Handle an incoming subscription message from a peer. Update internal
        mapping to mark the peer as subscribed or unsubscribed to topics as
        defined in the subscription message
        :param origin_id: id of the peer who subscribe to the message
        :param sub_message: RPC.SubOpts
        """
        # TODO verify logic here
        if sub_message.subscribe:
            if sub_message.topicid not in self.peer_topics:
                self.peer_topics[sub_message.topicid] = [peer_id]
            elif peer_id not in self.peer_topics[sub_message.topicid]:
                # Add peer to topic
                self.peer_topics[sub_message.topicid].append(peer_id)
        else:
            # TODO: Remove peer from topic
            pass

    async def handle_talk(self, peer_id, publish_message):
        """
        Put incoming message from a peer onto my blocking queue
        :param peer_id: peer id whom forwarded this message
        :param talk: RPC.Message format
        """

        # Check if this message has any topics that we are subscribed to
        for topic in publish_message.topicIDs:
            if topic in self.my_topics:
                # we are subscribed to a topic this message was sent for,
                # so add message to the subscription output queue
                # for each topic
                await self.my_topics[topic].put(publish_message)

    async def subscribe(self, topic_id):
        """
        Subscribe ourself to a topic
        :param topic_id: topic_id to subscribe to
        """
        # Map topic_id to blocking queue
        self.my_topics[topic_id] = asyncio.Queue()

        # Create subscribe message
        packet = rpc_pb2.RPC()
        packet.publish.extend([rpc_pb2.Message(
            from_id=str(self.host.get_id()).encode('utf-8'),
            seqno=str(generate_message_id()).encode('utf-8')
            )])
        packet.subscriptions.extend([rpc_pb2.RPC.SubOpts(
            subscribe = True,
            topicid = topic_id.encode('utf-8')
            )])

        # Send out subscribe message to all peers
        await self.message_all_peers(packet.SerializeToString())

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
        packet = rpc_pb2.RPC()
        packet.publish.extend([rpc_pb2.Message(
            from_id=str(self.host.get_id()).encode('utf-8'),
            seqno=str(generate_message_id()).encode('utf-8')
            )])
        packet.subscriptions.extend([rpc_pb2.RPC.SubOpts(
            subscribe = False,
            topicid = topic_id.encode('utf-8')
            )])

        # Send out unsubscribe message to all peers
        await self.message_all_peers(packet.SerializeToString())

        # Tell router we are leaving this topic
        self.router.leave(topic_id)

    async def message_all_peers(self, rpc_msg):
        """
        Broadcast a message to peers
        :param raw_msg: raw contents of the message to broadcast
        """

        # Broadcast message
        for peer in self.peers:
            stream = self.peers[peer]

            # Write message to stream
            await stream.write(rpc_msg)

def generate_message_id():
    """
    Generate a unique message id
    :return: messgae id
    """
    return str(uuid.uuid1())
