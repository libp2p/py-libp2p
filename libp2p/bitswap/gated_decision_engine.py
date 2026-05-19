"""
Payment-Gated Decision Engine for Bitswap 1.3.0.

Extends the standard Bitswap block serving logic with payment gating:
- If a block is free, serve it directly.
- If a block requires payment and the peer has NOT paid, respond with
  PaymentRequired (type=2) + PaymentTerms in-band (1.3.0 path).
- If the peer sends a TxReceipt (on-chain payment proof), verify it
  and serve the block.

Proto alignment:
  PaymentTerms  → fields: cid, asset, pay_to, amount, network, block_size, description
  TxReceipt     → fields: cid, tx_hash, from_address, to_address, amount, asset, network
  PaymentReceipt → fields: cid, tx_hash, expires
  PaymentRejection → fields: cid, reason

This module lives in py-libp2p so it's importable as libp2p.bitswap.
"""

import logging
import time
from typing import Any

from libp2p.bitswap.block_store import BlockStore
from libp2p.bitswap.cid import parse_cid
from libp2p.bitswap.pb.bitswap_1_3_0_pb2 import Message as Message_1_3
from libp2p.bitswap.pb.bitswap_pb2 import Message as Message_1_2

logger = logging.getLogger(__name__)

BITSWAP_PROTOCOL_V120 = "/ipfs/bitswap/1.2.0"
BITSWAP_PROTOCOL_V130 = "/ipfs/bitswap/1.3.0"


class PaymentGatedDecisionEngine:
    """
    Decides whether to serve a block or gate it behind payment.

    Integrates with:
    - payments.ledger.PaymentLedger         — tracks paid (peer, cid) pairs
    - payments.pricing.BlockPricingEngine   — computes prices
    - payments.tx_verifier.TxVerifier       — verifies on-chain TxReceipts

    Payment flow (1.3.0):
      1. Client sends WANT_BLOCK
      2. Server → PaymentRequired + PaymentTerms (price offer)
      3. Client pays on-chain, sends TxReceipt with tx_hash
      4. Server verifies tx on-chain → PaymentReceipt + block data
    """

    def __init__(
        self,
        blockstore: BlockStore,
        ledger: Any,        # payments.ledger.PaymentLedger
        pricing: Any,       # payments.pricing.BlockPricingEngine
        tx_verifier: Any,   # payments.tx_verifier.TxVerifier (or None)
        server_wallet: str = "",
        network: str = "sepolia",
        asset: str = "ETH",
    ):
        self.blockstore = blockstore
        self.ledger = ledger
        self.pricing = pricing
        self.tx_verifier = tx_verifier
        self.server_wallet = server_wallet
        self.network = network
        self.asset = asset

        # Track pending payment offers: cid_hex → (peer_id, terms)
        self._pending_offers: dict[str, tuple[str, Any]] = {}

        # Callbacks for sending messages back to peers
        self.send_message_callback = None
        
        # Root CID tracking: cid_hex → {root_cid, total_size, child_count}
        # Used to compute total file size for pricing
        self._dag_info: dict[str, dict[str, Any]] = {}
        
        # Root CID tracking: cid_hex → {root_cid, total_size, child_count}
        # Used to compute total file size for pricing
        self._dag_info: dict[str, dict[str, Any]] = {}

    async def register_dag(
        self,
        root_cid: str | bytes,
        child_cids: list[str | bytes],
        total_size: int,
    ) -> None:
        """
        Register a DAG structure for root CID payment tracking.
        
        Call this after chunking a file to register the relationship between
        the root CID and its child blocks, along with the total file size.
        
        Args:
            root_cid: The root CID of the DAG
            child_cids: List of child/chunk CIDs
            total_size: Total size of all blocks combined (bytes)
            
        Example:
            >>> # After adding a large file to Bitswap
            >>> await engine.register_dag(
            ...     root_cid=root_cid,
            ...     child_cids=[chunk1, chunk2, ...],
            ...     total_size=5_000_000,  # 5 MB
            ... )
        """
        root_hex = _cid_to_str(root_cid)
        
        # Store DAG metadata
        self._dag_info[root_hex] = {
            "root_cid": root_hex,
            "total_size": total_size,
            "child_count": len(child_cids),
        }
        
        # Register in ledger so child blocks inherit root payment status
        await self.ledger.register_dag(root_cid, child_cids)
        
        logger.info(
            f"📋 Registered DAG: root={root_hex[:20]}... "
            f"size={total_size}B children={len(child_cids)}"
        )

    def mark_free(self, cid: str | bytes) -> None:
        """
        Mark a CID as free (no payment required).
        
        Args:
            cid: The CID to mark as free (root or child)
        """
        self.ledger.mark_free(cid)
        self.pricing.set_free(cid)
        logger.info(f"Marked as FREE: {_cid_to_str(cid)[:20]}...")

    async def handle_want(
        self,
        peer_id: str,
        cid: str | bytes,
        want_type: int,       # 0 = WANT_BLOCK, 1 = WANT_HAVE
        send_dont_have: bool,
        peer_protocol: str = BITSWAP_PROTOCOL_V120,
    ) -> Message_1_3 | Message_1_2 | None:
        """
        Process a WANT request from a peer.
        Returns a Message to send back, or None if nothing should be sent.
        """
        cid_str = _cid_to_str(cid)
        cid_bytes = _cid_to_bytes(cid)
        cid_obj = parse_cid(cid_bytes)

        logger.info(
            f"🔍 handle_want: peer={peer_id[:20]}... cid={cid_str[:20]}... "
            f"want_type={want_type} protocol={peer_protocol}"
        )

        # Check blockstore
        logger.info("All CIDs in blockstore: " + ", ".join([c.hex() for c in self.blockstore.get_all_cids()]))
        block_data = await self.blockstore.get_block(cid_obj)

        if block_data is None:
            logger.warning(f"❌ Block not in store: {cid_str[:20]}...")
            if send_dont_have:
                return self._make_dont_have(cid_bytes, peer_protocol)
            return None

        block_size = len(block_data)
        logger.info(f"✅ Block found: {cid_str[:20]}... size={block_size}")

        # Get pricing size (use total DAG size if this is part of a DAG)
        pricing_size = self._get_pricing_size(cid_str, block_size)
        
        # Compute price (at root CID level, not per-block)
        price = self.pricing.compute_price(cid_str, pricing_size)
        logger.info(
            f"💰 Price: {price} units for {cid_str[:20]}... "
            f"(block={block_size}B, pricing_size={pricing_size}B)"
        )

        # Check if free or already paid (ledger resolves child → root automatically)
        is_paid = self.ledger.is_paid(peer_id, cid_str)
        
        if price == 0:
            # Free block — serve it
            logger.info(f"✅ Serving block (FREE): {cid_str[:20]}...")
            if want_type == 1:  # WANT_HAVE
                return self._make_have(cid_bytes, peer_protocol)
            else:  # WANT_BLOCK
                return self._make_block_response(cid_bytes, block_data, peer_protocol)
        elif is_paid:
            # Already paid with sufficient amount — serve it
            logger.info(f"✅ Serving block (ALREADY PAID): {cid_str[:20]}... price={price} units")
            if want_type == 1:  # WANT_HAVE
                return self._make_have(cid_bytes, peer_protocol)
            else:  # WANT_BLOCK
                return self._make_block_response(cid_bytes, block_data, peer_protocol)
        else:
            # Payment required
            if peer_protocol == BITSWAP_PROTOCOL_V130:
                logger.info(
                    f"💳 Payment required: {price} units for {cid_str[:20]}..."
                )
                return self._make_payment_required_1_3(
                    peer_id, cid_bytes, pricing_size, price
                )
            else:
                logger.warning(
                    f"⚠️  Payment required but peer on {peer_protocol}, sending DONT_HAVE"
                )
                if send_dont_have:
                    return self._make_dont_have(cid_bytes, peer_protocol)
                return None

    async def handle_payment_authorization(
        self,
        peer_id: str,
        auth: Any,  # Message_1_3.PaymentAuthorization
    ) -> Message_1_3:
        """
        Process a PaymentAuthorization from a client (EIP-3009 signed payment).
        Verifies the signature and serves the block if valid.
        """
        cid_bytes = bytes(auth.cid)
        cid_str = cid_bytes.hex()
        from_address = auth.from_address

        logger.warning("=" * 70)
        logger.warning(
            f"[STEP 6b] SERVER handle_payment_authorization: peer={peer_id[:20]}... "
            f"cid={cid_str[:20]}... from={from_address[:12]}... value={auth.value}"
        )
        logger.warning("=" * 70)

        # Check if already paid (ledger hit — no need to re-verify)
        cid_obj = parse_cid(cid_bytes)
        block_data = await self.blockstore.get_block(cid_obj)

        if block_data is None:
            return self._make_payment_rejection(cid_bytes, "BLOCK_NOT_FOUND")

        block_size = len(block_data)
        pricing_size = self._get_pricing_size(cid_str, block_size)
        expected_price = self.pricing.compute_price(cid_str, pricing_size)

        # Check if already paid (ledger resolves child → root automatically)
        if self.ledger.is_paid(peer_id, cid_str):
            # Already in ledger with sufficient payment — serve immediately
            logger.info(
                f"✅ Already paid (ledger hit): {cid_str[:20]}... "
                f"block_size={block_size}B expected_price={expected_price}"
            )
            return self._make_receipt_and_block(cid_bytes, "", block_data)

        # Validate payment amount matches expected price
        if auth.value < expected_price:
            error_msg = (
                f"INSUFFICIENT_PAYMENT: paid={auth.value}, "
                f"expected={expected_price} for {block_size}B block"
            )
            logger.warning(f"❌ {error_msg}")
            return self._make_payment_rejection(cid_bytes, error_msg)
        
        # Verify EIP-3009 signature
        logger.warning("=" * 70)
        logger.warning(f"[STEP 7] SERVER VERIFYING EIP-3009 SIGNATURE")
        logger.warning(f"   from={from_address[:20]}...")
        logger.warning(f"   to={auth.to_address[:20]}...")
        logger.warning(f"   value={auth.value}  expected={expected_price}")
        logger.warning(f"   verifier={'configured' if self.tx_verifier is not None else 'NOT CONFIGURED (optimistic mode)'}")
        logger.warning("=" * 70)
        if self.tx_verifier is not None:
            try:
                # The tx_verifier is actually a FacilitatorClient for EIP-3009
                result = await self.tx_verifier.verify(
                    from_address=from_address,
                    to_address=auth.to_address,
                    value=auth.value,
                    valid_after=auth.valid_after,
                    valid_before=auth.valid_before,
                    nonce=bytes(auth.nonce),
                    v=auth.v,
                    r=bytes(auth.r),
                    s=bytes(auth.s),
                )
                valid = result.valid
                error = result.error
            except Exception as e:
                logger.error(f"[STEP 7] VERIFICATION EXCEPTION: {e}", exc_info=True)
                valid, error = False, str(e)

            if not valid:
                logger.warning("=" * 70)
                logger.warning(f"[STEP 7] ❌ EIP-3009 VERIFICATION FAILED: {error}")
                logger.warning("=" * 70)
                return self._make_payment_rejection(cid_bytes, error or "INVALID_SIGNATURE")
            else:
                logger.warning(f"[STEP 7] ✅ EIP-3009 VERIFICATION PASSED")
        else:
            # No verifier configured — optimistic mode: trust the authorization
            logger.warning(
                "[STEP 7] ⚠️  No payment verifier configured — accepting PaymentAuthorization optimistically"
            )

        # Record payment in ledger
        try:
            await self.ledger.record_payment(
                peer_id=peer_id,
                cid=cid_bytes,
                tx_hash="",  # No on-chain tx for EIP-3009
                amount=auth.value,
                nonce=bytes(auth.nonce),
            )
        except ValueError as e:
            # Duplicate nonce — already recorded
            logger.info(f"Payment already recorded: {e}")

        logger.warning("=" * 70)
        logger.warning(
            f"[STEP 8b] ✅ SERVER PAYMENT ACCEPTED — SENDING BLOCK TO CLIENT"
        )
        logger.warning(
            f"   cid={cid_str[:20]}... value={auth.value} expected={expected_price} block_size={block_size}B (EIP-3009)"
        )
        logger.warning("=" * 70)
        return self._make_receipt_and_block(cid_bytes, "", block_data)

    async def process_incoming_1_3_message(
        self, peer_id: str, msg: Message_1_3
    ) -> Message_1_3 | None:
        """
        Process an incoming 1.3.0 message that may contain PaymentAuthorizations.
        Returns a response message or None.
        """
        if msg.payment_authorizations:
            for auth in msg.payment_authorizations:
                return await self.handle_payment_authorization(peer_id, auth)
        return None

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get_pricing_size(self, cid_str: str, block_size: int) -> int:
        """
        Get the size to use for pricing calculation.
        
        NEW PAYMENT MODEL: For root CIDs, use total DAG size.
        For child CIDs, pricing is N/A (they inherit root payment).
        
        Args:
            cid_str: The CID (hex string)
            block_size: The actual block size
            
        Returns:
            Size in bytes to use for pricing
        """
        # Check if this is a registered DAG root
        dag_info = self._dag_info.get(cid_str)
        if dag_info:
            # This is a root CID - use total DAG size for pricing
            total_size = dag_info["total_size"]
            logger.info(
                f"💡 CID {cid_str[:20]}... is DAG root: "
                f"block_size={block_size}B, total_size={total_size}B"
            )
            return total_size
        
        # Not a registered root CID - use block size (backward compatibility)
        # This handles: old files, single-block files, or child blocks
        logger.debug(
            f"CID {cid_str[:20]}... not a registered DAG root, "
            f"using block_size={block_size}B for pricing"
        )
        return block_size

    def _make_payment_required_1_3(
        self,
        peer_id: str,
        cid_bytes: bytes,
        block_size: int,
        amount: int,
    ) -> Message_1_3:
        """Build a 1.3.0 PaymentRequired message with embedded PaymentTerms."""
        import secrets
        import time
        
        msg = Message_1_3()

        # BlockPresence with type=2 (PaymentRequired)
        presence = msg.blockPresences.add()
        presence.cid = cid_bytes
        presence.type = Message_1_3.BlockPresenceType.PaymentRequired  # = 2

        # PaymentTerms — all fields including nonce, valid_before, scheme
        terms = msg.payment_terms.add()
        terms.cid = cid_bytes
        terms.asset = self.asset
        terms.pay_to = self.server_wallet
        terms.amount = amount
        terms.network = self.network
        terms.nonce = secrets.token_bytes(32)  # Server generates nonce
        terms.valid_before = int(time.time()) + 3600  # 1 hour expiry
        terms.block_size = block_size
        terms.description = (
            f"Block {cid_bytes.hex()[:20]}... ({block_size // 1024}KB) — "
            f"pay {amount} wei to {self.server_wallet[:10]}..."
        )
        terms.scheme = "EIP3009"  # Payment scheme

        logger.info(
            f"📤 PaymentRequired → {peer_id[:20]}... "
            f"cid={cid_bytes.hex()[:20]}... amount={amount} asset={self.asset}"
        )
        return msg

    def _make_receipt_and_block(
        self, cid_bytes: bytes, tx_hash: str, block_data: bytes
    ) -> Message_1_3:
        """Build a PaymentReceipt + block payload message."""
        msg = Message_1_3()

        receipt = msg.payment_receipts.add()
        receipt.cid = cid_bytes
        receipt.tx_hash = tx_hash or ""
        receipt.expires = int(time.time()) + 86400 * 7  # 7 days

        block_entry = msg.payload.add()
        block_entry.prefix = cid_bytes[:4]
        block_entry.data = block_data

        return msg

    def _make_payment_rejection(self, cid_bytes: bytes, reason: str) -> Message_1_3:
        msg = Message_1_3()
        rejection = msg.payment_rejections.add()
        rejection.cid = cid_bytes
        rejection.reason = reason
        return msg

    def _make_have(self, cid_bytes: bytes, protocol: str) -> Message_1_3 | Message_1_2:
        MsgClass = Message_1_3 if protocol == BITSWAP_PROTOCOL_V130 else Message_1_2
        msg = MsgClass()
        presence = msg.blockPresences.add()
        presence.cid = cid_bytes
        if protocol == BITSWAP_PROTOCOL_V130:
            presence.type = Message_1_3.BlockPresenceType.Have
        else:
            presence.type = Message_1_2.BlockPresenceType.Have
        return msg

    def _make_dont_have(
        self, cid_bytes: bytes, protocol: str
    ) -> Message_1_3 | Message_1_2:
        MsgClass = Message_1_3 if protocol == BITSWAP_PROTOCOL_V130 else Message_1_2
        msg = MsgClass()
        presence = msg.blockPresences.add()
        presence.cid = cid_bytes
        if protocol == BITSWAP_PROTOCOL_V130:
            presence.type = Message_1_3.BlockPresenceType.DontHave
        else:
            presence.type = Message_1_2.BlockPresenceType.DontHave
        return msg

    def _make_block_response(
        self, cid_bytes: bytes, block_data: bytes, protocol: str
    ) -> Message_1_3 | Message_1_2:
        MsgClass = Message_1_3 if protocol == BITSWAP_PROTOCOL_V130 else Message_1_2
        msg = MsgClass()
        block = msg.payload.add()
        block.prefix = cid_bytes[:4]
        block.data = block_data
        return msg

    def _get_pricing_size(self, cid_str: str, block_size: int) -> int:
        """
        Get the size to use for pricing calculations.
        
        If this CID is part of a registered DAG, return the total DAG size.
        Otherwise, return the individual block size.
        
        Args:
            cid_str: The CID being priced
            block_size: The individual block size
            
        Returns:
            Size in bytes to use for pricing
        """
        # Check if this is a registered root CID
        if cid_str in self._dag_info:
            total_size = self._dag_info[cid_str]["total_size"]
            logger.debug(
                f"Using DAG total size for pricing: {cid_str[:20]}... "
                f"total={total_size}B (not block={block_size}B)"
            )
            return total_size
        
        # Not a registered DAG, use individual block size
        return block_size


# ── CID helpers ───────────────────────────────────────────────────────────────

def _cid_to_str(cid: str | bytes) -> str:
    if isinstance(cid, bytes):
        return cid.hex()
    return cid


def _cid_to_bytes(cid: str | bytes) -> bytes:
    if isinstance(cid, str):
        try:
            return bytes.fromhex(cid)
        except ValueError:
            return cid.encode()
    return cid
