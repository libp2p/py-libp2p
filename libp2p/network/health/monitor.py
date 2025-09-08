"""
Connection Health Monitor Service for Python libp2p.

This module provides the ConnectionHealthMonitor service that performs
proactive health monitoring, automatic connection replacement, and
connection lifecycle management.
"""

import logging
from typing import TYPE_CHECKING, Any

import trio

from libp2p.abc import INetConn
from libp2p.peer.id import ID
from libp2p.tools.async_service import Service

if TYPE_CHECKING:
    from libp2p.network.swarm import Swarm

logger = logging.getLogger("libp2p.network.health.monitor")


class ConnectionHealthMonitor(Service):
    """
    Service for monitoring connection health and performing automatic replacements.
    """

    def __init__(self, swarm: "Swarm"):
        """
        Initialize the health monitor.

        Parameters
        ----------
        swarm : Swarm
            The swarm instance to monitor.

        """
        super().__init__()
        self.swarm = swarm
        self.config = swarm.connection_config
        self._monitoring_task_started = trio.Event()
        self._stop_monitoring = trio.Event()

    async def run(self) -> None:
        """Start the health monitoring service."""
        logger.info("Starting ConnectionHealthMonitor service")

        # Only run if health monitoring is enabled
        if not self._is_health_monitoring_enabled():
            logger.debug("Health monitoring disabled, skipping monitor service")
            return

        try:
            # Start the periodic monitoring task
            async with trio.open_nursery() as nursery:
                nursery.start_soon(self._monitor_connections_task)
                self._monitoring_task_started.set()

                # Wait until cancelled
                await trio.sleep_forever()

        except trio.Cancelled:
            logger.info("ConnectionHealthMonitor service cancelled")
            self._stop_monitoring.set()
            raise

    async def _monitor_connections_task(self) -> None:
        """Main monitoring loop that runs periodic health checks."""
        logger.info(
            f"Health monitoring started with "
            f"{self.config.health_check_interval}s interval"
        )

        try:
            while True:
                # Wait for either the check interval or stop signal
                with trio.move_on_after(self.config.health_check_interval):
                    await self._stop_monitoring.wait()
                    break  # Stop signal received

                # Perform health checks on all connections
                await self._check_all_connections()

        except trio.Cancelled:
            logger.info("Health monitoring task cancelled")
            raise
        except Exception as e:
            logger.error(f"Health monitoring task error: {e}", exc_info=True)
            raise

    async def _check_all_connections(self) -> None:
        """Check health of all connections across all peers."""
        try:
            # Get snapshot of current connections to avoid modification during iteration
            current_connections = self.swarm.connections.copy()

            for peer_id, connections in current_connections.items():
                if not connections:
                    continue

                # Check each connection to this peer
                for conn in list(connections):  # Copy list to avoid modification issues
                    try:
                        await self._check_connection_health(peer_id, conn)
                    except Exception as e:
                        logger.error(f"Error checking connection to {peer_id}: {e}")

        except Exception as e:
            logger.error(f"Error in connection health check cycle: {e}")

    async def _check_connection_health(self, peer_id: ID, conn: INetConn) -> None:
        """Check health of a specific connection."""
        try:
            # Ensure health tracking is initialized
            if not self._has_health_data(peer_id, conn):
                self.swarm.initialize_connection_health(peer_id, conn)
                return

            # Measure ping latency
            start_time = trio.current_time()
            ping_success = await self._ping_connection(conn)
            latency_ms = (trio.current_time() - start_time) * 1000

            # Update health metrics
            health = self.swarm.health_data[peer_id][conn]
            health.update_ping_metrics(latency_ms, ping_success)
            health.update_stream_metrics(len(conn.get_streams()))

            # Log health status periodically
            if ping_success:
                logger.debug(
                    f"Health check for {peer_id}: latency={latency_ms:.1f}ms, "
                    f"score={health.health_score:.2f}, "
                    f"success_rate={health.ping_success_rate:.2f}"
                )
            else:
                logger.warning(
                    f"Health check failed for {peer_id}: "
                    f"score={health.health_score:.2f}, "
                    f"success_rate={health.ping_success_rate:.2f}"
                )

            # Check if connection needs replacement
            if self._should_replace_connection(peer_id, conn):
                await self._replace_unhealthy_connection(peer_id, conn)

        except Exception as e:
            logger.error(f"Error checking health for connection to {peer_id}: {e}")
            # Record the error in health data if available
            if self._has_health_data(peer_id, conn):
                health = self.swarm.health_data[peer_id][conn]
                health.add_error(f"Health check error: {e}")

    async def _ping_connection(self, conn: INetConn) -> bool:
        """
        Ping a connection to measure responsiveness.

        Uses a simple stream creation test as a health check.
        In a production implementation, this could use a dedicated ping protocol.
        """
        try:
            # Use a timeout for the ping
            with trio.move_on_after(self.config.ping_timeout):
                # Simple health check: try to create and immediately close a stream
                stream = await conn.new_stream()
                await stream.close()
                return True

        except Exception as e:
            logger.debug(f"Ping failed for connection: {e}")

        return False

    def _should_replace_connection(self, peer_id: ID, conn: INetConn) -> bool:
        """Determine if a connection should be replaced based on health metrics."""
        if not self._has_health_data(peer_id, conn):
            return False

        health = self.swarm.health_data[peer_id][conn]
        config = self.config

        # Check various health thresholds
        unhealthy_reasons = []

        if health.health_score < config.min_health_threshold:
            unhealthy_reasons.append(f"low_health_score={health.health_score:.2f}")

        if health.ping_latency > config.max_ping_latency:
            unhealthy_reasons.append(f"high_latency={health.ping_latency:.1f}ms")

        if health.ping_success_rate < config.min_ping_success_rate:
            unhealthy_reasons.append(f"low_success_rate={health.ping_success_rate:.2f}")

        if health.failed_streams > config.max_failed_streams:
            unhealthy_reasons.append(f"too_many_failed_streams={health.failed_streams}")

        if unhealthy_reasons:
            logger.info(
                f"Connection to {peer_id} marked for replacement: "
                f"{', '.join(unhealthy_reasons)}"
            )
            return True

        return False

    async def _replace_unhealthy_connection(
        self, peer_id: ID, old_conn: INetConn
    ) -> None:
        """Replace an unhealthy connection with a new one."""
        try:
            logger.info(f"Replacing unhealthy connection for peer {peer_id}")

            # Check if we have enough connections remaining
            current_connections = self.swarm.connections.get(peer_id, [])
            remaining_after_removal = len(current_connections) - 1

            # Only remove if we have more than the minimum required
            if remaining_after_removal < self.config.min_connections_per_peer:
                logger.warning(
                    f"Not replacing connection to {peer_id}: would go below minimum "
                    f"({remaining_after_removal} < "
                    f"{self.config.min_connections_per_peer})"
                )
                return

            # Clean up health tracking first
            self.swarm.cleanup_connection_health(peer_id, old_conn)

            # Remove from active connections
            if (
                peer_id in self.swarm.connections
                and old_conn in self.swarm.connections[peer_id]
            ):
                self.swarm.connections[peer_id].remove(old_conn)

            # Close the unhealthy connection
            try:
                await old_conn.close()
            except Exception as e:
                logger.debug(f"Error closing unhealthy connection: {e}")

            # Try to establish a new connection to maintain connectivity
            try:
                # Get peer info for dialing
                peer_info = self.swarm.peerstore.peer_info(peer_id)
                if peer_info and peer_info.addrs:
                    logger.info(f"Attempting to dial new connection to {peer_id}")
                    new_conn = await self.swarm.dial_peer(peer_id)
                    if new_conn:
                        logger.info(
                            f"Successfully established replacement connection to "
                            f"{peer_id}"
                        )
                    else:
                        logger.warning(
                            f"Failed to establish replacement connection to {peer_id}"
                        )
                else:
                    logger.warning(
                        f"No addresses available for {peer_id}, "
                        f"cannot establish replacement"
                    )

            except Exception as e:
                logger.error(
                    f"Error establishing replacement connection to {peer_id}: {e}"
                )

        except Exception as e:
            logger.error(f"Error replacing connection to {peer_id}: {e}")

    def _is_health_monitoring_enabled(self) -> bool:
        """Check if health monitoring is enabled."""
        return self.swarm._is_health_monitoring_enabled()

    def _has_health_data(self, peer_id: ID, conn: INetConn) -> bool:
        """Check if health data exists for a connection."""
        return (
            hasattr(self.swarm, "health_data")
            and peer_id in self.swarm.health_data
            and conn in self.swarm.health_data[peer_id]
        )

    async def get_monitoring_status(self) -> dict[str, Any]:
        """Get current monitoring status and statistics."""
        if not self._is_health_monitoring_enabled():
            return {"enabled": False}

        total_connections = sum(len(conns) for conns in self.swarm.connections.values())
        monitored_connections = sum(
            len(health_data) for health_data in self.swarm.health_data.values()
        )

        return {
            "enabled": True,
            "monitoring_task_started": self._monitoring_task_started.is_set(),
            "check_interval_seconds": self.config.health_check_interval,
            "total_connections": total_connections,
            "monitored_connections": monitored_connections,
            "total_peers": len(self.swarm.connections),
            "monitored_peers": len(self.swarm.health_data),
        }
