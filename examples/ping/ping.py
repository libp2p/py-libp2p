import argparse
import logging
import os
import struct

from cryptography.hazmat.primitives.asymmetric import (
    x25519,
)
import multiaddr
import trio

from libp2p import (
    generate_new_rsa_identity,
    new_host,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.security.noise.transport import Transport as NoiseTransport
from libp2p.stream_muxer.yamux.yamux import (
    Yamux,
    YamuxStream,
)
from libp2p.stream_muxer.yamux.yamux import PROTOCOL_ID as YAMUX_PROTOCOL_ID

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("ping_debug.log", mode="w", encoding="utf-8"),
    ],
)

# Protocol constants - must match rust-libp2p exactly
PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")
PING_LENGTH = 32
RESP_TIMEOUT = 30
MAX_FRAME_SIZE = 1024 * 1024  # 1MB max frame size


class InteropYamux(Yamux):
    """Enhanced Yamux with proper rust-libp2p interoperability"""

    def __init__(self, *args, **kwargs):
        logging.info("InteropYamux.__init__ called")
        super().__init__(*args, **kwargs)
        self.frame_count = 0
        self.debug_frames = True

    async def _read_exact_bytes(self, n):
        """Read exactly n bytes from the connection with proper error handling"""
        if n == 0:
            return b""

        if n > MAX_FRAME_SIZE:
            logging.error(f"Requested read size {n} exceeds maximum {MAX_FRAME_SIZE}")
            return None

        data = b""
        while len(data) < n:
            try:
                remaining = n - len(data)
                chunk = await self.secured_conn.read(remaining)
            except (trio.ClosedResourceError, trio.BrokenResourceError):
                logging.debug(
                    f"Connection closed while reading {n}"
                    f"bytes (got {len(data)}) for peer {self.peer_id}"
                )
                return None
            except Exception as e:
                logging.error(f"Error reading {n} bytes: {e}")
                return None

            if not chunk:
                logging.debug(
                    f"Connection closed while reading {n}"
                    f"bytes (got {len(data)}) for peer {self.peer_id}"
                )
                return None
            data += chunk
        return data

    async def handle_incoming(self):
        """Enhanced incoming frame handler with better error recovery"""
        logging.info(f"Starting Yamux for {self.peer_id}")

        consecutive_errors = 0
        max_consecutive_errors = 3

        while not self.event_shutting_down.is_set():
            try:
                # Read frame header (12 bytes)
                header_data = await self._read_exact_bytes(12)
                if header_data is None:
                    logging.debug(
                        f"Connection closed or incomplete"
                        f"header for peer {self.peer_id}"
                    )
                    break

                # Quick sanity check for protocol data leakage
                if (
                    b"/ipfs" in header_data
                    or b"multi" in header_data
                    or b"noise" in header_data
                ):
                    logging.error(
                        f"Protocol data in header position: {header_data.hex()}"
                    )
                    break

                try:
                    # Unpack header: version, type, flags, stream_id, length
                    version, msg_type, flags, stream_id, length = struct.unpack(
                        ">BBHII", header_data
                    )

                    # Validate header values strictly
                    if version != 0:
                        logging.error(f"Invalid yamux version {version}, expected 0")
                        break

                    if msg_type not in [0, 1, 2, 3]:
                        logging.error(f"Invalid message type {msg_type}, expected 0-3")
                        break

                    if length > MAX_FRAME_SIZE:
                        logging.error(f"Frame too large: {length} > {MAX_FRAME_SIZE}")
                        break

                    # Additional validation for ping frames
                    if msg_type == 2 and length != 4:
                        logging.error(
                            f"Invalid ping frame length: {length}, expected 4"
                        )
                        break

                    # Log frame details
                    logging.debug(
                        f"Received header for peer {self.peer_id}"
                        f": type={msg_type}, flags={flags},"
                        f"stream_id={stream_id}, length={length}"
                    )

                    consecutive_errors = 0  # Reset error counter on successful parse

                except struct.error as e:
                    consecutive_errors += 1
                    logging.error(
                        f"Header parse error #{consecutive_errors}"
                        f": {e}, data: {header_data.hex()}"
                    )
                    if consecutive_errors >= max_consecutive_errors:
                        logging.error("Too many consecutive header parse errors")
                        break
                    continue

                # Read payload if present
                payload = b""
                if length > 0:
                    payload = await self._read_exact_bytes(length)
                    if payload is None:
                        logging.debug(
                            f"Failed to read payload of"
                            f"{length} bytes for peer {self.peer_id}"
                        )
                        break
                    if len(payload) != length:
                        logging.error(
                            f"Payload length mismatch:"
                            f"got {len(payload)}, expected {length}"
                        )
                        break

                # Process frame by type
                if msg_type == 0:  # Data frame
                    await self._handle_data_frame(stream_id, flags, payload)

                elif msg_type == 1:  # Window update
                    await self._handle_window_update(stream_id, payload)

                elif msg_type == 2:  # Ping frame
                    await self._handle_ping_frame(stream_id, flags, payload)

                elif msg_type == 3:  # GoAway frame
                    await self._handle_goaway_frame(payload)
                    break

            except (trio.ClosedResourceError, trio.BrokenResourceError):
                logging.debug(
                    f"Connection closed during frame processing for peer {self.peer_id}"
                )
                break
            except Exception as e:
                consecutive_errors += 1
                logging.error(f"Frame processing error #{consecutive_errors}: {e}")
                if consecutive_errors >= max_consecutive_errors:
                    logging.error("Too many consecutive frame processing errors")
                    break

        await self._cleanup_on_error()

    async def _handle_data_frame(self, stream_id, flags, payload):
        """Handle data frames with proper stream lifecycle"""
        if stream_id == 0:
            logging.warning("Received data frame for stream 0 (control stream)")
            return

        # Handle SYN flag - new stream creation
        if flags & 0x1:  # SYN flag
            if stream_id in self.streams:
                logging.warning(f"SYN received for existing stream {stream_id}")
            else:
                logging.debug(
                    f"Creating new stream {stream_id} for peer {self.peer_id}"
                )
                stream = YamuxStream(self, stream_id, is_outbound=False)
                async with self.streams_lock:
                    self.streams[stream_id] = stream

                # Send the new stream to the handler
                await self.new_stream_send_channel.send(stream)
                logging.debug(f"Sent stream {stream_id} to handler")

        # Add data to stream buffer if stream exists
        if stream_id in self.streams:
            stream = self.streams[stream_id]
            if payload:
                # Add to stream's receive buffer
                async with self.streams_lock:
                    if not hasattr(stream, "_receive_buffer"):
                        stream._receive_buffer = bytearray()
                    if not hasattr(stream, "_receive_event"):
                        stream._receive_event = trio.Event()
                    stream._receive_buffer.extend(payload)
                    stream._receive_event.set()

            # Handle stream closure flags
            if flags & 0x2:  # FIN flag
                stream.recv_closed = True
                logging.debug(f"Stream {stream_id} received FIN")
            if flags & 0x4:  # RST flag
                stream.reset_received = True
                logging.debug(f"Stream {stream_id} received RST")
        else:
            if payload:
                logging.warning(f"Received data for unknown stream {stream_id}")

    async def _handle_window_update(self, stream_id, payload):
        """Handle window update frames"""
        if len(payload) != 4:
            logging.warning(f"Invalid window update payload length: {len(payload)}")
            return

        delta = struct.unpack(">I", payload)[0]
        logging.debug(f"Window update: stream={stream_id}, delta={delta}")

        async with self.streams_lock:
            if stream_id in self.streams:
                if not hasattr(self.streams[stream_id], "send_window"):
                    self.streams[stream_id].send_window = 256 * 1024  # Default window
                self.streams[stream_id].send_window += delta

    async def _handle_ping_frame(self, stream_id, flags, payload):
        """Handle ping/pong frames with proper validation"""
        if len(payload) != 4:
            logging.warning(f"Invalid ping payload length: {len(payload)} (expected 4)")
            return

        ping_value = struct.unpack(">I", payload)[0]

        if flags & 0x1:  # SYN flag - ping request
            logging.debug(
                f"Received ping request with value {ping_value} for peer {self.peer_id}"
            )
            # Send pong response (ACK flag = 0x2)
            try:
                pong_header = struct.pack(
                    ">BBHII", 0, 2, 0x2, 0, 4
                )  # Version=0, Type=2, Flags=ACK, StreamID=0, Length=4
                pong_payload = struct.pack(">I", ping_value)
                await self.secured_conn.write(pong_header + pong_payload)
                logging.debug(f"Sent pong response with value {ping_value}")
            except Exception as e:
                logging.error(f"Failed to send pong response: {e}")
        else:
            # Pong response
            logging.debug(f"Received pong response with value {ping_value}")

    async def _handle_goaway_frame(self, payload):
        """Handle GoAway frames"""
        if len(payload) != 4:
            logging.warning(f"Invalid GoAway payload length: {len(payload)}")
            return

        code = struct.unpack(">I", payload)[0]
        logging.info(f"Received GoAway frame with code {code}")
        self.event_shutting_down.set()


async def handle_ping(stream: INetStream) -> None:
    peer_id = stream.muxed_conn.peer_id
    logging.info(f"Handling ping stream from {peer_id}")

    try:
        with trio.fail_after(RESP_TIMEOUT):
            # Read initial protocol negotiation
            initial_data = await stream.read(1024)
            logging.debug(
                f"Received initial stream data from {peer_id}"
                f": {initial_data.hex()} (length={len(initial_data)})"
            )
            if initial_data == b"/ipfs/ping/1.0.0\n":
                logging.debug(
                    f"Confirmed /ipfs/ping/1.0.0 protocol negotiation from {peer_id}"
                )
            else:
                logging.warning(f"Unexpected initial data: {initial_data!r}")

            # Read ping payload
            payload = await stream.read(PING_LENGTH)
            if not payload:
                logging.info(f"Stream closed by {peer_id}")
                return
            if len(payload) != PING_LENGTH:
                logging.warning(
                    f"Unexpected payload length"
                    f" {len(payload)} from {peer_id}: {payload.hex()}"
                )
                return
            logging.info(
                f"Received ping from {peer_id}:"
                f" {payload[:8].hex()}... (length={len(payload)})"
            )
            await stream.write(payload)
            logging.info(f"Sent pong to {peer_id}: {payload[:8].hex()}...")

    except trio.TooSlowError:
        logging.warning(f"Ping timeout with {peer_id}")
    except trio.BrokenResourceError:
        logging.info(f"Connection broken with {peer_id}")
    except Exception as e:
        logging.error(f"Error handling ping from {peer_id}: {e}")
    finally:
        try:
            await stream.close()
            logging.debug(f"Closed ping stream with {peer_id}")
        except Exception:
            pass


async def send_ping(stream: INetStream) -> None:
    peer_id = stream.muxed_conn.peer_id
    try:
        payload = os.urandom(PING_LENGTH)
        logging.info(f"Sending ping to {peer_id}: {payload[:8].hex()}...")
        with trio.fail_after(RESP_TIMEOUT):
            await stream.write(payload)
            logging.debug(f"Ping sent to {peer_id}")
            response = await stream.read(PING_LENGTH)
        if not response:
            logging.error(f"No pong response from {peer_id}")
            return
        if len(response) != PING_LENGTH:
            logging.warning(
                f"Pong length mismatch: got {len(response)}, expected {PING_LENGTH}"
            )
        if response == payload:
            logging.info(f"Ping successful! Pong matches from {peer_id}")
        else:
            logging.warning(f"Pong mismatch from {peer_id}")
    except trio.TooSlowError:
        logging.error(f"Ping timeout to {peer_id}")
    except Exception as e:
        logging.error(f"Error sending ping to {peer_id}: {e}")
    finally:
        try:
            await stream.close()
        except Exception:
            pass


def create_noise_keypair():
    try:
        x25519_private_key = x25519.X25519PrivateKey.generate()

        class NoisePrivateKey:
            def __init__(self, key):
                self._key = key

            def to_bytes(self):
                return self._key.private_bytes_raw()

            def public_key(self):
                return NoisePublicKey(self._key.public_key())

            def get_public_key(self):
                return NoisePublicKey(self._key.public_key())

        class NoisePublicKey:
            def __init__(self, key):
                self._key = key

            def to_bytes(self):
                return self._key.public_bytes_raw()

        return NoisePrivateKey(x25519_private_key)
    except Exception as e:
        logging.error(f"Failed to create Noise keypair: {e}")
        return None


def info_from_p2p_addr(addr):
    """Extract peer info from multiaddr - you'll need to implement this"""
    # This is a placeholder - you need to implement the actual parsing
    # based on your libp2p implementation


async def run(port: int, destination: str) -> None:
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    try:
        key_pair = generate_new_rsa_identity()
        logging.debug("Generated RSA keypair")

        noise_privkey = create_noise_keypair()
        logging.debug("Generated Noise keypair")
    except Exception as e:
        logging.error(f"Key generation failed: {e}")
        raise

    noise_transport = NoiseTransport(key_pair, noise_privkey=noise_privkey)
    logging.debug(f"Noise transport initialized: {noise_transport}")
    sec_opt = {TProtocol("/noise"): noise_transport}
    muxer_opt = {TProtocol(YAMUX_PROTOCOL_ID): InteropYamux}

    logging.info(f"Using muxer: {muxer_opt}")

    host = new_host(key_pair=key_pair, sec_opt=sec_opt, muxer_opt=muxer_opt)

    peer_id = host.get_id().pretty()
    logging.info(f"Host peer ID: {peer_id}")

    async with host.run(listen_addrs=[listen_addr]), trio.open_nursery():
        if not destination:
            host.set_stream_handler(PING_PROTOCOL_ID, handle_ping)

            logging.info(f"Server listening on {listen_addr}")
            logging.info(f"Full address: {listen_addr}/p2p/{peer_id}")
            logging.info("Waiting for connections...")

            await trio.sleep_forever()
        else:
            maddr = multiaddr.Multiaddr(destination)
            info = info_from_p2p_addr(maddr)

            logging.info(f"Connecting to {info.peer_id}")

            try:
                with trio.fail_after(30):
                    await host.connect(info)
                    logging.info(f"Connected to {info.peer_id}")

                    await trio.sleep(2.0)

                    logging.info(f"Opening ping stream to {info.peer_id}")
                    stream = await host.new_stream(info.peer_id, [PING_PROTOCOL_ID])
                    logging.info(f"Opened ping stream to {info.peer_id}")

                    await trio.sleep(0.5)

                    await send_ping(stream)

                    logging.info("Ping completed successfully")

                    logging.info("Keeping connection alive for 5 seconds...")
                    await trio.sleep(5.0)
            except trio.TooSlowError:
                logging.error(f"Connection timeout to {info.peer_id}")
                raise
            except Exception as e:
                logging.error(f"Connection failed to {info.peer_id}: {e}")
                import traceback

                traceback.print_exc()
                raise


def main():
    parser = argparse.ArgumentParser(
        description="libp2p ping with Rust interoperability"
    )
    parser.add_argument(
        "-p", "--port", default=8000, type=int, help="Port to listen on"
    )
    parser.add_argument("-d", "--destination", type=str, help="Destination multiaddr")

    args = parser.parse_args()

    try:
        trio.run(run, args.port, args.destination)
    except KeyboardInterrupt:
        logging.info("Terminated by user")
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        raise


if __name__ == "__main__":
    main()
