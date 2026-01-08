"""
Runtime patches for aiortc to prevent premature data channel closure during handshake.

aiortc may close RTCPeerConnection and SCTP transport prematurely, causing data channels
to close before the Noise handshake can complete. This patch:

1. Intercepts RTCPeerConnection.close() to prevent closure during active handshake
2. Intercepts SCTP state transitions to prevent premature CLOSED state
3. Adds defensive checks for data channel operations during handshake

This is similar to aioice_patch.py but addresses aiortc-specific issues.
"""

from __future__ import annotations

import inspect
import logging
import sys
import traceback
from typing import Any

from aiortc import RTCDataChannel, RTCPeerConnection, RTCSctpTransport

logger = logging.getLogger("libp2p.transport.webrtc")


# Track active handshakes to prevent premature closure
_active_handshakes: set[RTCPeerConnection] = set()


def register_handshake(peer_connection: RTCPeerConnection) -> None:
    """Register a peer connection as having an active handshake."""
    if peer_connection is not None:
        _active_handshakes.add(peer_connection)
        logger.debug(f"Registered handshake for peer connection {id(peer_connection)}")


def unregister_handshake(peer_connection: RTCPeerConnection) -> None:
    """Unregister a peer connection from active handshakes."""
    if peer_connection is not None:
        _active_handshakes.discard(peer_connection)
        logger.debug(
            f"Unregistered handshake for peer connection {id(peer_connection)}"
        )


def is_handshake_active(peer_connection: RTCPeerConnection) -> bool:
    """Check if a peer connection has an active handshake."""
    return peer_connection in _active_handshakes


def _patch_peer_connection_close() -> None:
    """Patch RTCPeerConnection.close() to prevent closure during handshake."""
    if RTCPeerConnection is None:
        return

    if getattr(RTCPeerConnection, "_libp2p_close_patch", False):
        return

    original_close = RTCPeerConnection.close

    async def patched_close(self: RTCPeerConnection) -> None:
        """Patched close method that checks for active handshake."""
        # Capture FULL stack trace including aiortc internals
        try:
            # Get the full call stack with filenames and line numbers
            frame: Any = sys._getframe(1)  # Skip this frame, start from caller
            stack_lines = []
            depth = 0
            while frame and depth < 25:  # Limit depth to avoid infinite loops
                filename = frame.f_code.co_filename
                lineno = frame.f_lineno
                func_name = frame.f_code.co_name
                # Only include frames from actual source files
                # (not just '<string>' etc)
                if filename and not filename.startswith("<"):
                    stack_lines.append(
                        f'  File "{filename}", line {lineno}, in {func_name}'
                    )
                    # Try to get source line if available
                    try:
                        source_lines, start_line = inspect.getsourcelines(frame)
                        if start_line <= lineno < start_line + len(source_lines):
                            source_line = source_lines[lineno - start_line].strip()
                            if source_line:
                                stack_lines.append(f"    {source_line}")
                    except (OSError, IndexError, TypeError):
                        pass
                frame = frame.f_back if frame else None
                depth += 1
            stack_trace = "\n".join(stack_lines)
        except Exception:
            # Fallback to standard traceback if manual inspection fails
            stack_trace = "".join(traceback.format_stack())

        # Get current states for diagnostics
        conn_state = getattr(self, "connectionState", "unknown")
        ice_state = getattr(self, "iceConnectionState", "unknown")
        sctp_state = "N/A"
        try:
            if hasattr(self, "sctp") and self.sctp:
                sctp_transport = self.sctp.transport
                if hasattr(sctp_transport, "state"):
                    sctp_state = getattr(sctp_transport, "state", "N/A")
        except Exception:
            pass

        logger.error(
            f"peer_connection.close() CALLED on {id(self)} - "
            f"handshake_active={is_handshake_active(self)}, "
            f"conn_state={conn_state}, ice_state={ice_state}, sctp_state={sctp_state}\n"
            f"Stack trace:\n{stack_trace}"
        )

        if is_handshake_active(self):
            logger.warning(
                f"Attempted to close peer connection {id(self)} "
                f"during active handshake - "
                "deferring closure until handshake completes"
            )
            # Don't close immediately - let handshake complete or fail naturally
            # The handshake error handling will clean up properly
            return

        # Normal closure when no handshake is active
        await original_close(self)

    RTCPeerConnection.close = patched_close  # type: ignore[assignment]
    RTCPeerConnection._libp2p_close_patch = True  # type: ignore[attr-defined]
    logger.debug("aiortc RTCPeerConnection.close() patch installed")


def _patch_sctp_transport_state() -> bool:
    """
    Patch RTCSctpTransport._set_state() to prevent premature CLOSED state.

    Returns:
        bool: True if patch was installed successfully, False otherwise

    """
    if RTCSctpTransport is None:
        logger.warning("RTCSctpTransport is None - cannot patch SCTP")
        return False

    if getattr(RTCSctpTransport, "_libp2p_state_patch", False):
        logger.debug("RTCSctpTransport._set_state already patched")
        return True

    # Try to get the original _set_state method
    if not hasattr(RTCSctpTransport, "_set_state"):
        logger.error(
            "RTCSctpTransport._set_state not found on class! "
            "Available methods/attributes: "
            + ", ".join(
                [x for x in dir(RTCSctpTransport) if not x.startswith("__")][:20]
            )
        )
        # Try to find it via MRO (Method Resolution Order)
        try:
            for base in RTCSctpTransport.__mro__:
                if hasattr(base, "_set_state"):
                    logger.info(f"Found _set_state in base class: {base}")
                    break
        except Exception:
            pass
        return False

    original_set_state = RTCSctpTransport._set_state
    logger.debug(f"Found RTCSctpTransport._set_state: {original_set_state}")

    def patched_set_state(self: RTCSctpTransport, new_state: Any) -> None:
        """Patched _set_state that prevents CLOSED during handshake."""
        # Check if we're trying to set CLOSED state
        # RTCSctpTransport.State.CLOSED is typically an enum value
        # Handle both enum and string representations
        state_name = None
        if hasattr(new_state, "name"):
            state_name = new_state.name
        elif hasattr(new_state, "value"):
            state_name = str(new_state.value)
        else:
            state_name = str(new_state)

        current_state = getattr(self, "_state", None)
        current_state_name = None
        if current_state:
            if hasattr(current_state, "name"):
                current_state_name = current_state.name
            elif hasattr(current_state, "value"):
                current_state_name = str(current_state.value)
            else:
                current_state_name = str(current_state)
        else:
            current_state_name = str(current_state)

        # Log ALL state transitions (not just CLOSED) for debugging
        is_closed_transition = (
            state_name == "CLOSED"
            or "closed" in str(state_name).lower()
            or (
                hasattr(new_state, "value") and "closed" in str(new_state.value).lower()
            )
        )

        # Capture stack trace for CLOSED transitions
        if is_closed_transition:
            try:
                # Get the full call stack with filenames and line numbers
                frame: Any = sys._getframe(1)
                stack_lines = []
                depth = 0
                while frame and depth < 25:  # Limit depth to avoid infinite loops
                    filename = frame.f_code.co_filename
                    lineno = frame.f_lineno
                    func_name = frame.f_code.co_name
                    # Only include frames from actual source files
                    # (not just '<string>' etc)
                    if filename and not filename.startswith("<"):
                        stack_lines.append(
                            f'  File "{filename}", line {lineno}, in {func_name}'
                        )
                        # Try to get source line if available
                        try:
                            source_lines, start_line = inspect.getsourcelines(frame)
                            if start_line <= lineno < start_line + len(source_lines):
                                source_line = source_lines[lineno - start_line].strip()
                                if source_line:
                                    stack_lines.append(f"    {source_line}")
                        except (OSError, IndexError, TypeError):
                            pass
                    frame = frame.f_back if frame else None
                    depth += 1
                stack_trace = "\n".join(stack_lines)
            except Exception:
                # Fallback to standard traceback if manual inspection fails
                stack_trace = "".join(traceback.format_stack())

            # Try to find associated peer connection
            # SCTP transport has _pc attribute that links to peer connection
            peer_conn = None
            if hasattr(self, "_pc") and self._pc:
                peer_conn = self._pc

            # Get peer connection states
            if peer_conn:
                conn_state = getattr(peer_conn, "connectionState", None)
                ice_state = getattr(peer_conn, "iceConnectionState", None)
            else:
                conn_state = None
                ice_state = None

            handshake_active = is_handshake_active(peer_conn) if peer_conn else False
            peer_conn_id = id(peer_conn) if peer_conn else None
            logger.error(
                f"SCTP _set_state(CLOSED) CALLED on {id(self)} - "
                f"current_state={current_state_name}, "
                f"peer_conn={peer_conn_id}, "
                f"handshake_active={handshake_active}, "
                f"conn_state={conn_state}, ice_state={ice_state}\n"
                f"Stack trace:\n{stack_trace}"
            )

            # If we found the peer connection and it has an active handshake,
            # defer closure
            if peer_conn and is_handshake_active(peer_conn):
                logger.warning(
                    f"SCTP transport {id(self)} attempting to close "
                    f"during active handshake "
                    f"(peer connection {id(peer_conn)}) - deferring closure"
                )
                # Don't transition to CLOSED - let handshake complete or fail naturally
                return

            # Log warning if any handshakes are active
            # (even if we can't find the specific PC)
            if _active_handshakes:
                active_count = len(_active_handshakes)
                logger.warning(
                    f"SCTP transport {id(self)} closing while "
                    f"{active_count} active handshake(s) exist - "
                    "this may cause handshake failures"
                )

        # Call original method
        original_set_state(self, new_state)

    RTCSctpTransport._set_state = patched_set_state  # type: ignore[assignment]
    RTCSctpTransport._libp2p_state_patch = True  # type: ignore[attr-defined]
    logger.info("aiortc RTCSctpTransport._set_state() patch installed successfully")
    return True


def _patch_data_channel_close() -> None:
    """Patch RTCDataChannel.close() to prevent closure during handshake."""
    try:
        from aiortc import RTCDataChannel  # type: ignore
    except ImportError:
        return

    if getattr(RTCDataChannel, "_libp2p_close_patch", False):
        return

    original_close = RTCDataChannel.close

    async def patched_close(self: RTCDataChannel) -> None:
        """Patched close method that checks for active handshake."""
        # Try to find associated peer connection
        # Data channels have a _transport attribute that links to SCTP transport
        # SCTP transport links to peer connection
        peer_conn = None
        if hasattr(self, "_transport") and self._transport:
            sctp_transport = self._transport
            if hasattr(sctp_transport, "_pc") and sctp_transport._pc:
                peer_conn = sctp_transport._pc

        if peer_conn and is_handshake_active(peer_conn):
            logger.warning(
                f"Attempted to close data channel {id(self)} during active handshake - "
                "deferring closure"
            )
            return

        close_result = original_close(self)
        if close_result is not None:
            await close_result

    RTCDataChannel.close = patched_close  # type: ignore[assignment]
    RTCDataChannel._libp2p_close_patch = True  # type: ignore[attr-defined]
    logger.debug("aiortc RTCDataChannel.close() patch installed")


def install_patches() -> None:
    """Install all aiortc patches."""
    _patch_peer_connection_close()
    _patch_sctp_transport_state()
    _patch_data_channel_close()

    # Log patch installation status
    patch_status = {
        "peer_connection_close": (
            getattr(RTCPeerConnection, "_libp2p_close_patch", False)
            if RTCPeerConnection is not None
            else False
        ),
        "sctp_set_state": (
            getattr(RTCSctpTransport, "_libp2p_state_patch", False)
            if RTCSctpTransport is not None
            else False
        ),
        # Will be set by _patch_data_channel_close if it succeeds
        "data_channel_close": False,
    }
    try:
        patch_status["data_channel_close"] = getattr(
            RTCDataChannel, "_libp2p_close_patch", False
        )
    except ImportError:
        pass

    logger.info(f"aiortc patches installed: {patch_status}")

    # Warn if SCTP patch failed
    if not patch_status.get("sctp_set_state", False):
        logger.error(
            "SCTP _set_state patch FAILED to install - "
            "SCTP state transitions will NOT be intercepted! "
            "This means premature SCTP closure cannot be prevented."
        )


# Auto-install patches on import
try:
    install_patches()
except Exception as e:
    logger.warning(f"Failed to install aiortc patches: {e}")
