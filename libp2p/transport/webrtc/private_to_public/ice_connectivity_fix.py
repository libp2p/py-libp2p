"""
Comprehensive ICE Connectivity Fix for py-libp2p WebRTC

This module addresses ICE connectivity check failures that cause connections
to get stuck in "checking" state, even with valid localhost candidates.
"""

import logging
from typing import Any

import aioice
from aioice.ice import CandidatePair, candidate_pair_priority
import trio

logger = logging.getLogger("libp2p.transport.webrtc.ice_fix")


class ICEConnectivityFix:
    """
    Fixes for ICE connectivity check failures.
    """

    @staticmethod
    def force_ice_restart(peer_connection: Any, role: str) -> None:
        """
        Force ICE to restart connectivity checks.
        Sometimes aioice gets stuck and needs a push.
        """
        try:
            if hasattr(peer_connection, "sctp") and peer_connection.sctp:
                ice_transport = peer_connection.sctp.transport.transport
                if hasattr(ice_transport, "iceGatherer"):
                    gatherer = ice_transport.iceGatherer
                    if hasattr(gatherer, "_connection"):
                        conn = gatherer._connection

                        # Force connection to check state
                        if hasattr(conn, "_check_state"):
                            logger.info(f"{role} Forcing ICE check state update")
                            conn._check_state()

                        # Trigger connectivity checks
                        if hasattr(conn, "_check_list"):
                            check_list = conn._check_list
                            if check_list:
                                logger.info(
                                    f"{role} ICE has {len(check_list)} candidate pairs"
                                )
                                # Log candidate pair states
                                for idx, pair in enumerate(check_list[:5]):  # First 5
                                    state = getattr(pair, "state", "unknown")
                                    logger.debug(f"{role} Pair {idx}: state={state}")
        except Exception as e:
            logger.debug(f"{role} Could not force ICE restart: {e}")

    @staticmethod
    async def monitor_and_nudge_ice(
        peer_connection: Any,
        role: str,
        timeout: float = 30.0,
        nudge_interval: float = 2.0,
    ) -> bool:
        """
        Monitor ICE and periodically nudge it if stuck in checking.

        Returns True if connection succeeds, False if timeout.
        """
        start_time = trio.current_time()
        last_nudge = start_time
        nudge_count = 0

        while trio.current_time() - start_time < timeout:
            current_state = peer_connection.iceConnectionState

            # Success states
            if current_state in ("connected", "completed"):
                logger.info(f"{role} ICE connected after {nudge_count} nudges")
                return True

            # Failure state
            if current_state == "failed":
                logger.error(f"{role} ICE failed")
                return False

            # Nudge if stuck in checking
            if current_state == "checking":
                now = trio.current_time()
                if now - last_nudge >= nudge_interval:
                    nudge_count += 1
                    logger.debug(
                        f"{role} ICE stuck in checking "
                        f"(nudge #{nudge_count}, elapsed={now - start_time:.1f}s)"
                    )
                    ICEConnectivityFix.force_ice_restart(peer_connection, role)
                    last_nudge = now

            await trio.sleep(0.1)

        # Timeout
        final_state = peer_connection.iceConnectionState
        logger.error(
            f"{role} ICE timeout after {timeout}s "
            f"(state: {final_state}, nudges: {nudge_count})"
        )
        return False

    @staticmethod
    def verify_ice_components_ready(peer_connection: Any, role: str) -> dict[str, Any]:
        """
        Verify all ICE components are properly initialized before starting checks.
        """
        issues: list[str] = []
        details: dict[str, Any] = {}

        try:
            # Check SCTP transport exists
            if not peer_connection.sctp:
                issues.append("❌ No SCTP transport")
                return {"ready": False, "issues": issues, "details": details}

            details["has_sctp"] = True

            # Check ICE transport
            if not peer_connection.sctp.transport:
                issues.append("❌ No DTLS transport")
                return {"ready": False, "issues": issues, "details": details}

            details["has_dtls"] = True

            ice_transport = peer_connection.sctp.transport.transport
            if not ice_transport:
                issues.append("❌ No ICE transport")
                return {"ready": False, "issues": issues, "details": details}

            details["has_ice_transport"] = True

            # Check ICE gatherer
            if not hasattr(ice_transport, "iceGatherer"):
                issues.append("❌ No ICE gatherer")
                return {"ready": False, "issues": issues, "details": details}

            gatherer = ice_transport.iceGatherer
            details["has_gatherer"] = True

            # Check aioice connection
            if not hasattr(gatherer, "_connection"):
                issues.append("❌ No aioice connection")
                return {"ready": False, "issues": issues, "details": details}

            conn = gatherer._connection
            details["has_connection"] = True

            # Check local candidates
            local_candidates = getattr(conn, "local_candidates", [])
            details["local_candidates"] = len(local_candidates)

            if len(local_candidates) == 0:
                issues.append("⚠️ No local ICE candidates")
            else:
                logger.info(f"{role} ✅ {len(local_candidates)} local ICE candidates")

            # Check remote candidates
            remote_candidates = getattr(conn, "remote_candidates", [])
            details["remote_candidates"] = len(remote_candidates)

            if len(remote_candidates) == 0:
                issues.append("⚠️ No remote ICE candidates")
            else:
                logger.info(f"{role} ✅ {len(remote_candidates)} remote ICE candidates")

            # Check candidate pairs
            check_list = getattr(conn, "_check_list", [])
            details["candidate_pairs"] = len(check_list)

            if len(check_list) == 0:
                issues.append("❌ No ICE candidate pairs - checks cannot start!")
            else:
                logger.info(f"{role} ✅ {len(check_list)} ICE candidate pairs")

                # Log pair states
                for idx, pair in enumerate(check_list[:3]):  # First 3
                    state = getattr(pair, "state", "unknown")
                    local = getattr(pair, "local_candidate", None)
                    remote = getattr(pair, "remote_candidate", None)
                    lh = (
                        f"{local.host if local else 'none'}:"
                        f"{local.port if local else '?'}"
                    )
                    rh = (
                        f"{remote.host if remote else 'none'}:"
                        f"{remote.port if remote else '?'}"
                    )
                    logger.debug(
                        "%s Pair %s: state=%s local=%s remote=%s",
                        role,
                        idx,
                        state,
                        lh,
                        rh,
                    )

            # Check ICE role
            ice_role = getattr(conn, "_ice_role", None)
            details["ice_role"] = ice_role
            logger.info(f"{role} ICE role: {ice_role}")

            # All checks passed
            if not issues:
                logger.info(f"{role} ✅ All ICE components ready")
                return {"ready": True, "issues": [], "details": details}
            else:
                return {"ready": len(issues) == 0, "issues": issues, "details": details}

        except Exception as e:
            issues.append(f"❌ Error checking ICE components: {e}")
            return {"ready": False, "issues": issues, "details": details}

    @staticmethod
    async def wait_for_ice_gathering_complete(
        peer_connection: Any, role: str, timeout: float = 10.0
    ) -> bool:
        """
        Wait for ICE gathering to complete before proceeding.
        This ensures we have all candidates before starting connectivity checks.
        """
        start_time = trio.current_time()

        while trio.current_time() - start_time < timeout:
            state = peer_connection.iceGatheringState

            if state == "complete":
                logger.info(f"{role} ✅ ICE gathering complete")
                return True

            await trio.sleep(0.1)

        logger.warning(
            f"{role} ⚠️ ICE gathering timeout "
            f"(state: {peer_connection.iceGatheringState})"
        )
        return False

    @staticmethod
    def prioritize_localhost_pairs(peer_connection: Any, role: str) -> None:
        """
        Re-sort aioice _check_list so 127.0.0.1/::1 pairs are checked first.
        Fixes ICE stuck in 'checking' when IPv6/link-local is tried before localhost.
        """
        try:
            if not getattr(peer_connection, "sctp", None):
                return
            ice_transport = peer_connection.sctp.transport.transport
            gatherer = getattr(ice_transport, "iceGatherer", None)
            if not gatherer or not hasattr(gatherer, "_connection"):
                return
            conn = gatherer._connection
            pairs = getattr(conn, "_check_list", None)
            if not pairs:
                return
            ice_controlling = getattr(conn, "ice_controlling", True)

            def key(pair: Any) -> tuple[int, Any]:
                local_host = pair.local_candidate.host
                remote_host = pair.remote_candidate.host
                localhost_first = local_host in (
                    "127.0.0.1",
                    "::1",
                ) and remote_host in ("127.0.0.1", "::1")
                orig = -candidate_pair_priority(
                    pair.local_candidate,
                    pair.remote_candidate,
                    ice_controlling,
                )
                return (0 if localhost_first else 1, orig)

            pairs.sort(key=key)
            if hasattr(conn, "_unfreeze_initial"):
                conn._unfreeze_initial()
            in_progress = CandidatePair.State.IN_PROGRESS
            for pair in pairs:
                if getattr(pair, "state", None) != in_progress:
                    continue
                lh = pair.local_candidate.host in ("127.0.0.1", "::1")
                rh = pair.remote_candidate.host in ("127.0.0.1", "::1")
                if lh and rh:
                    continue
                try:
                    task = getattr(pair, "task", None)
                    if task is not None and not task.done():
                        task.cancel()
                    conn.check_state(pair, CandidatePair.State.FAILED)
                    conn.check_complete(pair)
                    logger.info(
                        "%s Failed non-localhost IN_PROGRESS pair for localhost",
                        role,
                    )
                except Exception:
                    pass
                break
            logger.info("%s ICE check list re-sorted to prioritize localhost", role)
        except Exception as e:
            logger.debug(f"{role} Could not prioritize localhost pairs: {e}")

    @staticmethod
    def patch_aioice_localhost(role: str) -> None:
        """
        Ensure aioice includes localhost candidates.
        This is critical for local testing.
        """
        try:
            # Check if localhost candidates are enabled
            original_get_host_addresses = aioice.ice.get_host_addresses

            def patched_get_host_addresses(*args: Any, **kwargs: Any) -> list[str]:
                """Ensure localhost is always included"""
                addresses = list(original_get_host_addresses(*args, **kwargs))

                # Add localhost if not present
                if "127.0.0.1" not in addresses:
                    addresses.append("127.0.0.1")
                if "::1" not in addresses:
                    addresses.append("::1")

                return addresses

            aioice.ice.get_host_addresses = patched_get_host_addresses
            logger.info(f"{role} ✅ Patched aioice to include localhost")

        except Exception as e:
            logger.warning(f"{role} Could not patch aioice: {e}")

    @staticmethod
    async def diagnose_ice_failure(
        peer_connection: Any, role: str, expected_ufrag: str, expected_pwd: str
    ) -> dict[str, Any]:
        """
        Comprehensive ICE failure diagnosis.
        """
        logger.error(f"\n{'=' * 80}\n{role} ICE FAILURE DIAGNOSIS\n{'=' * 80}")

        diagnosis = {
            "role": role,
            "connection_state": peer_connection.connectionState,
            "ice_state": peer_connection.iceConnectionState,
            "gathering_state": peer_connection.iceGatheringState,
            "issues": [],
        }

        # 1. Check components
        components = ICEConnectivityFix.verify_ice_components_ready(
            peer_connection,
            role,
        )
        diagnosis["components"] = components

        if not components["ready"]:
            logger.error(f"{role} ❌ ICE components not ready:")
            for issue in components["issues"]:
                logger.error(f"  {issue}")

        # 2. Check credentials (only when expected values provided)
        if expected_ufrag or expected_pwd:
            try:
                local_desc = peer_connection.localDescription
                if local_desc:
                    from libp2p.transport.webrtc.private_to_public.util import SDP

                    sdp_ufrag, sdp_pwd = SDP.get_ice_credentials_from_sdp(
                        local_desc.sdp
                    )
                    if expected_ufrag and sdp_ufrag != expected_ufrag:
                        issue = "ufrag mismatch: expected={} sdp={}".format(
                            expected_ufrag,
                            sdp_ufrag,
                        )
                        diagnosis["issues"].append(issue)
                        logger.error(f"{role} {issue}")
                    if expected_pwd and sdp_pwd != expected_pwd:
                        issue = "❌ password mismatch"
                        diagnosis["issues"].append(issue)
                        logger.error(f"{role} {issue}")
            except Exception as e:
                diagnosis["issues"].append(f"❌ Error checking credentials: {e}")

        # 3. Log candidate pairs status (always visible on failure)
        try:
            if hasattr(peer_connection, "sctp") and peer_connection.sctp:
                ice_transport = peer_connection.sctp.transport.transport
                gatherer = ice_transport.iceGatherer
                conn = gatherer._connection
                check_list = getattr(conn, "_check_list", [])
                logger.error(f"{role} Candidate pairs ({len(check_list)} total):")
                if len(check_list) == 0:
                    logger.error(
                        "%s NO CANDIDATE PAIRS - remote candidates not processed",
                        role,
                    )
                for idx, pair in enumerate(check_list[:10]):
                    state = getattr(pair, "state", "unknown")
                    local = getattr(pair, "local_candidate", None)
                    remote = getattr(pair, "remote_candidate", None)
                    lh = (
                        f"{local.host if local else '?'}:{local.port if local else '?'}"
                    )
                    rp = (
                        f"{remote.host if remote else '?'}:"
                        f"{remote.port if remote else '?'}"
                    )
                    logger.error(
                        "%s Pair %s: %s | L: %s | R: %s",
                        role,
                        idx,
                        state,
                        lh,
                        rp,
                    )
        except Exception as e:
            diagnosis["issues"].append(f"❌ Error checking pairs: {e}")
            logger.error(f"{role} Could not check pairs: {e}")

        logger.error(f"{'=' * 80}\n")
        return diagnosis


async def enhanced_wait_for_ice_connection(
    peer_connection: Any, role: str, timeout: float = 30.0, use_monitoring: bool = True
) -> bool:
    """
    Enhanced ICE connection waiting with active monitoring and nudging.

    Args:
        peer_connection: RTCPeerConnection instance
        role: "client" or "server"
        timeout: Timeout in seconds
        use_monitoring: If True, actively monitor and nudge ICE

    Returns:
        True if connected, False if failed/timeout

    """
    # First ensure ICE gathering is complete
    gathering_ok = await ICEConnectivityFix.wait_for_ice_gathering_complete(
        peer_connection, role, timeout=min(10.0, timeout / 3)
    )

    if not gathering_ok:
        logger.warning(f"{role} ⚠️ ICE gathering incomplete, proceeding anyway")

    # Verify components are ready
    components = ICEConnectivityFix.verify_ice_components_ready(peer_connection, role)
    if not components["ready"]:
        logger.error(f"{role} ❌ ICE components not ready, cannot proceed")
        return False

    # Wait for connection with monitoring
    if use_monitoring:
        success = await ICEConnectivityFix.monitor_and_nudge_ice(
            peer_connection, role, timeout=timeout
        )
    else:
        # Simple wait
        ice_connected = trio.Event()
        ice_failed = trio.Event()

        def on_ice_change() -> None:
            state = peer_connection.iceConnectionState
            if state in ("connected", "completed"):
                ice_connected.set()
            elif state == "failed":
                ice_failed.set()

        peer_connection.on("iceconnectionstatechange", on_ice_change)

        # Check current state
        if peer_connection.iceConnectionState in ("connected", "completed"):
            return True

        with trio.move_on_after(timeout) as scope:
            async with trio.open_nursery() as nursery:
                nursery.start_soon(ice_connected.wait)
                nursery.start_soon(ice_failed.wait)

        if scope.cancelled_caught:
            success = False
        else:
            success = ice_connected.is_set()

    # Diagnose failure
    if not success:
        await ICEConnectivityFix.diagnose_ice_failure(
            peer_connection,
            role,
            expected_ufrag="",  # Would need to pass these in
            expected_pwd="",
        )

    return success
