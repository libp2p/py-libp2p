from typing import (
    NamedTuple,
)


class StreamID(NamedTuple):
    channel_id: int
    is_initiator: bool
