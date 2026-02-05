from dataclasses import dataclass
from enum import Enum
import json


class MessageType(Enum):
    """Message types for WebRTC signaling protocol."""

    SDP_OFFER = 0
    SDP_ANSWER = 1
    ICE_CANDIDATE = 2


@dataclass
class SignalingMessage:
    """
    WebRTC signaling message structure.
    """

    message_type: MessageType
    data: str

    def to_bytes(self) -> bytes:
        """Serialize message to bytes."""
        message_dict = {"type": self.message_type.value, "data": self.data}
        return json.dumps(message_dict).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> "SignalingMessage":
        """Deserialize message from bytes."""
        message_dict = json.loads(data.decode("utf-8"))
        return cls(
            message_type=MessageType(message_dict["type"]), data=message_dict["data"]
        )

    def __repr__(self) -> str:
        return (
            f"SignalingMessage(type={self.message_type.name}, "
            f"data_length={len(self.data)})"
        )


@dataclass
class SDPOffer:
    """SDP offer message."""

    sdp: str

    def to_signaling_message(self) -> SignalingMessage:
        return SignalingMessage(MessageType.SDP_OFFER, self.sdp)


@dataclass
class SDPAnswer:
    """SDP answer message."""

    sdp: str

    def to_signaling_message(self) -> SignalingMessage:
        return SignalingMessage(MessageType.SDP_ANSWER, self.sdp)


@dataclass
class ICECandidate:
    """ICE candidate message."""

    candidate: str | None

    def to_signaling_message(self) -> SignalingMessage:
        # Handle null candidate (end-of-candidates)
        data = json.dumps({"candidate": self.candidate}) if self.candidate else "null"
        return SignalingMessage(MessageType.ICE_CANDIDATE, data)

    @classmethod
    def from_signaling_message(cls, msg: SignalingMessage) -> "ICECandidate":
        """Create ICE candidate from signaling message."""
        if msg.data == "null":
            return cls(candidate=None)

        data = json.loads(msg.data)
        return cls(candidate=data.get("candidate"))


def create_sdp_offer(sdp: str) -> SignalingMessage:
    """Create SDP offer signaling message."""
    return SDPOffer(sdp).to_signaling_message()


def create_sdp_answer(sdp: str) -> SignalingMessage:
    """Create SDP answer signaling message."""
    return SDPAnswer(sdp).to_signaling_message()


def create_ice_candidate(candidate: str | None) -> SignalingMessage:
    """Create ICE candidate signaling message."""
    return ICECandidate(candidate).to_signaling_message()
