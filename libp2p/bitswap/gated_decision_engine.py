"""
Payment-Gated Decision Engine for Bitswap 1.3.0.

Extends the standard Bitswap block serving logic with payment gating:
- If a block is free (small), serve it directly.
- If a block requires payment and the peer has NOT paid, respond with
  PaymentRequired (type=2) + PaymentTerms in-band (1.3.0 path) or
  DONT_HAVE + side-channel (1.2.0 fallback path).
- If the peer HAS paid, serve the block normally.

This module lives in py-libp2p so it's importable as libp2p.bitswap.
"""

import logging
import os
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
    - gooseswarm.payments.ledger.PaymentLedger — tracks paid (peer, cid) pairs
    - gooseswarm.payments.pricing.BlockPricingEngine — computes prices
    - gooseswarm.payments.facilitator.FacilitatorClient — verifies EIP-712 sigs

    Usage:
        engine = PaymentGatedDecisionEngine(
            blockstore=my_blockstore,
            ledger=my_ledger,
            pricing=my_pricing,
            facilitator=my_facilitator,
            server_wallet="0x...",
        )
        # Wire into BitswapClient as a message handler
    """

    def __init__(
        self,
        blockstore: BlockStore,
        ledger: Any,  # gooseswarm.payments.ledger.PaymentLedger
        pricing: Any,  # gooseswarm.payments.pricing.BlockPricingEngine
        facilitator: Any,  # gooseswarm.payments.facilitator.FacilitatorClient
        server_wallet: str = "",
        host: Any = None,
    ):
        self.blockstore = blockstore
        self.ledger = ledger
        self.pricing = pricing
        self.facilitator = facilitator
        self.server_wallet = server_wallet or (
            facilitator.server_wallet if facilitator else ""
        )
        self.host = host

        # Pending payment offers: nonce_bytes → offer_dict
        self._pending_offers: dict[bytes, dict[str, Any]] = {}

        # Callbacks for sending messages back to peers
        # Set externally: engine.send_message_callback = async_fn(peer_id, msg_bytes)
        self.send_message_callback = None

    async def handle_want(
        self,
        peer_id: str,
        cid: str | bytes,
        want_type: int,  # 0 = WANT_BLOCK, 1 = WANT_HAVE
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

        # Check blockstore
        block_data = await self.blockstore.get_block(cid_obj)

        if block_data is None:
            # We don't have the block
            if send_dont_have:
                return self._make_dont_have(cid_bytes, peer_protocol)
            return None

        block_size = len(block_data)

        # Compute price
        price = self.pricing.compute_price(cid_str, block_size)

        if price == 0 or self.ledger.is_paid(peer_id, cid_str, block_size):
            # Free block or already paid — serve it
            if want_type == 1:  # WANT_HAVE
                return self._make_have(cid_bytes, peer_protocol)
            else:  # WANT_BLOCK
                return self._make_block_response(cid_bytes, block_data, peer_protocol)
        else:
            # Payment required
            if peer_protocol == BITSWAP_PROTOCOL_V130:
                return await self._make_payment_required_1_3(
                    peer_id, cid_bytes, block_size, price
                )
            else:
                # 1.2.0 fallback: send DONT_HAVE (side-channel is handled separately)
                if send_dont_have:
                    return self._make_dont_have(cid_bytes, peer_protocol)
                return None

    async def handle_payment_authorization(
        self,
        peer_id: str,
        auth: Any,  # pb_1_3.Message.PaymentAuthorization
    ) -> Message_1_3:
        """
        Process a PaymentAuthorization from a client.
        Returns a PaymentReceipt or PaymentRejection message.
        """
        nonce = bytes(auth.nonce)

        # Validate against pending offer
        offer = self._pending_offers.pop(nonce, None)
        if offer is None:
            logger.warning(
                f"No pending offer for nonce {nonce.hex()[:10]}... "
                f"from {peer_id[:20]}..."
            )
            return self._make_payment_rejection(auth.cid, "NO_PENDING_OFFER")

        if offer["peer_id"] != peer_id:
            return self._make_payment_rejection(auth.cid, "PEER_MISMATCH")

        # Check nonce replay
        if self.ledger.is_nonce_used(nonce):
            return self._make_payment_rejection(auth.cid, "NONCE_USED")

        # Check amount
        if auth.value < offer["amount"]:
            reason = f"WRONG_AMOUNT:need={offer['amount']},got={auth.value}"
            return self._make_payment_rejection(auth.cid, reason)

        # Check expiry
        if offer["valid_before"] < int(time.time()):
            return self._make_payment_rejection(auth.cid, "EXPIRED")

        # Verify EIP-712 signature
        result = await self.facilitator.verify(
            from_address=auth.from_address,
            to_address=auth.to_address,
            value=auth.value,
            valid_after=auth.valid_after,
            valid_before=auth.valid_before,
            nonce=nonce,
            v=auth.v,
            r=bytes(auth.r),
            s=bytes(auth.s),
        )

        if not result.valid:
            return self._make_payment_rejection(auth.cid, result.error)

        # Record payment in ledger
        try:
            await self.ledger.record_payment(
                peer_id=peer_id,
                cid=bytes(auth.cid),
                tx_hash=result.tx_hash,
                amount=auth.value,
                nonce=nonce,
            )
        except ValueError as e:
            return self._make_payment_rejection(auth.cid, str(e))

        # Send PaymentReceipt + the block data
        msg = Message_1_3()
        receipt = msg.payment_receipts.add()
        receipt.cid = bytes(auth.cid)
        receipt.tx_hash = result.tx_hash
        receipt.expires = int(time.time()) + 86400 * 7  # 7 days

        # Include the paid block in the response
        block_data = await self.blockstore.get_block(parse_cid(bytes(auth.cid)))
        if block_data is not None:
            block_entry = msg.payload.add()
            block_entry.prefix = bytes(auth.cid)[:4]
            block_entry.data = block_data
            logger.info(
                f"Payment accepted + block sent to {peer_id[:20]}... "
                f"cid={bytes(auth.cid).hex()[:20]}... amount={auth.value} "
                f"size={len(block_data)} bytes"
            )
        else:
            logger.warning(
                f"Payment accepted but block not found locally: "
                f"cid={bytes(auth.cid).hex()[:20]}..."
            )
            logger.info(
                f"Payment accepted from {peer_id[:20]}... "
                f"cid={bytes(auth.cid).hex()[:20]}... amount={auth.value}"
            )
        return msg

    async def process_incoming_1_3_message(
        self, peer_id: str, msg: Message_1_3
    ) -> Message_1_3 | None:
        """
        Process an incoming 1.3.0 message that may contain PaymentAuthorizations.
        Returns a response message or None.
        """
        if msg.payment_authorizations:
            # Process the first authorization (typically one per message)
            for auth in msg.payment_authorizations:
                return await self.handle_payment_authorization(peer_id, auth)
        return None

    # ── Internal helpers ──────────────────────────────────────────────────

    async def _make_payment_required_1_3(
        self,
        peer_id: str,
        cid_bytes: bytes,
        block_size: int,
        amount: int,
    ) -> Message_1_3:
        """Build a 1.3.0 PaymentRequired message with embedded PaymentTerms."""
        nonce = os.urandom(32)
        valid_before = int(time.time()) + 120  # 2 minute window

        # Store pending offer for when PaymentAuthorization arrives
        self._pending_offers[nonce] = {
            "peer_id": peer_id,
            "cid": cid_bytes,
            "amount": amount,
            "valid_before": valid_before,
        }

        msg = Message_1_3()

        # BlockPresence with type=2 (PaymentRequired)
        presence = msg.blockPresences.add()
        presence.cid = cid_bytes
        presence.type = Message_1_3.BlockPresenceType.PaymentRequired  # = 2

        # PaymentTerms in field 6
        terms = msg.payment_terms.add()
        terms.cid = cid_bytes
        terms.asset = self.facilitator.usdc_address if self.facilitator else ""
        terms.pay_to = self.server_wallet
        terms.amount = amount
        terms.network = getattr(self.facilitator, "network", "base-sepolia")
        terms.nonce = nonce
        terms.valid_before = valid_before
        terms.block_size = block_size
        terms.description = f"Block {cid_bytes.hex()[:20]}... ({block_size // 1024}KB)"
        terms.scheme = "exact"

        logger.info(
            f"Sending PaymentRequired to {peer_id[:20]}... "
            f"cid={cid_bytes.hex()[:20]}... amount={amount} units"
        )
        return msg

    def _make_have(self, cid_bytes: bytes, protocol: str) -> Message_1_3 | Message_1_2:
        MsgClass = Message_1_3 if protocol == BITSWAP_PROTOCOL_V130 else Message_1_2
        msg = MsgClass()
        presence = msg.blockPresences.add()
        presence.cid = cid_bytes
        if protocol == BITSWAP_PROTOCOL_V130:
            presence.type = Message_1_3.BlockPresenceType.Have  # = 0
        else:
            presence.type = Message_1_2.BlockPresenceType.Have  # = 0
        return msg

    def _make_dont_have(
        self, cid_bytes: bytes, protocol: str
    ) -> Message_1_3 | Message_1_2:
        MsgClass = Message_1_3 if protocol == BITSWAP_PROTOCOL_V130 else Message_1_2
        msg = MsgClass()
        presence = msg.blockPresences.add()
        presence.cid = cid_bytes
        if protocol == BITSWAP_PROTOCOL_V130:
            presence.type = Message_1_3.BlockPresenceType.DontHave  # = 1
        else:
            presence.type = Message_1_2.BlockPresenceType.DontHave  # = 1
        return msg

    def _make_block_response(
        self, cid_bytes: bytes, block_data: bytes, protocol: str
    ) -> Message_1_3 | Message_1_2:
        MsgClass = Message_1_3 if protocol == BITSWAP_PROTOCOL_V130 else Message_1_2
        msg = MsgClass()
        block = msg.payload.add()
        block.data = block_data
        # CID prefix: first 4 bytes of CID bytes (version + codec)
        block.prefix = cid_bytes[:4] if len(cid_bytes) >= 4 else cid_bytes
        return msg

    def _make_payment_rejection(self, cid_bytes: bytes, reason: str) -> Message_1_3:
        msg = Message_1_3()
        rej = msg.payment_rejections.add()
        rej.cid = bytes(cid_bytes)
        rej.reason = reason
        logger.warning(
            f"Payment rejected: cid={bytes(cid_bytes).hex()[:20]}... reason={reason}"
        )
        return msg


def _cid_to_str(cid: str | bytes) -> str:
    if isinstance(cid, bytes):
        return cid.hex()
    return cid


def _cid_to_bytes(cid: str | bytes) -> bytes:
    if isinstance(cid, str):
        # Try hex decode first
        try:
            return bytes.fromhex(cid.lstrip("0x"))
        except ValueError:
            return cid.encode()
    return cid
