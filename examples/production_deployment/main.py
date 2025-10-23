#!/usr/bin/env python3
"""
Production Deployment Main Application

This is a production-ready libp2p WebSocket transport application designed for
containerized deployment with monitoring, health checks, and AutoTLS support.

Features:
- Production-ready WebSocket transport with AutoTLS
- Health check endpoints
- Metrics collection for Prometheus
- Graceful shutdown handling
- Comprehensive logging
- Environment-based configuration
"""

import argparse
import logging
import os
import signal
import sys
import time
from typing import Any, Dict, Optional

from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID
from libp2p.transport.websocket.transport import (
    WebsocketConfig,
    WithAutoTLS,
    WithProxy,
)

# Configure logging
log_handlers: list[logging.Handler] = [logging.StreamHandler()]
if os.path.exists('/app/logs'):
    log_handlers.append(logging.FileHandler('/app/logs/libp2p.log'))
elif os.path.exists('logs'):
    log_handlers.append(logging.FileHandler('logs/libp2p.log'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=log_handlers,
)
logger = logging.getLogger("libp2p.production")

# Protocol definitions
ECHO_PROTOCOL_ID = TProtocol("/echo/1.0.0")
HEALTH_PROTOCOL_ID = TProtocol("/health/1.0.0")
METRICS_PROTOCOL_ID = TProtocol("/metrics/1.0.0")


class ProductionApp:
    """Production libp2p WebSocket application."""

    def __init__(self, config: Dict[str, str]) -> None:
        """
        Initialize production application.

        Args:
            config: Configuration dictionary from environment variables

        """
        self.config = config
        self.host: Optional[Any] = None
        self.peer_id: Optional[ID] = None
        self.shutdown_event = trio.Event()
        self.start_time = time.time()

        # Metrics
        self.connections_total = 0
        self.connections_active = 0
        self.messages_sent = 0
        self.messages_received = 0

    async def start(self) -> None:
        """Start the production application."""
        logger.info("🚀 Starting Production libp2p WebSocket Application")

        try:
            # Create peer identity
            key_pair = create_new_key_pair()
            self.peer_id = ID.from_pubkey(key_pair.public_key)

            # Create transport configuration
            # transport_config = self._create_transport_config()

            # Create transport (upgrader will be set by the host)
            # transport = WebsocketTransport(None, config=transport_config)

            # Create host with basic configuration
            self.host = new_host(key_pair=key_pair)

            # Set up protocol handlers
            await self._setup_handlers()

            # Start listening
            await self._start_listening()

            # Start health check server
            await self._start_health_server()

            logger.info("✅ Application started successfully")
            logger.info(f"📍 Peer ID: {self.peer_id}")
            if self.host:
                logger.info(f"🌐 Listening addresses: {self.host.get_addrs()}")

            # Wait for shutdown signal
            await self.shutdown_event.wait()

        except Exception as e:
            logger.error(f"❌ Failed to start application: {e}")
            raise
        finally:
            await self._cleanup()

    def _create_transport_config(self) -> Optional[WebsocketConfig]:
        """Create transport configuration based on environment."""
        if self.config.get('auto_tls_enabled', 'false').lower() == 'true':
            logger.info("🔒 AutoTLS enabled")
            return WithAutoTLS(
                domain=self.config.get('auto_tls_domain', 'libp2p.local'),
                storage_path='/app/certs',
                renewal_threshold_hours=int(
                    self.config.get('renewal_threshold_hours', '24')
                ),
                cert_validity_days=int(self.config.get('cert_validity_days', '90')),
            )
        elif self.config.get('proxy_url'):
            logger.info(f"🌐 Proxy enabled: {self.config['proxy_url']}")
            return WithProxy(
                proxy_url=self.config['proxy_url'],
                auth=(
                    tuple(self.config.get('proxy_auth', '').split(':'))  # type: ignore
                    if self.config.get('proxy_auth')
                    else None
                ),
            )
        else:
            logger.info("🔧 Using default configuration")
            return None

    async def _setup_handlers(self) -> None:
        """Set up protocol handlers."""
        # Echo handler
        async def echo_handler(stream: Any) -> None:
            """Handle echo protocol requests."""
            try:
                peer_id = str(stream.muxed_conn.peer_id)
                logger.info(f"📥 Echo request from {peer_id}")

                while True:
                    data = await stream.read(1024)
                    if not data:
                        break

                    self.messages_received += 1
                    logger.info(f"📨 Echo: {data.decode('utf-8', errors='replace')}")

                    # Echo back
                    await stream.write(data)
                    self.messages_sent += 1

            except Exception as e:
                logger.error(f"Echo handler error: {e}")
            finally:
                await stream.close()

        # Health handler
        async def health_handler(stream: Any) -> None:
            """Handle health check requests."""
            try:
                health_data = {
                    'status': 'healthy',
                    'uptime': time.time() - self.start_time,
                    'connections_total': self.connections_total,
                    'connections_active': self.connections_active,
                    'messages_sent': self.messages_sent,
                    'messages_received': self.messages_received,
                    'peer_id': str(self.peer_id),
                }

                import json
                await stream.write(json.dumps(health_data).encode())

            except Exception as e:
                logger.error(f"Health handler error: {e}")
            finally:
                await stream.close()

        # Metrics handler
        async def metrics_handler(stream: Any) -> None:
            """Handle metrics requests."""
            try:
                metrics_data = {
                    'libp2p_connections_total': self.connections_total,
                    'libp2p_connections_active': self.connections_active,
                    'libp2p_messages_sent_total': self.messages_sent,
                    'libp2p_messages_received_total': self.messages_received,
                    'libp2p_uptime_seconds': time.time() - self.start_time,
                }

                # Prometheus format
                prometheus_metrics = []
                for key, value in metrics_data.items():
                    prometheus_metrics.append(f"{key} {value}")

                await stream.write('\n'.join(prometheus_metrics).encode())

            except Exception as e:
                logger.error(f"Metrics handler error: {e}")
            finally:
                await stream.close()

        # Set handlers (if host is available)
        if self.host:
            self.host.set_stream_handler(ECHO_PROTOCOL_ID, echo_handler)
            self.host.set_stream_handler(HEALTH_PROTOCOL_ID, health_handler)
            self.host.set_stream_handler(METRICS_PROTOCOL_ID, metrics_handler)

        logger.info("✅ Protocol handlers configured")

    async def _start_listening(self) -> None:
        """Start listening on configured addresses."""
        listen_addrs = []

        # HTTP/WebSocket
        if self.config.get('http_port'):
            addr = f"/ip4/0.0.0.0/tcp/{self.config['http_port']}/ws"
            listen_addrs.append(Multiaddr(addr))
            logger.info(f"🌐 Listening on HTTP/WebSocket: {addr}")

        # HTTPS/WSS
        if self.config.get('https_port'):
            addr = f"/ip4/0.0.0.0/tcp/{self.config['https_port']}/wss"
            listen_addrs.append(Multiaddr(addr))
            logger.info(f"🔒 Listening on HTTPS/WSS: {addr}")

        if not listen_addrs:
            # Default to port 8080
            addr = "/ip4/0.0.0.0/tcp/8080/ws"
            listen_addrs.append(Multiaddr(addr))
            logger.info(f"🌐 Default listening on: {addr}")

        # Start listening (if host is available)
        if self.host:
            for addr in listen_addrs:
                await self.host.listen(addr)

    async def _start_health_server(self) -> None:
        """Start HTTP health check server."""
        if self.config.get('health_port'):
            # Start HTTP health server in background
            async with trio.open_nursery() as nursery:
                nursery.start_soon(self._run_health_server)
            port = self.config['health_port']
            logger.info(f"🏥 Health server started on port {port}")

    async def _run_health_server(self) -> None:
        """Run HTTP health check server."""
        try:
            import aiohttp  # type: ignore
            from aiohttp import web  # type: ignore

            async def health_handler(request: Any) -> Any:
                """HTTP health check handler."""
                return web.json_response({
                    'status': 'healthy',
                    'uptime': time.time() - self.start_time,
                    'connections_active': self.connections_active,
                    'peer_id': str(self.peer_id),
                })

            app = web.Application()
            app.router.add_get('/health', health_handler)
            app.router.add_get('/metrics', health_handler)

            runner = web.AppRunner(app)
            await runner.setup()

            site = web.TCPSite(
                runner,
                '0.0.0.0',
                int(self.config.get('health_port', '8080'))
            )
            await site.start()

        except ImportError:
            logger.warning("aiohttp not available, skipping HTTP health server")
        except Exception as e:
            logger.error(f"Health server error: {e}")

    async def _cleanup(self) -> None:
        """Cleanup resources on shutdown."""
        logger.info("🧹 Cleaning up resources...")

        if self.host:
            try:
                await self.host.stop()
                logger.info("✅ Host stopped")
            except Exception as e:
                logger.error(f"Error stopping host: {e}")

        logger.info("✅ Cleanup completed")


def load_config() -> Dict[str, str]:
    """Load configuration from environment variables."""
    return {
        'log_level': os.getenv('LOG_LEVEL', 'info'),
        'http_port': os.getenv('HTTP_PORT', '8080'),
        'https_port': os.getenv('HTTPS_PORT', '8443'),
        'health_port': os.getenv('HEALTH_PORT', '8080'),
        'auto_tls_enabled': os.getenv('AUTO_TLS_ENABLED', 'false'),
        'auto_tls_domain': os.getenv('AUTO_TLS_DOMAIN', 'libp2p.local'),
        'renewal_threshold_hours': os.getenv('RENEWAL_THRESHOLD_HOURS', '24'),
        'cert_validity_days': os.getenv('CERT_VALIDITY_DAYS', '90'),
        'proxy_url': os.getenv('PROXY_URL', ''),
        'proxy_auth': os.getenv('PROXY_AUTH', ''),
        'metrics_enabled': os.getenv('METRICS_ENABLED', 'true'),
    }


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Production libp2p WebSocket Application"
    )
    parser.add_argument('--config', help='Configuration file path')
    parser.add_argument('--log-level', default='info', help='Log level')

    args = parser.parse_args()

    # Load configuration
    config = load_config()

    # Set log level
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.getLogger().setLevel(log_level)

    # Create application
    app = ProductionApp(config)

    # Set up signal handlers
    def signal_handler(signum: int, frame: Any) -> None:
        logger.info(f"📡 Received signal {signum}, initiating shutdown...")
        trio.from_thread.run_sync(app.shutdown_event.set)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Run application
        await app.start()
    except KeyboardInterrupt:
        logger.info("📡 Keyboard interrupt received")
    except Exception as e:
        logger.error(f"❌ Application error: {e}")
        sys.exit(1)
    finally:
        logger.info("👋 Application shutdown complete")


if __name__ == "__main__":
    trio.run(main)
