from enum import (
    Enum,
)

# go-mplex MaxMessageSize — reject larger frame bodies on read.
# Ref: https://github.com/libp2p/go-mplex/blob/master/multiplex.go
MAX_MESSAGE_SIZE = 1 << 20  # 1 MiB

# go-mplex BufferSize / ChunkSize — write frames are chunked at ChunkSize.
BUFFER_SIZE = 4096
CHUNK_SIZE = BUFFER_SIZE - 20  # 4076

# go-mplex ReceiveTimeout — reset the stream if the app does not consume data.
RECEIVE_TIMEOUT_SECS = 5

# go-mplex dataIn channel depth (was historically documented as 8; upstream is 1).
MPLEX_MESSAGE_CHANNEL_SIZE = 1


class HeaderTags(Enum):
    NewStream = 0
    MessageReceiver = 1
    MessageInitiator = 2
    CloseReceiver = 3
    CloseInitiator = 4
    ResetReceiver = 5
    ResetInitiator = 6
