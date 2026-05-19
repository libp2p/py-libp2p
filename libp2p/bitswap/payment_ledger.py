"""
Payment Ledger for Bitswap 1.3.0 - Root CID Payment Tracking.

Tracks payments at the root CID level, not per-block. When a peer pays for
a root CID, all child blocks (chunks) in the DAG are automatically accessible.

Design:
- Payment records: (peer_id, root_cid) → {amount, nonce, timestamp, tx_hash}
- Root CID mapping: (child_cid) → root_cid (for chunk → root resolution)
- Nonce deduplication: Prevents replay attacks
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class PaymentLedger:
    """
    Tracks root CID payments for Bitswap 1.3.0.
    
    When a peer pays for a root CID, they gain access to all blocks in that DAG.
    This prevents charging separately for each chunk of a multi-block file.
    
    Example:
        >>> ledger = PaymentLedger()
        >>> 
        >>> # Register a DAG structure (root → children mapping)
        >>> await ledger.register_dag(
        ...     root_cid="bafyroot123...",
        ...     child_cids=["bafychild1...", "bafychild2...", ...]
        ... )
        >>> 
        >>> # Record payment for root CID
        >>> await ledger.record_payment(
        ...     peer_id="12D3Koo...",
        ...     cid=b"\\x01\\x55...",  # Can be root or child CID
        ...     amount=1000000,  # 1 USDC in micro-units
        ...     nonce=b"\\x12\\x34...",
        ... )
        >>> 
        >>> # Check if peer has paid (works for root OR child CIDs)
        >>> ledger.is_paid("12D3Koo...", "bafychild1...")  # True (child of paid root)
        >>> ledger.is_paid("12D3Koo...", "bafyroot123...")  # True (root itself)
    """

    def __init__(self):
        # Payment records: (peer_id, root_cid_hex) → payment_info
        self._payments: dict[tuple[str, str], dict[str, Any]] = {}
        
        # Child → Root mapping: child_cid_hex → root_cid_hex
        # Used to resolve chunk CIDs to their root CID
        self._cid_to_root: dict[str, str] = {}
        
        # Nonce registry: nonce_hex → (peer_id, cid_hex, timestamp)
        # Prevents replay attacks (same nonce can't be used twice)
        self._used_nonces: dict[str, tuple[str, str, float]] = {}
        
        # Free CIDs: Set of CID hashes that are always free (no payment required)
        self._free_cids: set[str] = set()

    async def register_dag(
        self,
        root_cid: str | bytes,
        child_cids: list[str | bytes],
    ) -> None:
        """
        Register a DAG structure so child blocks inherit root payment status.
        
        Args:
            root_cid: The root CID of the DAG (hex string or bytes)
            child_cids: List of child/chunk CIDs in the DAG
            
        Example:
            >>> # After chunking a file into blocks
            >>> await ledger.register_dag(
            ...     root_cid=root_cid,
            ...     child_cids=[chunk1_cid, chunk2_cid, ...]
            ... )
        """
        root_hex = _cid_to_hex(root_cid)
        
        for child_cid in child_cids:
            child_hex = _cid_to_hex(child_cid)
            self._cid_to_root[child_hex] = root_hex
            logger.debug(f"Registered child {child_hex[:20]}... → root {root_hex[:20]}...")
        
        logger.info(
            f"Registered DAG: root={root_hex[:20]}... with {len(child_cids)} children"
        )

    def mark_free(self, cid: str | bytes) -> None:
        """
        Mark a CID as free (no payment required).
        
        Args:
            cid: The CID to mark as free (hex string or bytes)
        """
        cid_hex = _cid_to_hex(cid)
        self._free_cids.add(cid_hex)
        logger.info(f"Marked CID as FREE: {cid_hex[:20]}...")

    def is_free(self, cid: str | bytes) -> bool:
        """
        Check if a CID is marked as free.
        
        Args:
            cid: The CID to check (hex string or bytes)
            
        Returns:
            True if the CID is free, False otherwise
        """
        cid_hex = _cid_to_hex(cid)
        root_hex = self._cid_to_root.get(cid_hex, cid_hex)
        return cid_hex in self._free_cids or root_hex in self._free_cids

    def is_paid(
        self,
        peer_id: str,
        cid: str | bytes,
        block_size: int = 0,  # Ignored (kept for backward compatibility)
    ) -> bool:
        """
        Check if a peer has paid for a CID (root or child).
        
        Resolves child CIDs to their root CID automatically.
        
        Args:
            peer_id: The peer ID to check
            cid: The CID to check (can be root or child CID)
            block_size: Ignored (kept for backward compatibility with old API)
            
        Returns:
            True if the peer has paid for this CID (or its root), False otherwise
        """
        cid_hex = _cid_to_hex(cid)
        
        # Check if it's a free CID
        if self.is_free(cid_hex):
            return True
        
        # Resolve to root CID if this is a child
        root_hex = self._cid_to_root.get(cid_hex, cid_hex)
        
        # Check if payment exists for (peer, root)
        key = (peer_id, root_hex)
        paid = key in self._payments
        
        if paid:
            payment = self._payments[key]
            logger.debug(
                f"✅ Payment found: peer={peer_id[:20]}... "
                f"cid={cid_hex[:20]}... root={root_hex[:20]}... "
                f"amount={payment['amount']}"
            )
        else:
            logger.debug(
                f"❌ No payment: peer={peer_id[:20]}... "
                f"cid={cid_hex[:20]}... root={root_hex[:20]}..."
            )
        
        return paid

    async def record_payment(
        self,
        peer_id: str,
        cid: str | bytes,
        amount: int,
        nonce: bytes,
        tx_hash: str = "",
    ) -> None:
        """
        Record a payment for a root CID.
        
        Args:
            peer_id: The peer who paid
            cid: The CID being paid for (root or child - will resolve to root)
            amount: Payment amount in micro-units (e.g., USDC micro-units)
            nonce: Unique nonce for this payment (prevents replay attacks)
            tx_hash: Optional transaction hash (empty for EIP-3009)
            
        Raises:
            ValueError: If the nonce has already been used
        """
        cid_hex = _cid_to_hex(cid)
        nonce_hex = nonce.hex()
        
        # Check for nonce reuse (replay attack prevention)
        if nonce_hex in self._used_nonces:
            existing = self._used_nonces[nonce_hex]
            raise ValueError(
                f"Nonce already used: {nonce_hex[:20]}... "
                f"by peer={existing[0][:20]}... for cid={existing[1][:20]}..."
            )
        
        # Resolve to root CID
        root_hex = self._cid_to_root.get(cid_hex, cid_hex)
        
        # Record payment
        key = (peer_id, root_hex)
        self._payments[key] = {
            "amount": amount,
            "nonce": nonce_hex,
            "tx_hash": tx_hash,
            "timestamp": time.time(),
        }
        
        # Mark nonce as used
        self._used_nonces[nonce_hex] = (peer_id, root_hex, time.time())
        
        logger.info(
            f"💰 Payment recorded: peer={peer_id[:20]}... "
            f"root={root_hex[:20]}... amount={amount} "
            f"nonce={nonce_hex[:16]}..."
        )

    def get_payment(
        self,
        peer_id: str,
        cid: str | bytes,
    ) -> dict[str, Any] | None:
        """
        Get payment details for a peer and CID.
        
        Args:
            peer_id: The peer ID
            cid: The CID (root or child)
            
        Returns:
            Payment info dict with keys: amount, nonce, tx_hash, timestamp
            or None if no payment found
        """
        cid_hex = _cid_to_hex(cid)
        root_hex = self._cid_to_root.get(cid_hex, cid_hex)
        key = (peer_id, root_hex)
        return self._payments.get(key)

    def clear_old_nonces(self, max_age_seconds: float = 86400) -> int:
        """
        Clear nonces older than max_age_seconds (default: 24 hours).
        
        Returns:
            Number of nonces cleared
        """
        now = time.time()
        old_nonces = [
            nonce_hex
            for nonce_hex, (_, _, timestamp) in self._used_nonces.items()
            if now - timestamp > max_age_seconds
        ]
        
        for nonce_hex in old_nonces:
            del self._used_nonces[nonce_hex]
        
        if old_nonces:
            logger.info(f"Cleared {len(old_nonces)} old nonces (>{max_age_seconds}s)")
        
        return len(old_nonces)


# ── Helper functions ──────────────────────────────────────────────────────────

def _cid_to_hex(cid: str | bytes) -> str:
    """Convert CID to hex string for consistent storage."""
    if isinstance(cid, bytes):
        return cid.hex()
    elif isinstance(cid, str):
        # If already hex, return as-is; otherwise try to decode
        try:
            bytes.fromhex(cid)
            return cid
        except ValueError:
            # Assume it's a base58/base32 encoded CID string
            return cid.encode().hex()
    else:
        raise TypeError(f"CID must be str or bytes, got {type(cid)}")
