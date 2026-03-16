# Comprehensive ICE Debugging Tool
import logging
from typing import Any

import trio

logger = logging.getLogger("libp2p.transport.webrtc.ice_debug")


class ICEDebugger:
    """
    Advanced ICE debugging based on common failure patterns.
    Addresses issues identified in GitHub discussion #1141.
    """

    @staticmethod
    def analyze_ice_credentials(
        peer_connection: Any, expected_ufrag: str, expected_pwd: str, role: str
    ) -> dict[str, Any]:
        """
        Verify ICE credentials match expectations.
        Mismatch is a common cause of STUN auth failures.
        """
        issues = []

        try:
            # Extract from local description
            local_desc = peer_connection.localDescription
            if local_desc:
                sdp_lines = local_desc.sdp.splitlines()
                sdp_ufrag = None
                sdp_pwd = None

                for line in sdp_lines:
                    if line.startswith("a=ice-ufrag:"):
                        sdp_ufrag = line.split(":", 1)[1].strip()
                    elif line.startswith("a=ice-pwd:"):
                        sdp_pwd = line.split(":", 1)[1].strip()

                # Check match
                if sdp_ufrag != expected_ufrag:
                    issues.append(
                        f"❌ ICE ufrag MISMATCH: expected={expected_ufrag}, "
                        f"in_sdp={sdp_ufrag}"
                    )
                else:
                    logger.info(f"{role} ✅ ICE ufrag matches: {sdp_ufrag}")

                if sdp_pwd != expected_pwd:
                    issues.append(
                        f"❌ ICE password MISMATCH: expected={expected_pwd[:10]}..., "
                        f"in_sdp={sdp_pwd[:10] if sdp_pwd else None}..."
                    )
                else:
                    logger.info(f"{role} ✅ ICE password matches")
            else:
                issues.append("❌ No local description set")

            # Check internal ICE connection object
            if hasattr(peer_connection, "sctp") and peer_connection.sctp:
                if hasattr(peer_connection.sctp, "transport"):
                    ice_transport = peer_connection.sctp.transport.transport
                    if hasattr(ice_transport, "iceGatherer"):
                        gatherer = ice_transport.iceGatherer
                        if hasattr(gatherer, "_connection"):
                            conn = gatherer._connection
                            actual_user = getattr(conn, "_local_username", None)
                            actual_pwd = getattr(conn, "_local_password", None)

                            if actual_user != expected_ufrag:
                                issues.append(
                                    f"❌ Internal ICE username mismatch: "
                                    f"expected={expected_ufrag}, actual={actual_user}"
                                )

                            if actual_pwd != expected_pwd:
                                issues.append("❌ Internal ICE password mismatch")

        except Exception as e:
            issues.append(f"❌ Error checking credentials: {e}")

        return {"issues": issues, "credentials_ok": len(issues) == 0}

    @staticmethod
    def check_localhost_candidates(sdp: str, role: str) -> dict[str, Any]:
        """Check if localhost candidates are present and properly formatted"""
        lines = sdp.splitlines()
        candidates = [line for line in lines if "candidate:" in line]

        localhost_v4 = [c for c in candidates if "127.0.0.1" in c]
        localhost_v6 = [c for c in candidates if "::1" in c]

        issues = []

        if not localhost_v4 and not localhost_v6:
            issues.append(
                "❌ NO LOCALHOST CANDIDATES! This will fail for local testing."
            )
        else:
            logger.info(
                f"{role} ✅ Localhost candidates: "
                f"IPv4={len(localhost_v4)}, IPv6={len(localhost_v6)}"
            )

        # Check candidate format
        for cand in candidates:
            if "typ host" in cand:
                # Host candidates should have IP and port
                parts = cand.split()
                if len(parts) < 6:
                    issues.append(f"❌ Malformed candidate: {cand[:80]}")

        return {
            "total_candidates": len(candidates),
            "localhost_v4": len(localhost_v4),
            "localhost_v6": len(localhost_v6),
            "issues": issues,
            "has_localhost": len(localhost_v4) > 0 or len(localhost_v6) > 0,
        }

    @staticmethod
    async def monitor_ice_checks(
        peer_connection: Any, role: str, duration: float = 5.0
    ) -> dict[str, Any]:
        """
        Monitor ICE connectivity checks for a period.
        Helps identify if checks are happening at all.
        """
        check_events = []

        def on_ice_state_change() -> None:
            state = peer_connection.iceConnectionState
            check_events.append(
                {"time": trio.current_time(), "type": "state_change", "state": state}
            )
            logger.info(f"{role} ICE state -> {state}")

        peer_connection.on("iceconnectionstatechange", on_ice_state_change)

        # Monitor for duration
        start = trio.current_time()
        while trio.current_time() - start < duration:
            await trio.sleep(0.5)

            current_state = peer_connection.iceConnectionState
            check_events.append(
                {"time": trio.current_time(), "type": "poll", "state": current_state}
            )

        # Analyze
        state_changes = [e for e in check_events if e["type"] == "state_change"]

        checking = any(e["state"] == "checking" for e in state_changes)
        connected = any(e["state"] in ("connected", "completed") for e in state_changes)
        analysis = {
            "total_events": len(check_events),
            "state_changes": len(state_changes),
            "final_state": peer_connection.iceConnectionState,
            "ever_reached_checking": checking,
            "ever_reached_connected": connected,
        }

        if analysis["state_changes"] == 0:
            logger.error(
                "%s NO ICE STATE CHANGES in %ss - ICE not starting!",
                role,
                duration,
            )
        elif not analysis["ever_reached_checking"]:
            logger.error(f"{role} ❌ ICE never reached 'checking' state")
        elif not analysis["ever_reached_connected"]:
            logger.warning(
                f"{role} ⚠️ ICE reached 'checking' but never 'connected' - "
                "connectivity checks failing"
            )

        return analysis

    @staticmethod
    def compare_sdp_pair(local_sdp: str, remote_sdp: str, role: str) -> dict[str, Any]:
        """
        Compare local and remote SDPs for compatibility issues.
        """
        issues = []

        def extract_ice_creds(sdp: str) -> tuple[str | None, str | None]:
            ufrag: str | None = None
            pwd: str | None = None
            for line in sdp.splitlines():
                if line.startswith("a=ice-ufrag:"):
                    ufrag = line.split(":", 1)[1].strip()
                elif line.startswith("a=ice-pwd:"):
                    pwd = line.split(":", 1)[1].strip()
            return ufrag, pwd

        local_ufrag, local_pwd = extract_ice_creds(local_sdp)
        remote_ufrag, remote_pwd = extract_ice_creds(remote_sdp)

        # Get candidates
        local_cands = [line for line in local_sdp.splitlines() if "candidate:" in line]
        remote_cands = [
            line for line in remote_sdp.splitlines() if "candidate:" in line
        ]

        logger.info(
            f"\n{'=' * 80}\n"
            f"{role} SDP COMPARISON\n"
            f"{'=' * 80}\n"
            f"Local ICE ufrag:     {local_ufrag}\n"
            f"Remote ICE ufrag:    {remote_ufrag}\n"
            f"Local candidates:    {len(local_cands)}\n"
            f"Remote candidates:   {len(remote_cands)}\n"
            f"{'=' * 80}"
        )

        # Check for common issues
        if not local_cands:
            issues.append("❌ No candidates in local SDP")

        if not remote_cands:
            issues.append("❌ No candidates in remote SDP")

        if not local_ufrag or not local_pwd:
            issues.append("❌ Missing ICE credentials in local SDP")

        if not remote_ufrag or not remote_pwd:
            issues.append("❌ Missing ICE credentials in remote SDP")

        # Check for localhost candidates on both sides
        local_has_localhost = any("127.0.0.1" in c for c in local_cands)
        remote_has_localhost = any("127.0.0.1" in c for c in remote_cands)

        if not (local_has_localhost and remote_has_localhost):
            issues.append(
                f"⚠️ Localhost candidates: local={local_has_localhost}, "
                f"remote={remote_has_localhost}"
            )

        return {
            "issues": issues,
            "compatible": len(issues) == 0,
            "local_candidate_count": len(local_cands),
            "remote_candidate_count": len(remote_cands),
        }

    @staticmethod
    async def full_diagnostic(
        peer_connection: Any,
        role: str,
        expected_ufrag: str,
        expected_pwd: str,
        remote_sdp: str | None = None,
    ) -> None:
        """Run comprehensive diagnostics"""
        logger.info(f"\n{'=' * 80}\n{role} FULL ICE DIAGNOSTIC\n{'=' * 80}")

        # 1. Check credentials
        cred_result = ICEDebugger.analyze_ice_credentials(
            peer_connection, expected_ufrag, expected_pwd, role
        )

        if not cred_result["credentials_ok"]:
            logger.error(f"{role} CREDENTIAL ISSUES:")
            for issue in cred_result["issues"]:
                logger.error(f"  {issue}")

        # 2. Check local candidates
        local_desc = peer_connection.localDescription
        if local_desc:
            cand_result = ICEDebugger.check_localhost_candidates(local_desc.sdp, role)

            if not cand_result["has_localhost"]:
                logger.error(f"{role} ❌ NO LOCALHOST CANDIDATES - apply aioice patch!")

        # 3. Compare with remote if available
        if remote_sdp and local_desc:
            comp_result = ICEDebugger.compare_sdp_pair(local_desc.sdp, remote_sdp, role)

            if not comp_result["compatible"]:
                logger.error(f"{role} SDP COMPATIBILITY ISSUES:")
                for issue in comp_result["issues"]:
                    logger.error(f"  {issue}")

        # 4. Monitor ICE activity
        logger.info(f"{role} Monitoring ICE for 5s...")
        monitor_result = await ICEDebugger.monitor_ice_checks(
            peer_connection, role, duration=5.0
        )

        logger.info(
            f"{role} ICE Activity: "
            f"changes={monitor_result['state_changes']}, "
            f"final={monitor_result['final_state']}"
        )

        logger.info(f"{'=' * 80}\n")
