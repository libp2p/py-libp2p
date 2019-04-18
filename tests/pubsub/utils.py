import uuid
import struct
from libp2p.pubsub.pb import rpc_pb2


def message_id_generator(start_val):
    """
    Generate a unique message id
    :param start_val: value to start generating messages at
    :return: message id
    """
    val = start_val
    def generator():
        # Allow manipulation of val within closure
        nonlocal val

        # Increment id
        val += 1

        # Convert val to big endian
        return struct.pack('>Q', val)

    return generator

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
        seqno=msg_id,
        data=msg_content.encode('utf-8'),
        )

    for topic in topics:
        message.topicIDs.extend([topic.encode('utf-8')])

    packet.publish.extend([message])
    return packet
