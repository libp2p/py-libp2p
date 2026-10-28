"""
Tests for WebRTC protobuf message framing.
"""

from libp2p.transport.webrtc.pb.webrtc_pb2 import Message


class TestMessageSerialization:
    """Test protobuf Message round-trip."""

    def test_data_only_message(self):
        msg = Message(message=b"hello webrtc")
        data = msg.SerializeToString()
        parsed = Message()
        parsed.ParseFromString(data)
        assert parsed.message == b"hello webrtc"
        assert not parsed.HasField("flag")

    def test_fin_flag(self):
        msg = Message(flag=Message.FIN)
        data = msg.SerializeToString()
        parsed = Message()
        parsed.ParseFromString(data)
        assert parsed.flag == Message.FIN
        assert not parsed.HasField("message")

    def test_fin_flag_is_present_when_set(self):
        """FIN==0 must be present on wire because the field is ``optional``."""
        msg = Message(flag=Message.FIN)
        data = msg.SerializeToString()
        assert len(data) > 0, "FIN flag (value=0) must be present on wire"
        parsed = Message()
        parsed.ParseFromString(data)
        assert parsed.HasField("flag")
        assert parsed.flag == Message.FIN

    def test_stop_sending_flag(self):
        msg = Message(flag=Message.STOP_SENDING)
        data = msg.SerializeToString()
        parsed = Message()
        parsed.ParseFromString(data)
        assert parsed.flag == Message.STOP_SENDING

    def test_reset_flag(self):
        msg = Message(flag=Message.RESET)
        data = msg.SerializeToString()
        parsed = Message()
        parsed.ParseFromString(data)
        assert parsed.flag == Message.RESET

    def test_fin_ack_flag(self):
        msg = Message(flag=Message.FIN_ACK)
        data = msg.SerializeToString()
        parsed = Message()
        parsed.ParseFromString(data)
        assert parsed.flag == Message.FIN_ACK

    def test_flag_with_data(self):
        msg = Message(flag=Message.FIN, message=b"final chunk")
        data = msg.SerializeToString()
        parsed = Message()
        parsed.ParseFromString(data)
        assert parsed.flag == Message.FIN
        assert parsed.message == b"final chunk"

    def test_empty_message(self):
        msg = Message()
        data = msg.SerializeToString()
        assert len(data) == 0  # proto3 empty message serializes to zero bytes
        parsed = Message()
        parsed.ParseFromString(data)
        assert not parsed.HasField("flag")
        assert not parsed.HasField("message")

    def test_large_payload(self):
        payload = b"\x42" * 16384  # 16 KiB max message size
        msg = Message(message=payload)
        data = msg.SerializeToString()
        parsed = Message()
        parsed.ParseFromString(data)
        assert parsed.message == payload
        assert len(parsed.message) == 16384

    def test_flag_enum_values(self):
        """Verify flag enum values match the spec."""
        assert Message.FIN == 0
        assert Message.STOP_SENDING == 1
        assert Message.RESET == 2
        assert Message.FIN_ACK == 3

    def test_binary_payload(self):
        """Verify arbitrary binary data survives round-trip."""
        payload = bytes(range(256))
        msg = Message(message=payload)
        data = msg.SerializeToString()
        parsed = Message()
        parsed.ParseFromString(data)
        assert parsed.message == payload
