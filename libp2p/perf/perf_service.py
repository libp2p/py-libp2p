"""
Perf protocol service implementation.
Spec: https://github.com/libp2p/specs/blob/master/perf/perf.md

Note:
    This service is designed for benchmarking and performance testing.
    The server accepts any uint64 value for bytes to send back, which
    is intentional to support high-volume stress testing. This service
    should only be enabled in trusted environments or test networks.

"""

from collections.abc import AsyncIterator
import logging
import struct
import time
from typing import cast

from multiaddr import Multiaddr

from libp2p.abc import IHost, INetStream, IPerf
from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID as PeerID
from libp2p.peer.peerinfo import PeerInfo

from .constants import (
    PROTOCOL_NAME,
    WRITE_BLOCK_SIZE,
)
from .types import PerfInit, PerfOutput

logger = logging.getLogger(__name__)


class PerfService(IPerf):
    """
    Implementation of the perf protocol.

    The perf protocol is used to measure transfer performance within and across
    libp2p implementations.
    """

    def __init__(self, host: IHost, init: PerfInit | None = None) -> None:
        """
        Initialize the PerfService.

        Parameters
        ----------
        host : IHost
            The libp2p host instance.
        init : PerfInit, optional
            Initialization options for the service.

        """
        init_opts: PerfInit = init if init is not None else {}

        self._host = host
        self._started = False
        self._protocol = TProtocol(init_opts.get("protocol_name", PROTOCOL_NAME))
        self._write_block_size = init_opts.get("write_block_size", WRITE_BLOCK_SIZE)

        # Pre-allocate buffer for sending data
        self._buf = bytes(self._write_block_size)

    async def start(self) -> None:
        """Start the perf service and register the protocol handler."""
        self._host.set_stream_handler(self._protocol, self._handle_message)
        self._started = True
        logger.debug("Perf service started with protocol %s", self._protocol)

    async def stop(self) -> None:
        """Stop the perf service and unregister the protocol handler."""
        # Note: py-libp2p may not have unregister, but we set the flag
        self._started = False
        logger.debug("Perf service stopped")

    def is_started(self) -> bool:
        """Check if the service is currently running."""
        return self._started

    async def _handle_message(self, stream: INetStream) -> None:
        """
        Handle incoming perf protocol messages (server side).

        Reads data from the stream, extracts the number of bytes to send back
        from the first 8 bytes, then sends that many bytes back.
        """
        if not self._started:
            logger.debug("Perf service received stream while stopped; resetting")
            try:
                await stream.reset()
            except Exception:
                logger.debug("Failed to reset stopped perf stream", exc_info=True)
            return

        try:
            # Read exactly 8 bytes for the header (handle TCP fragmentation)
            header: bytes = b""
            while len(header) < 8:
                try:
                    chunk = cast(bytes, await stream.read(8 - len(header)))  # type: ignore[redundant-cast]
                    if not chunk:
                        logger.error("Stream closed before header was fully received")
                        await stream.reset()
                        return
                    header += chunk
                except Exception:
                    logger.error("Error reading header")
                    await stream.reset()
                    return

            # Parse the big-endian unsigned 64-bit integer
            bytes_to_send_back = struct.unpack(">Q", header)[0]
            logger.debug("Received request to send back %d bytes", bytes_to_send_back)

            # Read remaining data until EOF (client closes write side)
            while True:
                try:
                    data = await stream.read(self._write_block_size)
                    if not data:
                        break
                except Exception:
                    break

            # Send back the requested number of bytes
            while bytes_to_send_back > 0:
                to_send = min(self._write_block_size, bytes_to_send_back)
                await stream.write(self._buf[:to_send])
                bytes_to_send_back -= to_send

            await stream.close()

        except Exception as e:
            logger.error("Error handling perf message: %s", e)
            await stream.reset()

    async def measure_performance(
        self,
        multiaddr: Multiaddr,
        send_bytes: int,
        recv_bytes: int,
    ) -> AsyncIterator[PerfOutput]:
        """
        Measure transfer performance to a remote peer.

        Parameters
        ----------
        multiaddr : Multiaddr
            The address of the remote peer to test against.
        send_bytes : int
            Number of bytes to upload to the remote peer.
        recv_bytes : int
            Number of bytes to request the remote peer to send back.

        Yields
        ------
        PerfOutput
            Progress reports during the transfer, with a final summary at the end.

        """
        initial_start_time = time.time()
        last_reported_time = time.time()

        # Extract peer ID from multiaddr and connect
        peer_id = PeerID.from_base58(str(multiaddr).split("/p2p/")[-1])
        peer_info = PeerInfo(peer_id, [multiaddr])

        # Connect to the peer
        await self._host.connect(peer_info)
        logger.debug(
            "Opened connection after %.3f ms",
            (time.time() - last_reported_time) * 1000,
        )
        last_reported_time = time.time()

        # Open a new stream
        stream = await self._host.new_stream(peer_id, [self._protocol])
        logger.debug(
            "Opened stream after %.3f ms",
            (time.time() - last_reported_time) * 1000,
        )
        last_reported_time = time.time()

        last_amount_of_bytes_sent = 0
        total_bytes_sent = 0
        upload_start = time.time()

        try:
            # Send the number of bytes we want to receive (as big-endian u64)
            header = struct.pack(">Q", recv_bytes)
            await stream.write(header)

            logger.debug("Sending %d bytes to %s", send_bytes, peer_id)

            # Upload phase
            bytes_remaining = send_bytes
            while bytes_remaining > 0:
                to_send = min(self._write_block_size, bytes_remaining)
                await stream.write(self._buf[:to_send])
                bytes_remaining -= to_send
                last_amount_of_bytes_sent += to_send
                total_bytes_sent += to_send

                # Yield intermediary progress every second
                if time.time() - last_reported_time > 1.0:
                    yield PerfOutput(
                        type="intermediary",
                        time_seconds=time.time() - last_reported_time,
                        upload_bytes=last_amount_of_bytes_sent,
                        download_bytes=0,
                    )
                    last_reported_time = time.time()
                    last_amount_of_bytes_sent = 0

            logger.debug(
                "Upload complete after %.3f ms", (time.time() - upload_start) * 1000
            )

            # Close the write side to signal we're done sending
            # Note: close_write() is available on NetStream
            # but not on INetStream interface
            if hasattr(stream, "close_write"):
                await stream.close_write()  # type: ignore[attr-defined]

            # Download phase
            last_amount_of_bytes_received = 0
            last_reported_time = time.time()
            total_bytes_received = 0
            download_start = time.time()

            while total_bytes_received < recv_bytes:
                try:
                    data = await stream.read(self._write_block_size)
                    if not data:
                        break

                    last_amount_of_bytes_received += len(data)
                    total_bytes_received += len(data)

                    # Yield intermediary progress every second
                    if time.time() - last_reported_time > 1.0:
                        yield PerfOutput(
                            type="intermediary",
                            time_seconds=time.time() - last_reported_time,
                            upload_bytes=0,
                            download_bytes=last_amount_of_bytes_received,
                        )
                        last_reported_time = time.time()
                        last_amount_of_bytes_received = 0
                except Exception:
                    break

            logger.debug(
                "Download complete after %.3f ms", (time.time() - download_start) * 1000
            )

            if total_bytes_received != recv_bytes:
                raise ValueError(
                    f"Expected to receive {recv_bytes} bytes, "
                    f"but received {total_bytes_received}"
                )

            # Yield final result
            yield PerfOutput(
                type="final",
                time_seconds=time.time() - initial_start_time,
                upload_bytes=total_bytes_sent,
                download_bytes=total_bytes_received,
            )

            logger.debug("Performed %s to %s", self._protocol, peer_id)

        except Exception as e:
            logger.error(
                "Error sending %d/%d bytes to %s: %s",
                total_bytes_sent,
                send_bytes,
                peer_id,
                e,
            )
            await stream.reset()
            raise
        finally:
            await stream.close()
