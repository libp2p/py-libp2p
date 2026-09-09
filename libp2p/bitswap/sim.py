import logging
from typing import TYPE_CHECKING

from .cid import CIDObject

if TYPE_CHECKING:
    from .session import BitswapSession

logger = logging.getLogger("libp2p.bitswap.sim")


class SessionInterestManager:
    """
    SessionInterestManager routes incoming blocks to the sessions that requested them.
    """

    def __init__(self) -> None:
        # Map of CID to the set of Sessions waiting for it
        self._interests: dict[CIDObject, set["BitswapSession"]] = {}

    def record_session_interest(
        self, session: "BitswapSession", cid: CIDObject
    ) -> None:
        """Register a session's interest in a specific CID."""
        if cid not in self._interests:
            self._interests[cid] = set()
        self._interests[cid].add(session)
        logger.debug(f"Session {session.id} registered interest in {cid}")

    def remove_session_interest(
        self, session: "BitswapSession", cid: CIDObject
    ) -> None:
        """Remove a session's interest in a specific CID."""
        if cid in self._interests:
            self._interests[cid].discard(session)
            if not self._interests[cid]:
                del self._interests[cid]
            logger.debug(f"Session {session.id} removed interest in {cid}")

    def split_wanted_blocks(self, cid: CIDObject) -> set["BitswapSession"]:
        """Return all sessions interested in a CID and remove their interest."""
        sessions = self._interests.get(cid, set()).copy()
        if sessions:
            del self._interests[cid]
        return sessions

    def get_interested_sessions(self, cid: CIDObject) -> set["BitswapSession"]:
        """Return all sessions currently interested in a CID."""
        return self._interests.get(cid, set()).copy()
