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
from typing import Any

from libp2p.bitswap.pb.bitswap_1_3_0_pb2 import Message as Message_1_3

logger = logging.getLogger(__name__)

# Default maximum auto-pay threshold: $0.001 USDC = 1000 micro-units
DEFAULT_MAX_AUTO_PAY_UNITS = 1000


class BitswapPaymentClient_1_3:
    """
    Client-side handler for Bitswap 1.3.0 payment messages.

    Processes PaymentTerms from incoming messages and auto-pays if the
    amount is within the configured threshold.

    Args:
        signer: An EIP3009Signer instance (gooseswarm.payments.eip3009_signer)
        want_manager: Object with retry_want_block(peer_id, cid) async method
        max_auto_pay_usdc: Maximum amount to auto-pay in USDC (default $0.001)
        send_callback: Async function(peer_id, msg_bytes) to send responses

    """

    def __init__(
        self,
        signer: Any,  # gooseswarm.payments.eip3009_signer.EIP3009Signer
        want_manager: Any,  # has retry_want_block(peer_id, cid) method
        max_auto_pay_usdc: float = 0.001,
        send_callback: Callable[..., Any] | None = None,
        ledger: Any = None,  # gooseswarm.payments.ledger.PaymentLedger (optional)
    ):
        self.signer = signer
        self.want_manager = want_manager
        self.max_auto_pay_units = int(max_auto_pay_usdc * 1_000_000)
        self.send_callback = send_callback
        self.ledger = ledger

        # Pending payments: nonce_hex → {peer_id, cid, amount}
        self._pending_payments: dict[str, dict[str, Any]] = {}

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
        auth = msg.payment_authorizations.add()
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

        # Reject if too expensive
        if amount > self.max_auto_pay_units:
            logger.info(
                f"Block too expensive: {amount} units > "
                f"max {self.max_auto_pay_units} units. "
                f"Skipping — will seek block elsewhere."
            )
            return None

        # Validate pricing isn't a lie (10% tolerance)
        expected_amount = self._expected_price(terms.block_size)
        if expected_amount > 0 and amount > expected_amount * 1.1:
            logger.warning(
                f"Server overcharging: asked {amount}, expected ~{expected_amount}. "
                f"Skipping payment."
            )
            return None

        # Sign EIP-3009 authorization
        try:
            v, r, s = self.signer.sign_transfer_authorization(
                to=terms.pay_to,
                value=amount,
                nonce=bytes(terms.nonce),
                valid_before=terms.valid_before,
            )
        except Exception as e:
            logger.error(f"Failed to sign payment authorization: {e}")
            return None

        # Build PaymentAuthorization message
        response = Message_1_3()
        auth = response.payment_authorizations.add()
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
            f"cid={bytes(terms.cid).hex()[:20]}... amount={amount} units "
            f"(${amount / 1_000_000:.6f} USDC)"
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

    def _expected_price(self, block_size_bytes: int) -> int:
        """
        Client-side price oracle — must roughly match server pricing.
        Used to detect overcharging.
        """
        if block_size_bytes <= 4096:
            return 0
        kb = block_size_bytes / 1024
        return int(kb * 10)  # 10 units per KB baseline
