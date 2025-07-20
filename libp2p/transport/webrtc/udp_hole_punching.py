import logging
import socket

import trio

logger = logging.getLogger("libp2p.transport.webrtc.direct")


class UDPHolePuncher:
    """UDP hole punching implementation for WebRTC-Direct connections"""

    def __init__(self) -> None:
        self.punch_sockets: dict[str, socket.socket] = {}
        self.local_endpoints: dict[str, tuple[str, int]] = {}

    async def punch_hole(
        self, target_ip: str, target_port: int, local_port: int = 0
    ) -> tuple[str, int]:
        """
        Perform UDP hole punching to establish direct connection.

        Returns: (local_ip, local_port) that can reach the target
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)

        try:
            # Bind to local port (0 = random port)
            sock.bind(("", local_port))
            local_ip, local_port = sock.getsockname()

            # Get local IP by connecting to target (doesn't actually send data)
            try:
                sock.connect((target_ip, target_port))
                local_ip = sock.getsockname()[0]
            except Exception:
                # Fallback to getting local IP
                local_ip = self._get_local_ip()

            # Send hole punching packets
            punch_data = b"WEBRTC_PUNCH"
            for _ in range(5):  # Send multiple packets to increase success rate
                try:
                    await trio.to_thread.run_sync(
                        sock.sendto, punch_data, (target_ip, target_port)
                    )
                    await trio.sleep(0.1)
                except Exception as e:
                    logger.debug(f"Hole punch packet failed: {e}")
            # Store socket for later use
            endpoint_key = f"{target_ip}:{target_port}"
            self.punch_sockets[endpoint_key] = sock
            self.local_endpoints[endpoint_key] = (local_ip, local_port)

            logger.info(f"UDP hole punched: {local_port} -> {target_port}")
            return local_ip, local_port

        except Exception as e:
            sock.close()
            logger.error(f"UDP hole punching failed: {e}")
            raise

    def _get_local_ip(self) -> str:
        """Get local IP address"""
        try:
            # Connect to a remote address to determine local IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def cleanup_socket(self, target_ip: str, target_port: int) -> None:
        """Clean up hole punching socket"""
        endpoint_key = f"{target_ip}:{target_port}"
        if endpoint_key in self.punch_sockets:
            try:
                self.punch_sockets[endpoint_key].close()
            except Exception:
                pass
            del self.punch_sockets[endpoint_key]

        if endpoint_key in self.local_endpoints:
            del self.local_endpoints[endpoint_key]
