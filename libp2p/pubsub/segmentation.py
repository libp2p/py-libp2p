from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Optional

from .pb import rpc_pb2

DEFAULT_SEGMENT_SIZE = 256 * 1024          # 256 KiB per segment payload
DEFAULT_MAX_MESSAGE_SIZE = 1 * 1024 * 1024  # 1 MiB — threshold for segmentation
DEFAULT_REASSEMBLY_TIMEOUT = 120.0          # seconds before an incomplete set is evicted
MAX_BUFFERED_MESSAGE_IDS = 1024             # bound total incomplete sets to prevent memory DoS


def should_segment(data_size: int, threshold: int = DEFAULT_MAX_MESSAGE_SIZE) -> bool:
    """Return True if *data_size* exceeds the segmentation threshold."""
    return data_size > threshold


def segment_message(
    message_id: bytes,
    data: bytes,
    segment_size: int = DEFAULT_SEGMENT_SIZE,
) -> list[rpc_pb2.LargeMessageSegmentationExtension]:
    """Split *data* into ``ceil(len(data) / segment_size)`` protobuf segments.

    Each segment carries the same *message_id* and *total_segments* count.
    The last segment may be smaller than *segment_size*.
    """
    if not data:
        raise ValueError("cannot segment empty data")

    total = (len(data) + segment_size - 1) // segment_size
    checksum = sha256(data).digest()
    segments: list[rpc_pb2.LargeMessageSegmentationExtension] = []

    for i in range(total):
        offset = i * segment_size
        chunk = data[offset : offset + segment_size]
        seg = rpc_pb2.LargeMessageSegmentationExtension(
            messageID=message_id,
            segmentIndex=i,
            totalSegments=total,
            payload=chunk,
            checksum=checksum,
        )
        segments.append(seg)

    return segments


def reassemble_segments(
    segments: list[rpc_pb2.LargeMessageSegmentationExtension],
) -> bytes:
    """Reassemble a list of ordered segments back into the original payload.

    Segments MUST be complete (all indices present) and sorted by
    ``segmentIndex``.  Callers are responsible for ordering.
    """
    if not segments:
        raise ValueError("no segments to reassemble")

    segments.sort(key=lambda s: s.segmentIndex)
    data = b"".join(s.payload for s in segments)

    # Checksum verification when the sender provided one.
    if segments[0].HasField("checksum"):
        expected = segments[0].checksum
        actual = sha256(data).digest()
        if expected != actual:
            raise ValueError(
                f"checksum mismatch: expected {expected.hex()}, got {actual.hex()}"
            )

    return data


@dataclass
class PendingMessage:
    """Tracks segments received so far for an incomplete message."""
    total_segments: int
    segments: dict[int, rpc_pb2.LargeMessageSegmentationExtension] = field(default_factory=dict)
    first_seen: float = field(default_factory=time.time)

    @property
    def is_complete(self) -> bool:
        return len(self.segments) == self.total_segments

    @property
    def age(self) -> float:
        return time.time() - self.first_seen


class ReassemblyBuffer:
    """Bounded, timed buffer that reassembles ``LargeMessageSegmentationExtension``
    segments into complete payloads.

    Thread-safe *only* if used from a single ``anyio`` task (which is the case
    in py-libp2p's read loop).
    """

    def __init__(
        self,
        timeout: float = DEFAULT_REASSEMBLY_TIMEOUT,
        max_pending: int = MAX_BUFFERED_MESSAGE_IDS,
        on_complete: Callable[[bytes], Awaitable[None]] | None = None,
    ) -> None:
        self._timeout = timeout
        self._max_pending = max_pending
        self._pending: dict[bytes, PendingMessage] = {}
        self._on_complete = on_complete

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def add_segment(
        self,
        seg: rpc_pb2.LargeMessageSegmentationExtension,
    ) -> bytes | None:
        """Feed a segment into the buffer.

        Returns the fully reassembled payload bytes when the set is complete,
        or ``None`` if more segments are still expected.
        """
        mid = seg.messageID
        total = seg.totalSegments
        idx = seg.segmentIndex

        if idx >= total:
            return None

        if mid not in self._pending:
            if len(self._pending) >= self._max_pending:
                self._evict_oldest()
            self._pending[mid] = PendingMessage(total_segments=total)

        pending = self._pending[mid]

        if pending.total_segments != total:
            del self._pending[mid]
            return None

        pending.segments[idx] = seg

        if pending.is_complete:
            ordered = [pending.segments[i] for i in range(total)]
            del self._pending[mid]
            try:
                data = reassemble_segments(ordered)
            except ValueError:
                return None
            if self._on_complete is not None:
                await self._on_complete(data)
            return data

        return None

    def garbage_collect(self) -> int:
        """Evict all pending sets that have exceeded the timeout.

        Returns the number of sets evicted.
        """
        now = time.time()
        expired = [
            mid
            for mid, pm in self._pending.items()
            if now - pm.first_seen > self._timeout
        ]
        for mid in expired:
            del self._pending[mid]
        return len(expired)

    def pending_count(self) -> int:
        """Return the number of incomplete message sets currently buffered."""
        return len(self._pending)

    def has_pending(self, message_id: bytes) -> bool:
        """Return True if *message_id* has an incomplete set in the buffer."""
        return message_id in self._pending

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict_oldest(self) -> None:
        """Remove the single oldest pending set (by first_seen timestamp)."""
        if not self._pending:
            return
        oldest = min(self._pending.items(), key=lambda kv: kv[1].first_seen)
        del self._pending[oldest[0]]
