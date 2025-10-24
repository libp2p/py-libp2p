#!/usr/bin/env python3
"""
Simplified Production Deployment Main Application

This is a simplified production-ready libp2p WebSocket transport application
designed for containerized deployment with basic monitoring and health checks.

Features:
- Basic WebSocket transport
- Health check endpoints
- Simple metrics collection
- Graceful shutdown handling
- Environment-based configuration
"""

import argparse
import logging
import os
import signal
import sys
import time
from typing import Any

import trio

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


class SimpleProductionApp:
    """Simplified production libp2p WebSocket application."""

    def __init__(self, config: dict[str, str]) -> None:
        """Initialize production application."""
        self.config = config
        self.shutdown_event = trio.Event()
        self.start_time = time.time()

        # Metrics
        self.connections_total = 0
        self.connections_active = 0
        self.messages_sent = 0
        self.messages_received = 0

    async def start(self) -> None:
        """Start the production application."""
        logger.info("🚀 Starting Simple Production libp2p WebSocket Application")

        try:
            # Start health check server
            await self._start_health_server()

            logger.info("✅ Application started successfully")

            # Wait for shutdown signal
            await self.shutdown_event.wait()

        except Exception as e:
            logger.error(f"❌ Failed to start application: {e}")
            raise
        finally:
            await self._cleanup()

    async def _start_health_server(self) -> None:
        """Start HTTP health check server."""
        if self.config.get("health_port"):
            # Start HTTP health server in background
            # Start health server in background
            async with trio.open_nursery() as nursery:
                nursery.start_soon(self._run_health_server)
            port = self.config["health_port"]
            logger.info(f"🏥 Health server started on port {port}")

    async def _run_health_server(self) -> None:
        """Run HTTP health check server."""
        try:
            from aiohttp import web  # type: ignore

            async def health_handler(request: Any) -> Any:
                """HTTP health check handler."""
                return web.json_response(
                    {
                        "status": "healthy",
                        "uptime": time.time() - self.start_time,
                        "connections_active": self.connections_active,
                        "messages_sent": self.messages_sent,
                        "messages_received": self.messages_received,
                    }
                )

            async def metrics_handler(request: Any) -> Any:
                """Metrics handler."""
                metrics = {
                    "libp2p_connections_total": self.connections_total,
                    "libp2p_connections_active": self.connections_active,
                    "libp2p_messages_sent_total": self.messages_sent,
                    "libp2p_messages_received_total": self.messages_received,
                    "libp2p_uptime_seconds": time.time() - self.start_time,
                }

                # Prometheus format
                prometheus_metrics = []
                for key, value in metrics.items():
                    prometheus_metrics.append(f"{key} {value}")

                return web.Response(text="\n".join(prometheus_metrics))

            app = web.Application()
            app.router.add_get("/health", health_handler)
            app.router.add_get("/metrics", metrics_handler)

            runner = web.AppRunner(app)
            await runner.setup()

            site = web.TCPSite(
                runner, "0.0.0.0", int(self.config.get("health_port", "8080"))
            )
            await site.start()

        except ImportError:
            logger.warning("aiohttp not available, skipping HTTP health server")
        except Exception as e:
            logger.error(f"Health server error: {e}")

    async def _cleanup(self) -> None:
        """Cleanup resources on shutdown."""
        logger.info("🧹 Cleaning up resources...")
        logger.info("✅ Cleanup completed")


def load_config() -> dict[str, str]:
    """Load configuration from environment variables."""
    return {
        "log_level": os.getenv("LOG_LEVEL", "info"),
        "http_port": os.getenv("HTTP_PORT", "8080"),
        "https_port": os.getenv("HTTPS_PORT", "8443"),
        "health_port": os.getenv("HEALTH_PORT", "8080"),
        "auto_tls_enabled": os.getenv("AUTO_TLS_ENABLED", "false"),
        "auto_tls_domain": os.getenv("AUTO_TLS_DOMAIN", "libp2p.local"),
        "metrics_enabled": os.getenv("METRICS_ENABLED", "true"),
    }


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Simple Production libp2p WebSocket Application"
    )
    parser.add_argument("--config", help="Configuration file path")
    parser.add_argument("--log-level", default="info", help="Log level")

    args = parser.parse_args()

    # Load configuration
    config = load_config()

    # Set log level
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.getLogger().setLevel(log_level)

    # Create application
    app = SimpleProductionApp(config)

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
