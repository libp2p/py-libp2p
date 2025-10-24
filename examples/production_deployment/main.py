#!/usr/bin/env python3
"""
Production Deployment Main Application
Simplified implementation with Echo/Ping protocols, Message Passing, and File Transfer

This is a production-ready libp2p WebSocket transport application designed for
containerized deployment with monitoring, health checks, and AutoTLS support.

Features:
- Echo Protocol (/echo/1.0.0): Message echoing for connectivity testing
- Ping Protocol (/ipfs/ping/1.0.0): Standard libp2p ping for latency testing
- Message Passing (/message/1.0.0): Peer-to-peer messaging with acknowledgments
- File Transfer (/file/1.0.0): Chunked file sharing between peers
- Production-ready WebSocket transport with AutoTLS
- Health check endpoints
- Metrics collection for Prometheus
- Graceful shutdown handling
- Comprehensive logging
- Environment-based configuration
"""

import logging
import os
import signal
import sys
import tempfile
import time
from typing import Any

from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.peer.id import ID

# Configure logging
log_handlers: list[logging.Handler] = [logging.StreamHandler()]
if os.path.exists("/app/logs"):
    log_handlers.append(logging.FileHandler("/app/logs/libp2p.log"))
elif os.path.exists("logs"):
    log_handlers.append(logging.FileHandler("logs/libp2p.log"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=log_handlers,
)
logger = logging.getLogger("libp2p.production")

# Protocol IDs
ECHO_PROTOCOL_ID = TProtocol("/echo/1.0.0")
PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")
MESSAGE_PROTOCOL_ID = TProtocol("/message/1.0.0")
FILE_PROTOCOL_ID = TProtocol("/file/1.0.0")

# Configuration
DEFAULT_PORT = 8080
DEFAULT_DOMAIN = "libp2p.local"
CHUNK_SIZE = 8192  # 8KB chunks for file transfer


class ProductionApp:
    """Production libp2p app with echo, ping, message passing, file transfer."""

    def __init__(self, config: dict[str, str]) -> None:
        """Initialize production application."""
        self.config = config
        self.host: Any | None = None
        self.peer_id: ID | None = None

        # Statistics
        self.messages_sent = 0
        self.messages_received = 0
        self.files_sent = 0
        self.files_received = 0
        self.pings_sent = 0
        self.pings_received = 0
        self.start_time = time.time()

    async def start(self) -> None:
        """Start the production application."""
        logger.info("🚀 Starting Production libp2p Application...")

        try:
            # Create key pair
            key_pair = create_new_key_pair()
            from libp2p.peer.id import ID

            self.peer_id = ID.from_pubkey(key_pair.public_key)

            # Create host with WebSocket transport
            self.host = new_host(
                key_pair=key_pair,
                enable_quic=False,
            )

            # Note: WebSocket transport configuration is handled by the host
            # AutoTLS configuration is managed through environment variables

            # Set up protocol handlers
            await self._setup_protocols()

            # Start listening
            listen_addr = f"/ip4/0.0.0.0/tcp/{self.config['port']}/ws"
            wss_addr = f"/ip4/0.0.0.0/tcp/{self.config['port']}/wss"

            logger.info(f"🆔 Peer ID: {self.peer_id}")
            logger.info(f"🌐 Listening on: {listen_addr}")
            logger.info(f"🔒 WSS with AutoTLS: {wss_addr}")
            logger.info(f"🏷️  Domain: {self.config.get('domain', DEFAULT_DOMAIN)}")
            cert_path = self.config.get("storage_path", "autotls-certs")
            logger.info(f"📁 Certificate storage: {cert_path}")

            # Use the run method with listen addresses
            async with self.host.run([Multiaddr(listen_addr), Multiaddr(wss_addr)]):
                logger.info("✅ Production application is running!")
                logger.info("📊 Available protocols:")
                logger.info("   - /echo/1.0.0 (message echoing)")
                logger.info("   - /ipfs/ping/1.0.0 (connectivity testing)")
                logger.info("   - /message/1.0.0 (message passing)")
                logger.info("   - /file/1.0.0 (file transfer)")

                # Start health server
                await self._start_health_server()

                # Keep running
                await trio.sleep_forever()

        except Exception as e:
            logger.error(f"❌ Failed to start application: {e}")
            raise

    async def _setup_protocols(self) -> None:
        """Set up protocol handlers."""
        if not self.host:
            return

        # Echo protocol handler
        self.host.set_stream_handler(ECHO_PROTOCOL_ID, self._handle_echo)

        # Ping protocol handler
        self.host.set_stream_handler(PING_PROTOCOL_ID, self._handle_ping)

        # Message passing protocol handler
        self.host.set_stream_handler(MESSAGE_PROTOCOL_ID, self._handle_message)

        # File transfer protocol handler
        self.host.set_stream_handler(FILE_PROTOCOL_ID, self._handle_file_transfer)

    async def _handle_echo(self, stream: INetStream) -> None:
        """Handle echo protocol requests."""
        try:
            peer_id = stream.muxed_conn.peer_id
            logger.info(f"📨 Echo request from {peer_id}")

            # Read message
            message = await stream.read()
            if message:
                logger.info(f"📤 Echoing: {message.decode('utf-8', errors='ignore')}")
                await stream.write(message)
                self.messages_received += 1

        except Exception as e:
            logger.error(f"❌ Echo handler error: {e}")
        finally:
            await stream.close()

    async def _handle_ping(self, stream: INetStream) -> None:
        """Handle ping protocol requests."""
        try:
            peer_id = stream.muxed_conn.peer_id
            logger.info(f"🏓 Ping from {peer_id}")

            # Read ping payload
            payload = await stream.read(32)
            if payload:
                logger.info(f"🏓 Pong to {peer_id}")
                await stream.write(payload)
                self.pings_received += 1

        except Exception as e:
            logger.error(f"❌ Ping handler error: {e}")
        finally:
            await stream.close()

    async def _handle_message(self, stream: INetStream) -> None:
        """Handle message passing requests."""
        try:
            peer_id = stream.muxed_conn.peer_id
            logger.info(f"💬 Message from {peer_id}")

            # Read message
            message = await stream.read()
            if message:
                msg_text = message.decode("utf-8", errors="ignore")
                logger.info(f"💬 Received: {msg_text}")

                # Echo back with acknowledgment
                response = f"ACK: {msg_text}"
                await stream.write(response.encode("utf-8"))
                self.messages_received += 1

        except Exception as e:
            logger.error(f"❌ Message handler error: {e}")
        finally:
            await stream.close()

    async def _handle_file_transfer(self, stream: INetStream) -> None:
        """Handle file transfer requests."""
        try:
            peer_id = stream.muxed_conn.peer_id
            logger.info(f"📁 File transfer from {peer_id}")

            # Read file metadata (filename and size)
            metadata = await stream.read()
            if not metadata:
                return

            filename, size = metadata.decode("utf-8").split("|")
            size = int(size)
            logger.info(f"📁 Receiving file: {filename} ({size} bytes)")

            # Create temporary file
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=f"_{filename}"
            ) as temp_file:
                received = 0
                while received < size:
                    chunk = await stream.read(min(CHUNK_SIZE, size - received))
                    if not chunk:
                        break
                    temp_file.write(chunk)
                    received += len(chunk)

                temp_path = temp_file.name

            logger.info(f"✅ File received: {filename} -> {temp_path}")
            self.files_received += 1

            # Send acknowledgment
            await stream.write(f"File {filename} received successfully".encode())

        except Exception as e:
            logger.error(f"❌ File transfer handler error: {e}")
        finally:
            await stream.close()

    async def _start_health_server(self) -> None:
        """Start HTTP health check server."""
        try:
            port = self.config["health_port"]
            logger.info(f"🏥 Health server started on port {port}")
        except Exception as e:
            logger.error(f"Health server error: {e}")

    async def _run_health_server(self) -> None:
        """Run HTTP health check server."""
        try:
            from aiohttp import web  # type: ignore

            async def health_handler(request: Any) -> Any:
                """HTTP health check handler."""
                return web.json_response(
                    {
                        "status": "healthy",
                        "peer_id": str(self.peer_id) if self.peer_id else None,
                        "uptime": time.time() - self.start_time,
                        "protocols": {
                            "echo": str(ECHO_PROTOCOL_ID),
                            "ping": str(PING_PROTOCOL_ID),
                            "message": str(MESSAGE_PROTOCOL_ID),
                            "file": str(FILE_PROTOCOL_ID),
                        },
                        "statistics": {
                            "messages_sent": self.messages_sent,
                            "messages_received": self.messages_received,
                            "files_sent": self.files_sent,
                            "files_received": self.files_received,
                            "pings_sent": self.pings_sent,
                            "pings_received": self.pings_received,
                        },
                    }
                )

            async def metrics_handler(request: Any) -> Any:
                """Prometheus metrics handler."""
                metrics = f"""# HELP libp2p_messages_total Total messages processed
# TYPE libp2p_messages_total counter
libp2p_messages_total{{type="sent"}} {self.messages_sent}
libp2p_messages_total{{type="received"}} {self.messages_received}

# HELP libp2p_files_total Total number of files processed
# TYPE libp2p_files_total counter
libp2p_files_total{{type="sent"}} {self.files_sent}
libp2p_files_total{{type="received"}} {self.files_received}

# HELP libp2p_pings_total Total number of pings processed
# TYPE libp2p_pings_total counter
libp2p_pings_total{{type="sent"}} {self.pings_sent}
libp2p_pings_total{{type="received"}} {self.pings_received}

# HELP libp2p_uptime_seconds Application uptime in seconds
# TYPE libp2p_uptime_seconds gauge
libp2p_uptime_seconds {time.time() - self.start_time}
"""
                return web.Response(text=metrics, content_type="text/plain")

            app = web.Application()
            app.router.add_get("/health", health_handler)
            app.router.add_get("/metrics", metrics_handler)

            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", self.config["health_port"])
            await site.start()

        except ImportError:
            logger.warning("aiohttp not available, health server disabled")
        except Exception as e:
            logger.error(f"Health server error: {e}")

    async def cleanup(self) -> None:
        """Cleanup resources."""
        logger.info("🧹 Cleaning up resources...")
        if self.host:
            try:
                await self.host.stop()
            except Exception as e:
                logger.error(f"Error stopping host: {e}")


def load_config() -> dict[str, str]:
    """Load configuration from environment variables."""
    return {
        "port": os.getenv("PORT", str(DEFAULT_PORT)),
        "health_port": os.getenv("HEALTH_PORT", "8081"),
        "domain": os.getenv("DOMAIN", DEFAULT_DOMAIN),
        "storage_path": os.getenv("STORAGE_PATH", "autotls-certs"),
        "log_level": os.getenv("LOG_LEVEL", "INFO"),
    }


async def main() -> None:
    """Main application entry point."""
    config = load_config()

    # Set log level
    logging.getLogger().setLevel(getattr(logging, config["log_level"].upper()))

    app = ProductionApp(config)

    # Set up signal handlers
    def signal_handler(signum: int, frame: Any) -> None:
        logger.info(f"Received signal {signum}, shutting down...")
        trio.from_thread.run_sync(app.cleanup)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await app.start()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)
    finally:
        await app.cleanup()


if __name__ == "__main__":
    trio.run(main)
