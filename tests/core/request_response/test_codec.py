from libp2p.request_response import BytesCodec, JSONCodec


def test_bytes_codec_round_trip() -> None:
    codec = BytesCodec()
    payload = b"hello"

    assert codec.encode_request(payload) == payload
    assert codec.decode_request(payload) == payload
    assert codec.encode_response(payload) == payload
    assert codec.decode_response(payload) == payload


def test_json_codec_round_trip() -> None:
    codec = JSONCodec()
    payload = {"msg": "hello", "count": 3}

    encoded = codec.encode_request(payload)

    assert codec.decode_request(encoded) == payload
    assert codec.decode_response(codec.encode_response(payload)) == payload
