from libp2p.kad_dht.pb import kademlia_pb2 as record_pb2


def make_put_record(key: bytes, value: bytes) -> record_pb2.Record:
    """
    Create a new Record object with the specified key and value.

    Args:
        key (bytes): The key for the record.
        value (bytes): The value to associate with the key in the record.

    Returns:
        record_pb2.Record: A Record object containing the provided key and value.

    """
    record = record_pb2.Record()
    record.key = key
    record.value = value
    return record
