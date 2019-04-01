import uuid
from libp2p.pubsub.pb import rpc_pb2

def generate_message_id():
    """
    Generate a unique message id
    :return: messgae id
    """
    return str(uuid.uuid1())

def generate_RPC_packet(origin_id, topics, msg_content, msg_id):
    """
    Generate RPC packet to send over wire
    :param origin_id: peer id of the message origin
    :param topics: list of topics
    :param msg_content: string of content in data
    :param msg_id: seqno for the message
    """
    packet = rpc_pb2.RPC()
    message = rpc_pb2.Message(
        from_id=origin_id.encode('utf-8'),
        seqno=msg_id.encode('utf-8'),
        data=msg_content.encode('utf-8'),
        )

    for topic in topics:
        message.topicIDs.extend([topic.encode('utf-8')])

    packet.publish.extend([message])
    return packet
