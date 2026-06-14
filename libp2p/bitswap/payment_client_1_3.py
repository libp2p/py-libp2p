"""
Bitswap 1.3.0 Payment Client.

Client-side handler for in-band payment messages. When the server sends
a PAYMENT_REQUIRED response with PaymentTerms, this client:
1. Validates the price is acceptable
2. Signs an EIP-3009 authorization
3. Sends back a PaymentAuthorization in the same Bitswap stream
4. On receipt of PaymentReceipt, triggers a WANT_BLOCK retry

This module lives in py-libp2p so it's importable as libp2p.bitswap.
"""

from collections.abc import Callable
import logging
import time
from typing import Any

from libp2p.bitswap.pb.bitswap_1_3_0_pb2 import Message as Message_1_3

logger = logging.getLogger(__name__)

# Default maximum auto-pay threshold: $0.001 USDC = 1000 micro-units
DEFAULT_MAX_AUTO_PAY_UNITS = 1000000


class BitswapPaymentClient_1_3:
    """
    Client-side handler for Bitswap 1.3.0 payment messages.

    Processes PaymentTerms from incoming messages and auto-pays if the
    amount is within the configured threshold.

    Args:
        signer: An EIP3009Signer instance (gooseswarm.payments.eip3009_signer)
        want_manager: Object with retry_want_block(peer_id, cid) async method
        max_auto_pay_usdc: Maximum amount to auto-pay in USDC (default $1.00)
        send_callback: Async function(peer_id, msg_bytes) to send responses

    """

    def __init__(
        self,
        signer: Any,  # gooseswarm.payments.eip3009_signer.EIP3009Signer
        want_manager: Any,  # has retry_want_block(peer_id, cid) method
        max_auto_pay_usdc: float = 1.0,
        send_callback: Callable[..., Any] | None = None,
        ledger: Any = None,  # gooseswarm.payments.ledger.PaymentLedger (optional)
    ):
        self.signer = signer
        self.want_manager = want_manager
        self.max_auto_pay_units = int(max_auto_pay_usdc * 1000000)
        self.send_callback = send_callback
        self.ledger = ledger

        # Pending payments: nonce_hex → {peer_id, cid, amount}
        self._pending_payments: dict[str, dict[str, Any]] = {}

        # Server pricing config: peer_id → {units_per_kb, last_updated}
        # This is learned from PaymentTerms messages
        self._server_pricing: dict[str, dict[str, Any]] = {}

    async def process_incoming_message(
        self, peer_id: str, msg: Message_1_3
    ) -> Message_1_3 | None:
        """
        Called by the Bitswap dispatcher for every incoming 1.3.0 message.

        Handles:
        - PaymentTerms → sign and send PaymentAuthorization
        - PaymentReceipts → retry WANT_BLOCK
        - PaymentRejections → log and surface to application

        Returns a response Message to send back, or None.
        """
        # Handle payment terms (server telling us what a block costs)
        if msg.payment_terms:
            for terms in msg.payment_terms:
                response = await self._handle_payment_terms(peer_id, terms)
                if response:
                    return response

        # Handle receipts (server confirming our payment)
        for receipt in msg.payment_receipts:
            await self._handle_payment_receipt(peer_id, receipt)

        # Handle rejections
        for rejection in msg.payment_rejections:
            self._handle_payment_rejection(peer_id, rejection)

        return None

    async def build_payment_auth_msg(
        self,
        terms: Any,  # Message_1_3.PaymentTerms
    ) -> Message_1_3:
        """
        Build a PaymentAuthorization message for the given PaymentTerms.
        Used by tests and demo scripts.
        """
        v, r, s = self.signer.sign_transfer_authorization(
            to=terms.pay_to,
            value=terms.amount,
            nonce=bytes(terms.nonce),
            valid_before=terms.valid_before,
        )

        msg = Message_1_3()
        auth = msg.payment_authorizations.add()  # type: ignore[attr-defined]
        auth.cid = bytes(terms.cid)
        auth.from_address = self.signer.address
        auth.to_address = terms.pay_to
        auth.value = terms.amount
        auth.valid_after = 0
        auth.valid_before = terms.valid_before
        auth.nonce = bytes(terms.nonce)
        auth.v = v
        auth.r = r
        auth.s = s
        auth.scheme = terms.scheme
        return msg

    # ── Internal handlers ─────────────────────────────────────────────────

    async def _handle_payment_terms(
        self, peer_id: str, terms: Any
    ) -> Message_1_3 | None:
        """
        Server sent us PaymentTerms alongside a PaymentRequired BlockPresence.
        Decide whether to pay and send back a PaymentAuthorization.
        """
        amount = terms.amount
        block_size = terms.block_size

        logger.warning("=" * 70)
        logger.warning(
            f"[STEP 3b] CLIENT EVALUATING PAYMENT TERMS from {peer_id[:20]}..."
        )
        logger.warning(
            f"   amount={amount} units  max_auto_pay={self.max_auto_pay_units} units"
        )
        logger.warning(
            f"   block_size={block_size}B  asset={terms.asset}  scheme={terms.scheme}"
        )
        logger.warning("=" * 70)

        # Learn server's pricing from the PaymentTerms
        # The server includes its units_per_kb in the pricing calculation
        self._update_server_pricing(peer_id, amount, block_size)

        # Reject if too expensive
        if amount > self.max_auto_pay_units:
            logger.warning(
                f"[STEP 3b] ❌ PAYMENT REJECTED (too expensive): {amount} units > "
                f"max {self.max_auto_pay_units} units. "
                f"Skipping — will seek block elsewhere."
            )
            return None

        if not self._validate_pricing(peer_id, amount, block_size):
            logger.warning(
                f"[STEP 3b] ❌ PAYMENT REJECTED (pricing validation failed) for "
                f"{block_size}B block from {peer_id[:20]}... "
                f"Server asked {amount} units. Skipping payment."
            )
            return None

        logger.warning(
            "[STEP 3b] ✅ Payment terms accepted — proceeding to sign EIP-3009"
        )

        # Sign EIP-3009 authorization
        logger.warning("=" * 70)
        logger.warning("[STEP 4] CLIENT SIGNING EIP-3009 AUTHORIZATION")
        logger.warning(f"   to={terms.pay_to[:20]}...")
        logger.warning(f"   value={amount} units")
        logger.warning(f"   nonce={bytes(terms.nonce).hex()[:20]}...")
        logger.warning(f"   valid_before={terms.valid_before}")
        logger.warning(f"   signer_address={getattr(self.signer, 'address', 'N/A')}")
        logger.warning("=" * 70)
        try:
            v, r, s = self.signer.sign_transfer_authorization(
                to=terms.pay_to,
                value=amount,
                nonce=bytes(terms.nonce),
                valid_before=terms.valid_before,
            )
            logger.warning(
                f"[STEP 4] EIP-3009 SIGNATURE CREATED: v={v} r_len={len(r)} "
                f"s_len={len(s)}"
            )
        except Exception as e:
            logger.error(
                f"[STEP 4] FAILED TO SIGN EIP-3009 AUTHORIZATION: {e}", exc_info=True
            )
            return None

        # Build PaymentAuthorization message
        response = Message_1_3()
        auth = response.payment_authorizations.add()  # type: ignore[attr-defined]
        auth.cid = bytes(terms.cid)
        auth.from_address = self.signer.address
        auth.to_address = terms.pay_to
        auth.value = amount
        auth.valid_after = 0
        auth.valid_before = terms.valid_before
        auth.nonce = bytes(terms.nonce)
        auth.v = v
        auth.r = r
        auth.s = s
        auth.scheme = terms.scheme

        # Track pending payment
        nonce_hex = bytes(terms.nonce).hex()
        self._pending_payments[nonce_hex] = {
            "peer_id": peer_id,
            "cid": bytes(terms.cid).hex(),
            "amount": amount,
        }

        # Persist spent payment to ledger
        if self.ledger is not None:
            try:
                self.ledger.record_spent_payment(
                    peer_id=peer_id,
                    cid=bytes(terms.cid),
                    amount=amount,
                    nonce=bytes(terms.nonce),
                )
            except Exception as _e:
                logger.warning(f"Failed to persist spent payment: {_e}")

        logger.info(
            f"Sending PaymentAuthorization to {peer_id[:20]}... "
            f"cid={bytes(terms.cid).hex()[:20]}... "
            f"amount={amount} units (${amount / 1_000_000:.6f} USDC) "
            f"for {terms.block_size}B block"
        )
        return response

    async def _handle_payment_receipt(self, peer_id: str, receipt: Any) -> None:
        """Server confirmed payment. Retry the WANT_BLOCK immediately."""
        cid_hex = (
            bytes(receipt.cid).hex() if isinstance(receipt.cid, bytes) else receipt.cid
        )
        logger.info(
            f"Payment receipt received from {peer_id[:20]}... "
            f"cid={cid_hex[:20]}... "
            f"tx={receipt.tx_hash[:20] if receipt.tx_hash else 'optimistic'}..."
        )
        # Trigger want manager to retry
        if self.want_manager:
            try:
                await self.want_manager.retry_want_block(peer_id, cid_hex)
            except Exception as e:
                logger.error(f"Failed to retry want block: {e}")

    def _handle_payment_rejection(self, peer_id: str, rejection: Any) -> None:
        """Log and surface payment rejection."""
        cid_hex = (
            bytes(rejection.cid).hex()
            if isinstance(rejection.cid, bytes)
            else rejection.cid
        )
        logger.warning(
            f"Payment rejected by {peer_id[:20]}... "
            f"cid={cid_hex[:20]}... reason={rejection.reason}"
        )

    def _update_server_pricing(
        self, peer_id: str, amount: int, block_size: int
    ) -> None:
        """
        Learn the server's pricing configuration from PaymentTerms.

        The server calculates: price = max(1, int(block_size_kb * units_per_kb))
        We can reverse-engineer units_per_kb from the amount and block_size.
        """
        if amount == 0 or block_size == 0:
            return  # Free block, no pricing info to learn

        # Calculate implied units_per_kb from this payment request
        kb = block_size / 1024
        if kb > 0:
            implied_units_per_kb = amount / kb

            # Store or update the pricing config for this peer
            if peer_id not in self._server_pricing:
                self._server_pricing[peer_id] = {
                    "units_per_kb": implied_units_per_kb,
                    "last_updated": time.time(),
                    "sample_count": 1,
                }
                logger.info(
                    f"Learned pricing from {peer_id[:20]}...: "
                    f"{implied_units_per_kb:.2f} units/KB"
                )
            else:
                # Average with existing samples for stability
                config = self._server_pricing[peer_id]
                old_rate = config["units_per_kb"]
                sample_count = config["sample_count"]
                new_rate = (old_rate * sample_count + implied_units_per_kb) / (
                    sample_count + 1
                )
                config["units_per_kb"] = new_rate
                config["sample_count"] = sample_count + 1
                config["last_updated"] = time.time()

                # Warn if pricing changed significantly (>20%)
                if abs(new_rate - old_rate) / old_rate > 0.2:
                    logger.warning(
                        f"Server {peer_id[:20]}... pricing changed: "
                        f"{old_rate:.2f} → {new_rate:.2f} units/KB"
                    )

    def _validate_pricing(self, peer_id: str, amount: int, block_size: int) -> bool:
        """
        Validate that the server's price request is consistent with its learned pricing.

        Returns True if pricing is acceptable, False if suspicious.
        """
        if amount == 0:
            return True  # Free blocks are always acceptable

        # If we haven't learned pricing yet, accept this first payment
        if peer_id not in self._server_pricing:
            return True

        config = self._server_pricing[peer_id]
        units_per_kb = config["units_per_kb"]

        # Calculate expected price using learned pricing
        kb = block_size / 1024
        expected = max(1, int(kb * units_per_kb))

        # Allow 20% tolerance for rounding and small variations
        tolerance = 0.2
        min_acceptable = expected * (1 - tolerance)
        max_acceptable = expected * (1 + tolerance)

        if amount < min_acceptable or amount > max_acceptable:
            logger.warning(
                f"Pricing inconsistency detected: "
                f"expected {expected} units (±{tolerance * 100}%), got {amount} units "
                f"for {block_size}B block ({kb:.3f} KB) "
                f"using learned rate {units_per_kb:.2f} units/KB"
            )
            return False

        return True

    def get_server_pricing(self, peer_id: str) -> dict[str, Any] | None:
        """
        Get the learned pricing configuration for a peer.

        Returns:
            Dict with units_per_kb, last_updated, sample_count,
            or None if not learned yet.

        """
        return self._server_pricing.get(peer_id)
