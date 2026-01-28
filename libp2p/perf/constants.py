# Protocol constants for the perf protocol
# https://github.com/libp2p/specs/blob/master/perf/perf.md

PROTOCOL_NAME = "/perf/1.0.0"
WRITE_BLOCK_SIZE = 64 << 10  # 64KB (65536 bytes)
MAX_INBOUND_STREAMS = 1
MAX_OUTBOUND_STREAMS = 1
RUN_ON_LIMITED_CONNECTION = False
