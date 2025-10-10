"""
Resource limits and limiters for the resource manager.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import sys

from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID


class Direction(Enum):
    """Direction of network connections and streams."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


# Type alias for clarity
ProtocolID = TProtocol


@dataclass
class ScopeStat:
    """Statistics for a resource scope."""

    memory: int = 0
    num_streams_inbound: int = 0
    num_streams_outbound: int = 0
    num_conns_inbound: int = 0
    num_conns_outbound: int = 0
    num_fd: int = 0


@dataclass
class BaseLimit:
    """Basic implementation of resource limits."""

    streams: int = sys.maxsize
    streams_inbound: int = sys.maxsize
    streams_outbound: int = sys.maxsize
    conns: int = sys.maxsize
    conns_inbound: int = sys.maxsize
    conns_outbound: int = sys.maxsize
    fd: int = sys.maxsize
    memory: int = sys.maxsize

    def get_memory_limit(self) -> int:
        return int(self.memory)

    def get_stream_limit(self, direction: Direction) -> int:
        if direction == Direction.INBOUND:
            return int(self.streams_inbound)
        else:
            return int(self.streams_outbound)

    def get_stream_total_limit(self) -> int:
        return int(self.streams)

    def get_conn_limit(self, direction: Direction) -> int:
        if direction == Direction.INBOUND:
            return int(self.conns_inbound)
        else:
            return int(self.conns_outbound)

    def get_conn_total_limit(self) -> int:
        return int(self.conns)

    def get_fd_limit(self) -> int:
        return int(self.fd)


class FixedLimiter:
    """A limiter with fixed limits for all scopes."""

    def __init__(
        self,
        system: BaseLimit | None = None,
        transient: BaseLimit | None = None,
        service_default: BaseLimit | None = None,
        protocol_default: BaseLimit | None = None,
        peer_default: BaseLimit | None = None,
        stream_default: BaseLimit | None = None,
        conn_default: BaseLimit | None = None,
    ):
        self.system = system or BaseLimit(
            streams=16000,
            streams_inbound=8000,
            streams_outbound=8000,
            conns=1000,
            conns_inbound=800,
            conns_outbound=200,
            fd=8192,
            memory=1 << 30,  # 1GB
        )
        self.transient = transient or BaseLimit(
            streams=500,
            streams_inbound=250,
            streams_outbound=250,
            conns=50,
            conns_inbound=40,
            conns_outbound=10,
            fd=256,
            memory=32 << 20,  # 32MB
        )
        self.service_default = service_default or BaseLimit(
            streams=100,
            streams_inbound=64,
            streams_outbound=36,
            conns=50,
            conns_inbound=40,
            conns_outbound=10,
            fd=64,
            memory=16 << 20,  # 16MB
        )
        self.protocol_default = protocol_default or BaseLimit(
            streams=512,
            streams_inbound=256,
            streams_outbound=256,
            conns=100,
            conns_inbound=80,
            conns_outbound=20,
            fd=128,
            memory=16 << 20,  # 16MB
        )
        self.peer_default = peer_default or BaseLimit(
            streams=64,
            streams_inbound=32,
            streams_outbound=32,
            conns=8,
            conns_inbound=4,
            conns_outbound=4,
            fd=8,
            memory=64 << 20,  # 64MB
        )
        self.stream_default = stream_default or BaseLimit(
            memory=16 << 20,  # 16MB
        )
        self.conn_default = conn_default or BaseLimit(
            fd=1,
            memory=1 << 20,  # 1MB
        )

        # Custom limits
        self.service_limits: dict[str, BaseLimit] = {}
        self.protocol_limits: dict[TProtocol, BaseLimit] = {}
        self.peer_limits: dict[ID, BaseLimit] = {}

    def get_system_limits(self) -> BaseLimit:
        return self.system

    def get_transient_limits(self) -> BaseLimit:
        return self.transient

    def get_service_limits(self, service: str) -> BaseLimit:
        return self.service_limits.get(service, self.service_default)

    def get_protocol_limits(self, protocol: TProtocol) -> BaseLimit:
        return self.protocol_limits.get(protocol, self.protocol_default)

    def get_peer_limits(self, peer_id: ID) -> BaseLimit:
        return self.peer_limits.get(peer_id, self.peer_default)

    def get_stream_limits(self, peer_id: ID) -> BaseLimit:
        # Streams are limited by the peer limits, not just stream defaults
        return self.get_peer_limits(peer_id)

    def get_conn_limits(self) -> BaseLimit:
        return self.conn_default
