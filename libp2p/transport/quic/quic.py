import trio
import logging
import structlog
from typing import Optional, Tuple, Dict, List
from contextlib import asynccontextmanager
from datetime import datetime

from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from aioquic.quic.events import (
    QuicEvent, 
    StreamDataReceived, 
    ConnectionTerminated,
    StreamReset,
    HandshakeCompleted,
    ConnectionIdIssued,
    ConnectionIdRetired
)

from libp2p.typing import TProtocol
from libp2p.peer.id import ID as PeerID
from .errors import QuicError, QuicStreamError, QuicConnectionError, QuicProtocolError
from .metrics import QuicMetrics

# Configure structured logging
logger = structlog.get_logger()
logging.basicConfig(level=logging.INFO)

class QuicStream:
    """Enhanced QUIC stream with error handling."""
    
    def __init__(self, 
                 stream_id: int,
                 connection: 'QuicRawConnection',
                 peer_id: Optional[PeerID] = None):
        self.stream_id = stream_id
        self.connection = connection
        self.peer_id = peer_id
        self._send_channel, self._receive_channel = trio.open_memory_channel(100)
        self._closed = False
        self._reset = False
        self._error: Optional[Exception] = None
        
        logger.info(
            "stream_created",
            stream_id=stream_id,
            peer_id=str(peer_id) if peer_id else None
        )
        
    async def read(self, n: int = -1) -> bytes:
        """Read data from the stream with error handling."""
        if self._closed:
            raise QuicStreamError("Stream closed")
        if self._reset:
            raise QuicStreamError("Stream reset")
        if self._error:
            raise QuicStreamError(f"Stream error: {format_error(self._error)}")
            
        try:
            data = await self._receive_channel.receive()
            self.connection.metrics.bytes_received += len(data)
            
            logger.debug(
                "stream_data_received",
                stream_id=self.stream_id,
                bytes_count=len(data)
            )
            
            if n == -1:
                return data
            return data[:n]
        except trio.EndOfChannel:
            return b""
        except Exception as e:
            self._error = e
            logger.error(
                "stream_read_error",
                stream_id=self.stream_id,
                error=format_error(e)
            )
            raise QuicStreamError(f"Failed to read from stream: {format_error(e)}") from e
        
    async def write(self, data: bytes) -> None:
        """Write data to the stream with error handling."""
        if self._closed:
            raise QuicStreamError("Stream closed")
        if self._reset:
            raise QuicStreamError("Stream reset")
        if self._error:
            raise QuicStreamError(f"Stream error: {format_error(self._error)}")
            
        try:
            self.connection.quic_conn.send_stream_data(
                self.stream_id,
                data,
                end_stream=False
            )
            self.connection.metrics.bytes_sent += len(data)
            
            logger.debug(
                "stream_data_sent",
                stream_id=self.stream_id,
                bytes_count=len(data)
            )
            
            await self.connection.flush()
        except Exception as e:
            self._error = e
            logger.error(
                "stream_write_error",
                stream_id=self.stream_id,
                error=format_error(e)
            )
            raise QuicStreamError(f"Failed to write to stream: {format_error(e)}") from e

    @asynccontextmanager
    async def _cleanup_context(self):
        """Context manager for stream cleanup."""
        try:
            yield
        finally:
            try:
                await self._send_channel.aclose()
                await self._receive_channel.aclose()
            except Exception as e:
                logger.error(
                    "stream_cleanup_error",
                    stream_id=self.stream_id,
                    error=format_error(e)
                )
        
    async def close(self) -> None:
        """Close the stream with proper cleanup."""
        if not self._closed:
            async with self._cleanup_context():
                self._closed = True
                try:
                    self.connection.quic_conn.send_stream_data(
                        self.stream_id,
                        b"",
                        end_stream=True
                    )
                    await self.connection.flush()
                    self.connection.metrics.streams_closed += 1
                    
                    logger.info(
                        "stream_closed",
                        stream_id=self.stream_id,
                        error=format_error(self._error) if self._error else None
                    )
                except Exception as e:
                    logger.error(
                        "stream_close_error",
                        stream_id=self.stream_id,
                        error=format_error(e)
                    )
                    raise QuicStreamError(f"Failed to close stream: {format_error(e)}") from e

class QuicRawConnection:
    """Enhanced QUIC connection with error handling and monitoring."""
    
    def __init__(self, 
                 quic_conn: QuicConnection,
                 remote_addr: Tuple[str, int],
                 local_peer: Optional[PeerID] = None,
                 remote_peer: Optional[PeerID] = None):
        self.quic_conn = quic_conn
        self.remote_addr = remote_addr
        self.local_peer = local_peer
        self.remote_peer = remote_peer
        
        self._streams: Dict[int, QuicStream] = {}
        self._closed = False
        self._error: Optional[Exception] = None
        self._nursery: Optional[trio.Nursery] = None
        self.metrics = QuicMetrics()
        
        logger.info(
            "connection_created",
            remote_addr=remote_addr,
            local_peer=str(local_peer) if local_peer else None,
            remote_peer=str(remote_peer) if remote_peer else None
        )
        
    async def handle_event(self, event: QuicEvent) -> None:
        """Handle QUIC events with proper error handling."""
        try:
            if isinstance(event, StreamDataReceived):
                if event.stream_id not in self._streams:
                    self._streams[event.stream_id] = QuicStream(
                        event.stream_id,
                        self,
                        self.remote_peer
                    )
                    self.metrics.streams_opened += 1
                await self._streams[event.stream_id]._send_channel.send(event.data)
                
            elif isinstance(event, StreamReset):
                if event.stream_id in self._streams:
                    await self._streams[event.stream_id].reset()
                    
            elif isinstance(event, ConnectionTerminated):
                self._error = QuicConnectionError(
                    f"Connection terminated: {event.error_code}"
                )
                await self.close()
                
            elif isinstance(event, HandshakeCompleted):
                self.metrics.handshake_duration = (
                    datetime.now() - self.metrics.connection_start_time
                )
                logger.info(
                    "handshake_completed",
                    duration=str(self.metrics.handshake_duration)
                )
                
            elif isinstance(event, (ConnectionIdIssued, ConnectionIdRetired)):
                logger.debug(
                    "connection_id_event",
                    event_type=event.__class__.__name__,
                    connection_id=event.connection_id.hex()
                )
                
        except Exception as e:
            self.metrics.errors_count += 1
            logger.error(
                "event_handling_error",
                event_type=event.__class__.__name__,
                error=format_error(e)
            )
            raise QuicProtocolError(f"Failed to handle event: {format_error(e)}") from e

    async def _handle_events(self, task_status=trio.TASK_STATUS_IGNORED) -> None:
        """Event handling loop with error recovery."""
        task_status.started()
        while not self._closed:
            try:
                event = self.quic_conn.next_event()
                if event is None:
                    await trio.sleep(0.01)
                    continue
                    
                await self.handle_event(event)
                
            except Exception as e:
                self.metrics.errors_count += 1
                logger.error(
                    "event_loop_error",
                    error=format_error(e)
                )
                if not isinstance(e, QuicError):
                    raise QuicProtocolError(f"Event loop error: {format_error(e)}") from e
                raise

    @asynccontextmanager
    async def _connection_context(self):
        """Context manager for connection lifecycle."""
        try:
            yield
        finally:
            self.metrics.log_metrics()
            if self._nursery:
                self._nursery.cancel_scope.cancel()

    async def start(self) -> None:
        """Start the connection with proper initialization."""
        async with trio.open_nursery() as nursery:
            self._nursery = nursery
            try:
                await nursery.start(self._handle_events)
                logger.info(
                    "connection_started",
                    remote_addr=self.remote_addr
                )
            except Exception as e:
                logger.error(
                    "connection_start_error",
                    error=format_error(e)
                )
                raise QuicConnectionError(f"Failed to start connection: {format_error(e)}") from e

    async def close(self) -> None:
        """Close the connection with proper cleanup."""
        if not self._closed:
            async with self._connection_context():
                self._closed = True
                try:
                    # Close all streams
                    for stream in list(self._streams.values()):
                        await stream.close()
                    self._streams.clear()
                    
                    # Close QUIC connection
                    self.quic_conn.close()
                    await self.flush()
                    
                    logger.info(
                        "connection_closed",
                        remote_addr=self.remote_addr,
                        error=format_error(self._error) if self._error else None
                    )
                except Exception as e:
                    logger.error(
                        "connection_close_error",
                        error=format_error(e)
                    )
                    raise QuicConnectionError(f"Failed to close connection: {format_error(e)}") from e