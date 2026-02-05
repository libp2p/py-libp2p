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
# Track active upgrades (Noise complete, muxer negotiation in progress)
_active_upgrades: set[RTCPeerConnection] = set()


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


def register_upgrade(peer_connection: RTCPeerConnection) -> None:
    """Register a peer connection as having an active libp2p upgrade in progress."""
    if peer_connection is not None:
        _active_upgrades.add(peer_connection)
        logger.debug(f"Registered upgrade for peer connection {id(peer_connection)}")


def unregister_upgrade(peer_connection: RTCPeerConnection) -> None:
    """Unregister a peer connection from active upgrades."""
    if peer_connection is not None:
        _active_upgrades.discard(peer_connection)
        logger.debug(f"Unregistered upgrade for peer connection {id(peer_connection)}")


def is_upgrade_active(peer_connection: RTCPeerConnection) -> bool:
    """Check if a peer connection has an active libp2p upgrade in progress."""
    return peer_connection in _active_upgrades


def is_upgrade_active_on_peer(peer_connection: RTCPeerConnection) -> bool:
    """
    Check if upgrade is active on this peer connection.

    This checks both the global set and the per-connection flag.
    """
    if peer_connection is None:
        return False

    # Check global set (for backward compatibility)
    if peer_connection in _active_upgrades:
        return True

    # Check per-connection flag
    if hasattr(peer_connection, "_upgrade_active"):
        return getattr(peer_connection, "_upgrade_active", False)

    return False


def get_libp2p_owner_ready_event(peer_connection: RTCPeerConnection) -> Any | None:
    """
    Get the libp2p ownership event from peer connection.

    The event is set ONLY after:
    1. muxer negotiation finished
    2. Noise session established
    3. swarm.add_conn(conn) returned successfully

    Returns the trio.Event if found, None otherwise.
    """
    if peer_connection is None:
        return None

    # Check if event is stored directly on peer connection
    if hasattr(peer_connection, "_libp2p_owner_ready_event"):
        return getattr(peer_connection, "_libp2p_owner_ready_event", None)

    # Traverse secure_conn->conn->read_writer->libp2p_owner_ready is complex;
    # we store the event on peer_connection instead.
    return None


def get_dtls_state(peer_connection: RTCPeerConnection) -> str | None:
    """
    Get DTLS transport state from RTCPeerConnection.

    Returns:
        str | None: DTLS state ('new', 'connecting', 'connected', 'closed', 'failed')
        or None if unavailable

    """
    try:
        # DTLS transport is accessed via peer_connection.dtls.transport.state
        if hasattr(peer_connection, "dtls") and peer_connection.dtls:
            dtls_obj = peer_connection.dtls
            # DTLS object has a transport attribute
            if hasattr(dtls_obj, "transport"):
                dtls_transport = dtls_obj.transport
                if hasattr(dtls_transport, "state"):
                    state = getattr(dtls_transport, "state", None)
                    if state is not None:
                        # Handle both enum and string states
                        if hasattr(state, "name"):
                            return state.name.lower()
                        elif hasattr(state, "value"):
                            return str(state.value).lower()
                        return str(state).lower()
            # Fallback: check if dtls object itself has state
            elif hasattr(dtls_obj, "state"):
                state = getattr(dtls_obj, "state", None)
                if state is not None:
                    if hasattr(state, "name"):
                        return state.name.lower()
                    elif hasattr(state, "value"):
                        return str(state.value).lower()
                    return str(state).lower()

        # Alternative: access via SCTP transport's underlying transport
        # SCTP transport uses DTLS as its underlying transport
        if hasattr(peer_connection, "sctp") and peer_connection.sctp:
            sctp_transport = peer_connection.sctp
            if hasattr(sctp_transport, "transport"):
                underlying_transport = sctp_transport.transport
                # The underlying transport is the DTLS transport
                if hasattr(underlying_transport, "state"):
                    state = getattr(underlying_transport, "state", None)
                    if state is not None:
                        if hasattr(state, "name"):
                            return state.name.lower()
                        elif hasattr(state, "value"):
                            return str(state.value).lower()
                        return str(state).lower()
    except Exception as e:
        logger.debug(f"Error getting DTLS state: {e}")

    return None


def get_sctp_state(peer_connection: RTCPeerConnection) -> str | None:
    """
    Get SCTP transport state from RTCPeerConnection.

    Returns:
        str | None: SCTP state ('new', 'connecting', 'connected', 'closed')
        or None if unavailable

    """
    try:
        if hasattr(peer_connection, "sctp") and peer_connection.sctp:
            sctp_transport = peer_connection.sctp
            if hasattr(sctp_transport, "state"):
                state = getattr(sctp_transport, "state", None)
                if state is not None:
                    # Handle both enum and string states
                    if hasattr(state, "name"):
                        return state.name.lower()
                    elif hasattr(state, "value"):
                        return str(state.value).lower()
                    return str(state).lower()
    except Exception as e:
        logger.debug(f"Error getting SCTP state: {e}")

    return None


def is_dtls_connected(peer_connection: RTCPeerConnection) -> bool:
    """
    Check if DTLS transport is connected.

    Returns:
        bool: True if DTLS is connected, False otherwise

    """
    dtls_state = get_dtls_state(peer_connection)
    return dtls_state == "connected"


def is_sctp_connected(peer_connection: RTCPeerConnection) -> bool:
    """
    Check if SCTP transport is connected (not closed).

    Returns:
        bool: True if SCTP is connected, False if closed or unavailable

    """
    sctp_state = get_sctp_state(peer_connection)
    if sctp_state is None:
        return False
    # SCTP is connected if state is "connected" and not "closed"
    return sctp_state == "connected"


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

        # Block closure if handshake/upgrade active or libp2p owns it.
        handshake_active = is_handshake_active(self)
        upgrade_active = is_upgrade_active(self)
        owner_ready_event = get_libp2p_owner_ready_event(self)

        # Block if handshake is active
        if handshake_active:
            logger.warning(
                "peer_connection.close() BLOCKED %s - handshake active; "
                "conn=%s ice=%s sctp=%s",
                id(self),
                conn_state,
                ice_state,
                sctp_state,
            )
            return

        if upgrade_active:
            logger.warning(
                "peer_connection.close() BLOCKED %s - upgrade active; "
                "conn=%s ice=%s sctp=%s",
                id(self),
                conn_state,
                ice_state,
                sctp_state,
            )
            return

        if owner_ready_event is not None and owner_ready_event.is_set():
            logger.warning(
                "peer_connection.close() BLOCKED %s - libp2p owns; "
                "conn=%s ice=%s sctp=%s",
                id(self),
                conn_state,
                ice_state,
                sctp_state,
            )
            return

        owner_set = owner_ready_event.is_set() if owner_ready_event else False
        logger.debug(
            "peer_connection.close() CALLED %s handshake=%s upgrade=%s "
            "owner_set=%s conn=%s ice=%s sctp=%s\nStack:\n%s",
            id(self),
            handshake_active,
            upgrade_active,
            owner_set,
            conn_state,
            ice_state,
            sctp_state,
            stack_trace,
        )

        # Normal closure - ownership not transferred or event doesn't exist
        await original_close(self)

    RTCPeerConnection.close = patched_close  # type: ignore[assignment]
    RTCPeerConnection._libp2p_close_patch = True  # type: ignore[attr-defined]
    logger.debug("aiortc RTCPeerConnection.close() patch installed")


def _find_peer_connection_from_dtls(dtls_transport: Any) -> RTCPeerConnection | None:
    """
    Find the RTCPeerConnection associated with a DTLS transport.

    Tries multiple methods to find the peer connection:
    1. Check if DTLS transport has _pc attribute
    2. Search through active handshakes to find matching DTLS transport
    """
    # Method 1: Check if DTLS transport has direct reference
    try:
        if hasattr(dtls_transport, "_pc") and dtls_transport._pc:
            return dtls_transport._pc
        if (
            hasattr(dtls_transport, "peer_connection")
            and dtls_transport.peer_connection
        ):
            return dtls_transport.peer_connection
    except Exception:
        pass

    # Method 2: Search through active handshakes
    # DTLS transport is accessed via peer_connection.dtls.transport
    for peer_conn in _active_handshakes:
        try:
            if hasattr(peer_conn, "dtls") and peer_conn.dtls:
                dtls_obj = peer_conn.dtls
                # Check if dtls_obj.transport matches
                if (
                    hasattr(dtls_obj, "transport")
                    and dtls_obj.transport is dtls_transport
                ):
                    return peer_conn
                # Or check if dtls_obj itself is the transport
                if dtls_obj is dtls_transport:
                    return peer_conn
        except Exception:
            continue

    return None


def _patch_dtls_transport_state() -> bool:
    """
    Patch DTLS transport state transitions to
    prevent premature closure during handshake.

    Similar to SCTP patch, this prevents DTLS from closing
    when handshake is active.
    """
    try:
        from aiortc.rtcdtlstransport import RTCDtlsTransport
    except ImportError:
        logger.debug("RTCDtlsTransport not available for patching")
        return False

    if getattr(RTCDtlsTransport, "_libp2p_dtls_patch", False):
        return True

    if not hasattr(RTCDtlsTransport, "_set_state"):
        logger.debug("RTCDtlsTransport._set_state not found")
        return False

    original_dtls_set_state = RTCDtlsTransport._set_state

    def patched_dtls_set_state(self: RTCDtlsTransport, new_state: Any) -> None:
        """Patched DTLS _set_state that prevents CLOSED during handshake."""
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
            else:
                current_state_name = str(current_state)

        # Check if we're trying to set CLOSED state
        is_closed_transition = (
            state_name == "CLOSED"
            or "closed" in str(state_name).lower()
            or (
                hasattr(new_state, "value") and "closed" in str(new_state.value).lower()
            )
        )

        if is_closed_transition:
            # Find associated peer connection
            peer_conn = _find_peer_connection_from_dtls(self)

            if peer_conn:
                # Block if handshake, upgrade, or ownership active
                if is_handshake_active(peer_conn):
                    logger.warning(
                        "DTLS _set_state(CLOSED) BLOCKED %s - handshake active "
                        "pc=%s state=%s",
                        id(self),
                        id(peer_conn),
                        current_state_name,
                    )
                    return
                if is_upgrade_active(peer_conn):
                    logger.warning(
                        "DTLS _set_state(CLOSED) BLOCKED %s - upgrade active "
                        "pc=%s state=%s",
                        id(self),
                        id(peer_conn),
                        current_state_name,
                    )
                    return
                owner_ready_event = get_libp2p_owner_ready_event(peer_conn)
                if owner_ready_event is not None and owner_ready_event.is_set():
                    logger.warning(
                        f"DTLS _set_state(CLOSED) BLOCKED on {id(self)} - "
                        f"libp2p owns peer connection {id(peer_conn)} "
                        f"(ownership event is set), WebRTC must not close DTLS. "
                        f"current_state={current_state_name}"
                    )
                    return

                conn_state = getattr(peer_conn, "connectionState", None)
                ice_state = getattr(peer_conn, "iceConnectionState", None)

                # Capture stack trace for debugging
                stack_trace = "".join(traceback.format_stack())
                owner_set = owner_ready_event.is_set() if owner_ready_event else False
                logger.warning(
                    "DTLS _set_state(CLOSED) CALLED %s state=%s pc=%s "
                    "owner_set=%s conn=%s ice=%s\nStack:\n%s",
                    id(self),
                    current_state_name,
                    id(peer_conn),
                    owner_set,
                    conn_state,
                    ice_state,
                    stack_trace,
                )
            else:
                # Couldn't find peer connection - default to blocking close
                # This is safer than allowing close when we're uncertain
                logger.warning(
                    f"DTLS _set_state(CLOSED) BLOCKED on {id(self)} - "
                    f"current_state={current_state_name}, peer_conn=unknown "
                    f"(cannot verify ownership, blocking to be safe)"
                )
                return

        # Call original method for non-CLOSED transitions
        #  or when handshake is not active
        original_dtls_set_state(self, new_state)

    RTCDtlsTransport._set_state = patched_dtls_set_state  # type: ignore[assignment]
    RTCDtlsTransport._libp2p_dtls_patch = True  # type: ignore[attr-defined]
    return True


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

            if peer_conn:
                # Block if handshake, upgrade, or ownership active
                if is_handshake_active(peer_conn):
                    logger.warning(
                        "SCTP _set_state(CLOSED) BLOCKED %s - handshake active "
                        "pc=%s state=%s",
                        id(self),
                        id(peer_conn),
                        current_state_name,
                    )
                    return
                if is_upgrade_active(peer_conn):
                    logger.warning(
                        "SCTP _set_state(CLOSED) BLOCKED %s - upgrade active "
                        "pc=%s state=%s",
                        id(self),
                        id(peer_conn),
                        current_state_name,
                    )
                    return
                owner_ready_event = get_libp2p_owner_ready_event(peer_conn)
                if owner_ready_event is not None and owner_ready_event.is_set():
                    logger.warning(
                        f"SCTP _set_state(CLOSED) BLOCKED on {id(self)} - "
                        f"libp2p owns peer connection {id(peer_conn)} "
                        f"(ownership event is set), WebRTC must not close SCTP. "
                        f"current_state={current_state_name}"
                    )
                    return

            # Get peer connection states
            if peer_conn:
                conn_state = getattr(peer_conn, "connectionState", None)
                ice_state = getattr(peer_conn, "iceConnectionState", None)
            else:
                conn_state = None
                ice_state = None
                logger.warning(
                    f"SCTP _set_state(CLOSED) BLOCKED on {id(self)} - "
                    f"current_state={current_state_name}, peer_conn=unknown "
                    f"(cannot verify ownership, blocking to be safe)"
                )
                return

            peer_conn_id = id(peer_conn) if peer_conn else None
            owner_ready_event = (
                get_libp2p_owner_ready_event(peer_conn) if peer_conn else None
            )
            owner_set = owner_ready_event.is_set() if owner_ready_event else False
            logger.error(
                "SCTP _set_state(CLOSED) CALLED %s state=%s pc=%s "
                "owner_set=%s conn=%s ice=%s\nStack:\n%s",
                id(self),
                current_state_name,
                peer_conn_id,
                owner_set,
                conn_state,
                ice_state,
                stack_trace,
            )

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
        """Patched close method that checks for ownership and active handshake."""
        # Try to find associated peer connection
        # Data channels have a _transport attribute that links to SCTP transport
        # SCTP transport links to peer connection
        peer_conn = None
        if hasattr(self, "_transport") and self._transport:
            sctp_transport = self._transport
            if hasattr(sctp_transport, "_pc") and sctp_transport._pc:
                peer_conn = sctp_transport._pc

        if peer_conn:
            # Block if handshake, upgrade, or ownership active
            if is_handshake_active(peer_conn):
                logger.warning(
                    f"data_channel.close() BLOCKED on {id(self)} - "
                    f"handshake active on peer connection {id(peer_conn)}, "
                    f"WebRTC must not close data channel"
                )
                return
            if is_upgrade_active(peer_conn):
                logger.warning(
                    f"data_channel.close() BLOCKED on {id(self)} - "
                    f"upgrade active on peer connection {id(peer_conn)}, "
                    f"WebRTC must not close data channel"
                )
                return
            owner_ready_event = get_libp2p_owner_ready_event(peer_conn)
            if owner_ready_event is not None and owner_ready_event.is_set():
                logger.warning(
                    f"data_channel.close() BLOCKED on {id(self)} - "
                    f"libp2p owns peer connection {id(peer_conn)} "
                    f"(ownership event is set), WebRTC must not close data channel"
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
    _patch_dtls_transport_state()  # Add DTLS state monitoring
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


try:
    install_patches()
except Exception as e:
    logger.warning(f"Failed to install aiortc patches: {e}")
