from collections.abc import Awaitable, Callable
import logging
from typing import (
    Any,
    AsyncContextManager,
    TypeVar,
)

from aiortc import (
    RTCConfiguration,
    RTCDataChannel,
    RTCIceCandidate,
    RTCPeerConnection,
    RTCSessionDescription,
)
from trio_asyncio import (
    aio_as_trio,
    open_loop,
)

logger = logging.getLogger("libp2p.transport.webrtc.async_bridge")

T = TypeVar("T")


class WebRTCAsyncBridge:
    """
    Robust async bridge for WebRTC operations in trio context.
    Handles the complexities of trio-asyncio integration with proper
    error handling and context management.
    """

    def __init__(self) -> None:
        self._loop_context: AsyncContextManager[Any] | None = None
        self._in_context = False

    async def __aenter__(self) -> "WebRTCAsyncBridge":
        """Enter async context manager"""
        if not self._in_context:
            self._loop_context = open_loop()
            if self._loop_context:
                await self._loop_context.__aenter__()
            self._in_context = True
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context manager"""
        if self._in_context and self._loop_context is not None:
            await self._loop_context.__aexit__(exc_type, exc_val, exc_tb)
            self._in_context = False
            self._loop_context = None

    async def create_peer_connection(
        self, config: RTCConfiguration
    ) -> RTCPeerConnection:
        """Create RTCPeerConnection with proper async bridging"""
        try:
            peer_connection = RTCPeerConnection(config)
            logger.debug("Successfully created RTCPeerConnection")
            return peer_connection
        except Exception as e:
            logger.error(f"Failed to create RTCPeerConnection: {e}")
            raise

    async def create_data_channel(
        self, peer_connection: RTCPeerConnection, label: str
    ) -> RTCDataChannel:
        """Create data channel with proper async bridging"""
        try:
            data_channel = peer_connection.createDataChannel(label)
            logger.debug(f"Successfully created data channel: {label}")
            return data_channel
        except Exception as e:
            logger.error(f"Failed to create data channel: {e}")
            raise

    async def create_offer(
        self, peer_connection: RTCPeerConnection
    ) -> RTCSessionDescription:
        """Create SDP offer with proper async bridging"""
        try:
            offer = await aio_as_trio(peer_connection.createOffer())
            logger.debug("Successfully created SDP offer")
            return offer
        except Exception as e:
            logger.error(f"Failed to create offer: {e}")
            raise

    async def create_answer(
        self, peer_connection: RTCPeerConnection
    ) -> RTCSessionDescription:
        """Create SDP answer with proper async bridging"""
        try:
            answer = await aio_as_trio(peer_connection.createAnswer())
            logger.debug("Successfully created SDP answer")
            return answer
        except Exception as e:
            logger.error(f"Failed to create answer: {e}")
            raise

    async def set_local_description(
        self, peer_connection: RTCPeerConnection, description: RTCSessionDescription
    ) -> None:
        """Set local description with proper async bridging"""
        try:
            await aio_as_trio(peer_connection.setLocalDescription(description))
            logger.debug("Successfully set local description")
        except Exception as e:
            logger.error(f"Failed to set local description: {e}")
            raise

    async def set_remote_description(
        self, peer_connection: RTCPeerConnection, description: RTCSessionDescription
    ) -> None:
        """Set remote description with proper async bridging"""
        try:
            await aio_as_trio(peer_connection.setRemoteDescription(description))
            logger.debug("Successfully set remote description")
        except Exception as e:
            logger.error(f"Failed to set remote description: {e}")
            raise

    async def add_ice_candidate(
        self, peer_connection: RTCPeerConnection, candidate: RTCIceCandidate | None
    ) -> None:
        """Add ICE candidate with proper async bridging"""
        try:
            await aio_as_trio(peer_connection.addIceCandidate(candidate))
            logger.debug("Successfully added ICE candidate")
        except Exception as e:
            logger.error(f"Failed to add ICE candidate: {e}")
            raise

    async def close_peer_connection(self, peer_connection: RTCPeerConnection) -> None:
        """Close peer connection with proper async bridging"""
        try:
            await aio_as_trio(peer_connection.close())
            logger.debug("Successfully closed peer connection")
        except RuntimeError as e:
            # Handle closed event loop gracefully
            if "closed" in str(e).lower() or "no running event loop" in str(e).lower():
                logger.debug(
                    "Event loop closed during peer connection cleanup (non-critical)"
                )
                return
            raise
        except Exception as e:
            # Only log as error if it's not a closed loop issue
            error_str = str(e).lower()
            if "closed" not in error_str and "no running event loop" not in error_str:
                logger.error(f"Failed to close peer connection: {e}")
            else:
                logger.debug(f"Event loop issue during cleanup (non-critical): {e}")
            raise

    async def close_data_channel(self, data_channel: RTCDataChannel) -> None:
        """Close data channel with proper async bridging"""
        try:
            await aio_as_trio(data_channel.close)
            logger.debug("Successfully closed data channel")
        except RuntimeError as e:
            # Handle closed event loop gracefully
            if "closed" in str(e).lower() or "no running event loop" in str(e).lower():
                logger.debug(
                    "Event loop closed during data channel cleanup (non-critical)"
                )
                return
            raise
        except Exception as e:
            # Only log as error if it's not a closed loop issue
            error_str = str(e).lower()
            if "closed" not in error_str and "no running event loop" not in error_str:
                logger.error(f"Failed to close data channel: {e}")
            else:
                logger.debug(f"Event loop issue during cleanup (non-critical): {e}")
            raise

    async def send_data(self, data_channel: RTCDataChannel, data: bytes) -> None:
        """Send data through channel with proper async bridging"""
        try:
            # data_channel.send is a synchronous function, no need to await
            # await aio_as_trio(data_channel.send)(data)
            data_channel.send(data)

            logger.debug(f"Successfully sent {len(data)} bytes")
        except Exception as e:
            logger.error(f"Failed to send data: {e}")
            raise


# Global bridge instance for convenience
_global_bridge: WebRTCAsyncBridge | None = None


def get_webrtc_bridge() -> WebRTCAsyncBridge:
    """Get a global WebRTC async bridge instance"""
    global _global_bridge
    if _global_bridge is None:
        _global_bridge = WebRTCAsyncBridge()
    return _global_bridge


async def with_webrtc_context(
    func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any
) -> T:
    """
    Execute a function within a WebRTC async context.

    This ensures proper trio-asyncio integration for any WebRTC operations.
    """
    bridge = get_webrtc_bridge()
    async with bridge:
        return await func(*args, **kwargs)


class TrioSafeWebRTCOperations:
    """
    Simplified WebRTC operations that are safe to use in trio context.

    This class provides high-level operations that handle all the
    trio-asyncio complexity internally.
    """

    @staticmethod
    def _get_bridge() -> WebRTCAsyncBridge:
        """Get a bridge instance for safe WebRTC operations"""
        return get_webrtc_bridge()

    @staticmethod
    async def create_peer_conn_with_data_channel(
        config: RTCConfiguration, channel_label: str = "libp2p-webrtc"
    ) -> tuple[RTCPeerConnection, RTCDataChannel]:
        """Create peer connection and data channel in one operation"""
        bridge = get_webrtc_bridge()
        async with bridge:
            peer_connection = await bridge.create_peer_connection(config)
            data_channel = await bridge.create_data_channel(
                peer_connection, channel_label
            )
            return peer_connection, data_channel

    @staticmethod
    async def complete_sdp_exchange(
        initiator_pc: RTCPeerConnection, responder_pc: RTCPeerConnection
    ) -> tuple[RTCSessionDescription, RTCSessionDescription]:
        """Complete SDP offer/answer exchange"""
        bridge = get_webrtc_bridge()
        async with bridge:
            # Create and set offer
            offer = await bridge.create_offer(initiator_pc)
            await bridge.set_local_description(initiator_pc, offer)
            await bridge.set_remote_description(responder_pc, offer)

            # Create and set answer
            answer = await bridge.create_answer(responder_pc)
            await bridge.set_local_description(responder_pc, answer)
            await bridge.set_remote_description(initiator_pc, answer)

            return offer, answer

    @staticmethod
    async def cleanup_webrtc_resources(*resources: Any) -> None:
        """Clean up WebRTC resources safely"""
        bridge = get_webrtc_bridge()
        try:
            async with bridge:
                for resource in resources:
                    try:
                        if hasattr(resource, "close"):
                            if isinstance(resource, RTCPeerConnection):
                                await bridge.close_peer_connection(resource)
                            elif isinstance(resource, RTCDataChannel):
                                await bridge.close_data_channel(resource)
                            else:
                                await aio_as_trio(resource.close())
                    except Exception as e:
                        logger.warning(
                            f"Error cleaning up resource {type(resource)}: {e}"
                        )
        except RuntimeError as e:
            # Event loop might be closed - this is acceptable during cleanup
            if (
                "closed" not in str(e).lower()
                and "no running event loop" not in str(e).lower()
            ):
                raise
            logger.debug("Event loop closed during cleanup (non-critical)")
        except Exception as e:
            logger.warning(f"Error during WebRTC resource cleanup: {e}")
