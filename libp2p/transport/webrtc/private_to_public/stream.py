"""
WebRTC Stream implementation for py-libp2p.
"""

from enum import Enum
import logging
import time
from types import TracebackType
from typing import TYPE_CHECKING

from aiortc import RTCDataChannel
import trio

if TYPE_CHECKING:
    from libp2p.abc import IMuxedStream
else:
    try:
        from libp2p.abc import IMuxedStream
    except Exception:

        class IMuxedStream:
            pass


import varint

from ..constants import (
    BUFFERED_AMOUNT_LOW_TIMEOUT,
    DEFAULT_READ_TIMEOUT,
    MAX_BUFFERED_AMOUNT,
    MAX_MESSAGE_SIZE,
)
from ..exception import (
    WebRTCStreamClosedError,
    WebRTCStreamError,
    WebRTCStreamStateError,
    WebRTCStreamTimeoutError,
)
from .pb.message_pb2 import Message

logger = logging.getLogger("libp2p.transport.webrtc.private_to_public.stream")


class StreamState(Enum):
    OPEN = "open"
    WRITE_CLOSED = "write_closed"
    READ_CLOSED = "read_closed"
    CLOSED = "closed"
    CONNECTING = "connecting"
    CLOSING = "closing"
    RESET = "reset"
    RECIEVE_FIN_ACK = "receive_fin_ack"


class StreamDirection(Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class StreamTimeline:
    """Track stream lifecycle events for debugging and monitoring."""

    def __init__(self) -> None:
        self.created_at = time.time()
        self.opened_at: float | None = None
        self.first_data_at: float | None = None
        self.closed_at: float | None = None
        self.reset_at: float | None = None
        self.error_code: int | None = None

    def record_open(self) -> None:
        self.opened_at = time.time()

    def record_first_data(self) -> None:
        if self.first_data_at is None:
            self.first_data_at = time.time()

    def record_close(self) -> None:
        self.closed_at = time.time()

    def record_reset(self) -> None:
        self.reset_at = time.time()


class WebRTCStream(IMuxedStream):
    """
    WebRTC Stream implementation following libp2p IMuxedStream interface.
    """

    def __init__(self, id: int, direction: StreamDirection, channel: RTCDataChannel):
        """
        Initialize WebRTC stream.

        Args:
            id: Stream identifier (int)
            direction: Stream direction (inbound/outbound)
            channel: RTCDataChannel instance

        """
        self._id = id
        self._channel = channel
        self._direction = direction

        self._state_lock = trio.Lock()

        self._timeline = StreamTimeline()
        self._timeline.record_open()
        self._state = StreamState.OPEN

        match self._channel.readyState.lower():
            case StreamState.OPEN.value.lower():
                self._state = StreamState.OPEN
            case StreamState.CLOSED.value.lower() | StreamState.CLOSING.value.lower():
                if self._timeline.closed_at is None or self._timeline.closed_at == 0:
                    self._timeline.record_close()
            case StreamState.CONNECTING.value.lower():
                # noop
                pass
            case _:
                logger.error("Unknown datachannel state %s", self._channel.readyState)
                raise WebRTCStreamStateError("Unknown datachannel state")

        # Stream-specific channels
        self.send_channel: trio.MemorySendChannel[bytes]
        self.receive_channel: trio.MemoryReceiveChannel[bytes]
        self.send_channel, self.receive_channel = trio.open_memory_channel(100)

        # Message reader buffer
        self._receive_buffer = bytearray()
        self._receive_buffer_lock = trio.Lock()
        self._receive_event = trio.Event()

        # Register handler for message listener
        self._channel.on("message", self.handle_incoming_data)

        logger.debug(f"Created WebRTC stream {id} ({direction.value})")

    @property
    def stream_id(self) -> str:
        """Get stream ID as string for libp2p compatibility."""
        return str(self._id)

    @property
    def state(self) -> StreamState:
        """Get current stream state."""
        return self._state

    @property
    def direction(self) -> StreamDirection:
        """Get stream direction."""
        return self._direction

    @property
    def is_initiator(self) -> bool:
        """Check if this stream was locally initiated."""
        return self._direction == StreamDirection.OUTBOUND

    # Core stream operations

    async def read(self, n: int | None = None) -> bytes:
        """
        Read data from the stream with RTCDataChannel flow control.

        Args:
            n: Maximum number of bytes to read. If None or -1, read all available.

        Returns:
            Data read from stream
        Raises:
            WebRTCStreamClosedError: Stream is closed
            WebRTCStreamResetError: Stream was reset
            WebRTCStreamTimeoutError: Read timeout exceeded

        """
        if n is None:
            n = -1

        async with self._state_lock:
            if self._state in (StreamState.CLOSED, StreamState.RESET):
                raise WebRTCStreamClosedError(f"Stream {self.stream_id} is closed")

        # Wait for data with timeout
        timeout = DEFAULT_READ_TIMEOUT
        try:
            with trio.move_on_after(timeout) as cancel_scope:
                while True:
                    async with self._receive_buffer_lock:
                        if self._receive_buffer:
                            data = self._extract_data_from_buffer(n)
                            return data
                    # Wait for more data
                    await self._receive_event.wait()
                    self._receive_event = trio.Event()  # Reset for next wait

                    if cancel_scope.cancelled_caught:
                        raise WebRTCStreamTimeoutError(
                            f"Read timeout on stream {self.stream_id}"
                        )
        except WebRTCStreamTimeoutError:
            raise
        except Exception as e:
            logger.error(f"Error reading from stream {self.stream_id}: {e}")
            await self._handle_stream_error(e)
            raise WebRTCStreamError(f"Error reading from stream {self.stream_id}: {e}")

    async def write(self, data: bytes, check_buffer: bool = True) -> None:
        """
        Write data to the stream with WebRTC DataChannel flow control.

        Args:
            data: Data to send
            check_buffer: Whether to check the channel's bufferedAmount before sending
        Raises:
            WebRTCStreamClosedError: Stream is closed for writing
            WebRTCStreamResetError: Stream was reset
            StreamStateError: DataChannel is not open
            TimeoutError: Timed out waiting for DataChannel buffer to clear

        """
        if not data:
            return

        async with self._state_lock:
            if self._state in (StreamState.CLOSED, StreamState.RESET):
                raise WebRTCStreamClosedError(f"Stream {self.stream_id} is closed")

        try:
            bytes_total = len(data)
            max_message_size = MAX_MESSAGE_SIZE
            offset = 0
            while offset < bytes_total:
                to_send = min(bytes_total - offset, max_message_size)
                buf = data[offset : offset + to_send]

                message_buf = Message()
                message_buf.message = buf
                encoded_msg = message_buf.SerializeToString()
                send_buf = varint.encode(len(encoded_msg)) + encoded_msg

                logger.debug(f"sending {len(buf)}/{bytes_total} bytes on channel")
                await self._send_message(send_buf, check_buffer=check_buffer)

                offset += to_send

            self._timeline.record_first_data()
            logger.debug(f"Wrote {len(data)} bytes to stream {self.stream_id}")

        except Exception as e:
            logger.error(f"Error writing to stream {self.stream_id}: {e}")
            await self._handle_stream_error(e)
            raise

    async def reset(self) -> None:
        """Reset the stream by calling the handle reset function."""
        await self.sendReset()

    # This section handles writing of message and flag to the RTCDataChannel

    async def _send_message(self, data: bytes, check_buffer: bool = True) -> None:
        # Wait for buffer to be low enough if needed
        if check_buffer and self._channel.bufferedAmount > MAX_BUFFERED_AMOUNT:
            bufferedamountlow_event = trio.Event()

            def on_bufferedamountlow() -> None:
                bufferedamountlow_event.set()

            self._channel.on("bufferedamountlow", on_bufferedamountlow)
            try:
                logger.debug(
                    f"Channel buffer:{self._channel.bufferedAmount}, "
                    'wait for "bufferedamountlow" event'
                )
                with trio.move_on_after(BUFFERED_AMOUNT_LOW_TIMEOUT) as scope:
                    while self._channel.bufferedAmount > MAX_BUFFERED_AMOUNT:
                        await bufferedamountlow_event.wait()
                        bufferedamountlow_event = trio.Event()
                if scope.cancelled_caught:
                    raise TimeoutError(
                        "Timed out waiting for DataChannel buffer"
                        "to clear after {BUFFERED_AMOUNT_LOW_TIMEOUT}s"
                    )
            finally:
                bufferedamountlow_event = trio.Event()

        try:
            logger.debug(f'Sending message, channel state "{self._channel.readyState}"')
            self._channel.send(data)
        except Exception as err:
            logger.error(f"Error while sending message: {err}")
            raise

    async def _send_flag(self, flag: "Message.Flag.ValueType") -> bool:
        """
        Send a flag message over the DataChannel, if the channel is open.

        Args:
            flag: The flag to send (should be compatible with Message.Flag)

        Returns:
            bool: True if the flag was sent, False otherwise.

        """
        if str(self._channel.readyState).lower() != StreamState.OPEN.value.lower():
            logger.debug(
                f"Not sending flag {flag} because"
                f' channel is "{self._channel.readyState}", and not "open"',
            )
            return False

        logger.debug(f"Sending flag {flag}")
        message_buf = Message()
        message_buf.flag = flag
        # Use SerializeToString() for protobuf objects
        encoded_message = message_buf.SerializeToString()
        prefixed_buf = varint.encode(len(encoded_message)) + encoded_message

        try:
            await self._send_message(prefixed_buf, check_buffer=False)
            return True
        except Exception as err:
            logger.error(f"Could not send flag {flag} - {err}")
            return False

    async def sendReset(self) -> None:
        """
        Send a RESET flag and close the channel.
        """
        try:
            await self._send_flag(Message.Flag.RESET)
        except Exception as err:
            logger.error(f"failed to send reset - {err!r}")
        finally:
            self._channel.close()

    async def sendCloseWrite(self) -> None:
        """
        Send a FIN flag to close the write side and await FIN_ACK.
        """
        if str(self._channel.readyState).lower() != StreamState.OPEN.value.lower():
            await self.close()
            return

        await self.send_channel.aclose()
        await self._send_flag(Message.Flag.FIN)

    async def sendCloseRead(self) -> None:
        """
        Send a STOP_SENDING flag to close the read side.
        """
        if str(self._channel.readyState).lower() != StreamState.OPEN.value.lower():
            return
        await self.receive_channel.aclose()
        await self._send_flag(Message.Flag.STOP_SENDING)

    # This section handles recieving of messages and flags from RTCDataChannel

    async def handle_incoming_data(self, data: bytes) -> None:
        """
        Handle data received from the WebRTC datachannel.

        Args:
            data: Received data

        """
        if self._state == StreamState.RESET:
            return

        if data:
            self.send_channel.send_nowait(data)
            self._timeline.record_first_data()

            # Notify waiting readers
            self._receive_event.set()

            logger.debug(f"Stream {self.stream_id} received {len(data)} bytes")

        else:
            async with self._state_lock:
                if self._state == StreamState.WRITE_CLOSED:
                    self._state = StreamState.CLOSED
                else:
                    self._state = StreamState.READ_CLOSED

            self._receive_event.set()

    async def process_incoming_protobuf(self, buffer: bytes) -> bytes | None:
        """
        Process an incoming protobuf message from the datachannel.

        Args:
            buffer: The received protobuf-encoded bytes
        Returns:
            The message payload (bytes)
            if this is a data message and the stream is readable,
            else None.

        """
        message = Message()
        message.ParseFromString(buffer)

        if message.flag is not None:
            logger.debug('incoming flag %s"', message.flag)

            if message.flag == Message.Flag.FIN:
                # We should expect no more data from the remote, stop reading
                await self.handle_stop_reading()
                logger.debug("sending FIN_ACK")
                try:
                    await self._send_flag(Message.Flag.FIN_ACK)
                except Exception as err:
                    logger.error("error sending FIN_ACK immediately: %s", err)
                return None
            if message.flag == Message.Flag.RESET:
                # Stop reading and writing to the stream immediately
                await self.handle_reset()
                return None
            if message.flag == Message.Flag.STOP_SENDING:
                # The remote has stopped reading
                await self.handle_stop_sending()
                return None
            if message.flag == Message.Flag.FIN_ACK:
                logger.debug("received FIN_ACK")
                await self.close()
                return None
        if message.message is not None:
            # The message is of type message
            async with self._receive_buffer_lock:
                self._receive_buffer.extend(message.message)
        else:
            raise WebRTCStreamError("Unidentified feild in protobuf")
        return None

    async def handle_stop_sending(self) -> None:
        """
        Handle STOP_SENDING frame from remote peer.
        """
        logger.debug(f"Stream {self.stream_id} handling STOP_SENDING")
        async with self._state_lock:
            if self.direction == StreamDirection.OUTBOUND:
                self._state = StreamState.CLOSED
            elif self._state == StreamState.READ_CLOSED:
                self._state = StreamState.CLOSED
            else:
                # Only write side closed
                self._state = StreamState.WRITE_CLOSED
        await self.sendCloseWrite()

    async def handle_stop_reading(self) -> None:
        """
        Handle FIN frame from remote peer.
        """
        logger.debug(f"Stream {self.stream_id} handling FIN")
        async with self._state_lock:
            if self.direction == StreamDirection.INBOUND:
                self._state = StreamState.CLOSED
            elif self._state == StreamState.WRITE_CLOSED:
                self._state = StreamState.CLOSED
            else:
                # Only write side closed
                self._state = StreamState.READ_CLOSED
        await self.sendCloseRead()

    async def handle_reset(self) -> None:
        """
        Handle stream reset from remote peer.
        """
        logger.debug(f"Stream {self.stream_id} reset by peer")

        async with self._state_lock:
            self._state = StreamState.RESET

        self._timeline.record_reset()
        self._receive_buffer = bytearray()
        self._receive_buffer_lock = trio.Lock()
        self._receive_event.set()

    def _extract_data_from_buffer(self, n: int) -> bytes:
        """Extract data from receive buffer with specified limit."""
        if n == -1:
            # Read all available data
            data = bytes(self._receive_buffer)
            self._receive_buffer.clear()
        else:
            # Read up to n bytes
            data = bytes(self._receive_buffer[:n])
            self._receive_buffer = self._receive_buffer[n:]

        return data

    async def _handle_stream_error(self, error: Exception) -> None:
        """Handle errors by resetting the stream."""
        logger.error(f"Stream {self.stream_id} error: {error}")
        await self.reset()

    def is_closed(self) -> bool:
        """Check if stream is completely closed."""
        return self._state in (StreamState.CLOSED, StreamState.RESET)

    def is_reset(self) -> bool:
        """Check if stream was reset."""
        return self._state == StreamState.RESET

    async def close(self) -> None:
        """
        Close the stream gracefully (both read and write sides).
        This implements proper close semantics where both sides
        are closed and resources are cleaned up.
        """
        async with self._state_lock:
            if self._state in (StreamState.CLOSED, StreamState.RESET):
                return

            logger.debug(f"Closing stream {self.stream_id}")

        await self.receive_channel.aclose()
        await self.send_channel.aclose()
        self._channel.close()

        # Update state and cleanup
        async with self._state_lock:
            self._state = StreamState.CLOSED

        self._timeline.record_close()
        logger.debug(f"Stream {self.stream_id} closed")

    # Abstact implementations
    async def __aenter__(self) -> "WebRTCStream":
        """Enter the async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the async context manager and close the stream."""
        print("Exiting the context and closing the stream")
        await self.close()

    def set_deadline(self, ttl: int) -> bool:
        # TODO: Implement deadline for this stream
        return True

    def get_remote_address(self) -> tuple[str, int] | None:
        """
        Get the remote address for this stream.

        WebRTC connections don't expose IP:port addresses, so this returns None.
        """
        return None

    # String representation for debugging
    def __repr__(self) -> str:
        return (
            f"WebRTCStream(id={self.stream_id}, "
            f"state={self._state.value}, "
            f"direction={self._direction.value}, "
        )

    def __str__(self) -> str:
        return f"WebRTCStream({self.stream_id})"

    @staticmethod
    def createStream(channel: RTCDataChannel, direction: str) -> "WebRTCStream":
        # Convert direction string to StreamDirection enum
        direction_enum = StreamDirection(direction)
        if channel.id is None:
            return WebRTCStream(0, direction_enum, channel)
        return WebRTCStream(channel.id, direction_enum, channel)
