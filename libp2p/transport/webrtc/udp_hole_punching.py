import json
import logging
import socket
from typing import Any

import trio

logger = logging.getLogger("libp2p.transport.webrtc.direct")


class UDPHolePuncher:
    """UDP hole punching implementation for WebRTC-Direct connections."""

    def __init__(self) -> None:
        self.punch_sockets: dict[str, socket.socket] = {}
        self.local_endpoints: dict[str, tuple[str, int]] = {}

    async def punch_hole(
        self,
        target_ip: str,
        target_port: int,
        metadata: dict[str, Any],
        local_port: int = 0,
    ) -> tuple[str, int]:
        """
        Perform UDP hole punching to establish direct connection.

        Args:
            target_ip: Remote public IP address.
            target_port: Remote UDP port.
            metadata: Additional connection metadata (ufrag, peer_id, certhash, etc.).
            local_port: Optional local UDP port to bind to (0 = random).

        Returns:
            tuple[str, int]: (local_ip, local_port) that can reach the target.

        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            # Bind to local port (0 = random port)
            sock.bind(("", local_port))
            local_ip, local_port = sock.getsockname()
            # Make recv polling feasible for offer/answer over the same socket.
            sock.settimeout(0.5)

            # Best effort to discover outward-facing IP
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tmp_sock:
                    tmp_sock.connect((target_ip, target_port))
                    local_ip = tmp_sock.getsockname()[0]
            except Exception:
                local_ip = self._get_local_ip()

            payload = {
                "type": "punch",
                **metadata,
            }
            punch_data = json.dumps(payload).encode("utf-8")

            # Send multiple packets to improve success probability
            for _ in range(5):
                try:
                    await trio.to_thread.run_sync(
                        sock.sendto, punch_data, (target_ip, target_port)
                    )
                    print(
                        f"sent punch to {target_ip}:{target_port} metadata={metadata}"
                    )
                    await trio.sleep(0.1)
                except Exception as exc:
                    print(f"[puncher] send failed: {exc}")

            endpoint_key = f"{target_ip}:{target_port}"
            self.punch_sockets[endpoint_key] = sock
            self.local_endpoints[endpoint_key] = (local_ip, local_port)

            logger.info("UDP hole punched: %s -> %s", local_port, target_port)
            return local_ip, local_port

        except Exception as exc:
            sock.close()
            logger.error("UDP hole punching failed: %s", exc)
            raise

    async def send_json(
        self, target_ip: str, target_port: int, payload: dict[str, Any]
    ) -> None:
        endpoint_key = f"{target_ip}:{target_port}"
        sock = self.punch_sockets.get(endpoint_key)
        if sock is None:
            # Best-effort: create an ephemeral socket if punch_hole wasn't called.
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("", 0))
            sock.settimeout(0.5)
            self.punch_sockets[endpoint_key] = sock
            self.local_endpoints[endpoint_key] = sock.getsockname()

        data = json.dumps(payload).encode("utf-8")
        await trio.to_thread.run_sync(sock.sendto, data, (target_ip, target_port))

    async def recv_json(
        self, target_ip: str, target_port: int, *, timeout_s: float
    ) -> dict[str, Any] | None:
        endpoint_key = f"{target_ip}:{target_port}"
        sock = self.punch_sockets.get(endpoint_key)
        if sock is None:
            return None

        with trio.move_on_after(timeout_s) as scope:
            while True:
                try:
                    data, _addr = await trio.to_thread.run_sync(sock.recvfrom, 65535)
                except TimeoutError:
                    if scope.cancelled_caught:
                        return None
                    continue
                except Exception:
                    return None
                try:
                    return json.loads(data.decode("utf-8"))
                except Exception:
                    # Ignore non-JSON packets.
                    continue
        return None

    def _get_local_ip(self) -> str:
        """Discover the local IP address used for outbound traffic."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tmp_sock:
                tmp_sock.connect(("8.8.8.8", 80))
                return tmp_sock.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def cleanup_socket(self, target_ip: str, target_port: int) -> None:
        """Clean up resources associated with the given remote endpoint."""
        endpoint_key = f"{target_ip}:{target_port}"
        sock = self.punch_sockets.pop(endpoint_key, None)
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

        self.local_endpoints.pop(endpoint_key, None)
