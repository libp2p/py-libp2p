from libp2p.crypto.keys import PrivateKey
from libp2p.kad_dht.pb import kademlia_pb2 as record_pb2
from libp2p.records.utils import sign_record


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


def make_signed_put_record(
    key: bytes, value: bytes, private_key: PrivateKey
) -> record_pb2.Record:
    """
    Create a signed Record object with the specified key, value, and signature.

    The record is signed using the libp2p record signing convention:
    signature = sign("libp2p-record:" + key + value)

    This matches go-libp2p's record signing behavior for DHT PUT_VALUE.

    Args:
        key (bytes): The key for the record.
        value (bytes): The value to associate with the key in the record.
        private_key (PrivateKey): The private key to sign the record with.

    Returns:
        record_pb2.Record: A signed Record object.

    """
    record = record_pb2.Record()
    record.key = key
    record.value = value

    # Sign the record
    signature, author_public_key = sign_record(private_key, key, value)
    record.signature = signature
    record.author = author_public_key

    return record
