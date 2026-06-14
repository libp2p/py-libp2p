import logging
from typing import Any

from libp2p.abc import INetStream
from libp2p.peer.id import ID as PeerID

from .cid import parse_cid
from .extension import IBitswapExtension
from .pb.bitswap_1_3_0_pb2 import Message as Message_1_3

logger = logging.getLogger(__name__)


class PaymentExtension(IBitswapExtension):
    """
    Bitswap 1.3.0 Payment Extension.
    Intercepts and processes payment-related protobuf fields and wantlists.
    """

    def __init__(self, payment_client: Any = None, payment_engine: Any = None):
        self.payment_client = payment_client
        self.payment_engine = payment_engine
        self.client = None

    async def process_message(
        self, peer_id: PeerID, msg_bytes: bytes, stream: INetStream
    ) -> bool:
        """
        Process the 1.3.0 specific fields: payment terms, receipts, auths.
        Returns False so that standard wantlist and block processing can
        continue if needed.
        """
        msg_1_3: Message_1_3 | None = None
        try:
            _tmp = Message_1_3()
            _tmp.ParseFromString(msg_bytes)
            msg_1_3 = _tmp
        except Exception:
            return False

        if msg_1_3 is None:
            return False

        # Client-side: handle PaymentTerms / PaymentReceipts / PaymentRejections
        if self.payment_client and (
            msg_1_3.payment_terms
            or msg_1_3.payment_receipts
            or msg_1_3.payment_rejections
        ):
            if msg_1_3.payment_terms:
                logger.warning("=" * 70)
                logger.warning(
                    f"[STEP 3] CLIENT RECEIVED PAYMENT TERMS from "
                    f"{str(peer_id)[:20]}..."
                )
                for _t in msg_1_3.payment_terms:
                    logger.warning(f"   cid={bytes(_t.cid).hex()[:20]}...")
                    logger.warning(f"   amount={_t.amount} units")
                    logger.warning(f"   asset={_t.asset}  scheme={_t.scheme}")  # type: ignore[attr-defined]
                    logger.warning(f"   pay_to={_t.pay_to[:20]}...")
                    logger.warning(f"   block_size={_t.block_size}B")
                    logger.warning(f"   valid_before={_t.valid_before}")  # type: ignore[attr-defined]
                logger.warning("=" * 70)
            if msg_1_3.payment_receipts:
                logger.warning("=" * 70)
                logger.warning(
                    f"[STEP 8a] CLIENT RECEIVED PAYMENT RECEIPT from "
                    f"{str(peer_id)[:20]}..."
                )
                for _r in msg_1_3.payment_receipts:
                    logger.warning(f"   cid={bytes(_r.cid).hex()[:20]}...")
                    logger.warning(
                        f"   tx_hash={_r.tx_hash[:20] if _r.tx_hash else 'optimistic'}"
                    )
                    logger.warning(f"   expires={_r.expires}")
                logger.warning("=" * 70)
            if msg_1_3.payment_rejections:
                logger.warning("=" * 70)
                logger.warning(
                    f"[STEP 8a] CLIENT RECEIVED PAYMENT REJECTION from "
                    f"{str(peer_id)[:20]}..."
                )
                for _rj in msg_1_3.payment_rejections:
                    logger.warning(f"   cid={bytes(_rj.cid).hex()[:20]}...")
                    logger.warning(f"   reason={_rj.reason}")
                logger.warning("=" * 70)

            response = await self.payment_client.process_incoming_message(
                str(peer_id), msg_1_3
            )
            if response is not None:
                logger.warning("=" * 70)
                logger.warning(
                    f"[STEP 5] CLIENT SENDING PAYMENT AUTHORIZATION to "
                    f"{str(peer_id)[:20]}..."
                )
                if response.payment_authorizations:
                    for _a in response.payment_authorizations:
                        logger.warning(f"   cid={bytes(_a.cid).hex()[:20]}...")
                        logger.warning(f"   from={_a.from_address[:20]}...")
                        logger.warning(f"   to={_a.to_address[:20]}...")
                        logger.warning(f"   value={_a.value}")
                        logger.warning(f"   scheme={_a.scheme}")
                        logger.warning(
                            f"   v={_a.v} r_len={len(bytes(_a.r))} "
                            f"s_len={len(bytes(_a.s))}"
                        )
                logger.warning("=" * 70)
                await self.client._write_message_bytes(
                    stream, response.SerializeToString()
                )

        # Server-side: handle PaymentAuthorizations (EIP-3009 signed payments)
        if self.payment_engine and msg_1_3.payment_authorizations:  # type: ignore[attr-defined]
            try:
                logger.warning("=" * 70)
                logger.warning(
                    f"[STEP 6] SERVER RECEIVED PAYMENT AUTHORIZATION from "
                    f"{str(peer_id)[:20]}..."
                )
                for _a in msg_1_3.payment_authorizations:  # type: ignore[attr-defined]
                    logger.warning(f"   cid={bytes(_a.cid).hex()[:20]}...")
                    logger.warning(f"   from={_a.from_address[:20]}...")
                    logger.warning(f"   to={_a.to_address[:20]}...")
                    logger.warning(f"   value={_a.value}")
                    logger.warning(f"   scheme={_a.scheme}")
                    logger.warning(
                        f"   v={_a.v} r_len={len(bytes(_a.r))} s_len={len(bytes(_a.s))}"
                    )
                logger.warning("=" * 70)

                response = await self.payment_engine.process_incoming_1_3_message(
                    str(peer_id), msg_1_3
                )
                if response is not None:
                    _has_receipt = bool(response.payment_receipts)
                    _has_rejection = bool(response.payment_rejections)
                    _has_blocks = bool(response.payload) or bool(response.blocks)
                    logger.warning("=" * 70)
                    logger.warning(
                        "[STEP 8] SERVER SENDING RESPONSE after PaymentAuthorization:"
                    )
                    logger.warning(
                        f"   has_receipt={_has_receipt}  "
                        f"has_rejection={_has_rejection}  has_blocks={_has_blocks}"
                    )
                    if _has_rejection:
                        for _rj in response.payment_rejections:
                            logger.warning(f"   ❌ REJECTION reason={_rj.reason}")
                    if _has_blocks:
                        _nb = len(response.payload) + len(response.blocks)
                    logger.warning(
                        f"   ✅ SENDING {_nb} block(s) to client "  # type: ignore
                        f"— FILE TRANSFER STARTING"
                    )
                    logger.warning("=" * 70)
                    await self.client._write_message_bytes(
                        stream, response.SerializeToString()
                    )

                # Payment authorization handled — we intercept this completely.
                return True
            except Exception as e:
                logger.error(f"Error handling PaymentAuthorization: {e}", exc_info=True)

        # Handle PaymentRequired block presences (1.3.0 type=2)
        if msg_1_3.blockPresences:
            await self.client._process_block_presences_1_3(
                msg_1_3.blockPresences, peer_id
            )

        return False

    async def process_wantlist(
        self, wantlist: Any, peer_id: PeerID, stream: INetStream
    ) -> bool:
        """
        Gated wantlist processing.
        If we have a payment_engine, we MUST gate block sharing behind payment terms.
        """
        if not self.payment_engine:
            return False

        if peer_id not in self.client._peer_wantlists:
            self.client._peer_wantlists[peer_id] = {}
        peer_wantlist = self.client._peer_wantlists[peer_id]

        if wantlist.full:
            peer_wantlist.clear()

        for entry in wantlist.entries:
            entry_cid = parse_cid(entry.block)
            if entry.cancel:
                if entry_cid in peer_wantlist:
                    del peer_wantlist[entry_cid]
                continue

            peer_wantlist[entry_cid] = {
                "priority": entry.priority,
                "want_type": entry.wantType,
                "send_dont_have": entry.sendDontHave,
            }

            peer_protocol = self.client._peer_protocols.get(peer_id, "")
            response_msg = await self.payment_engine.handle_want(
                peer_id=str(peer_id),
                cid=entry.block,
                want_type=entry.wantType,
                send_dont_have=entry.sendDontHave,
                peer_protocol=str(peer_protocol),
            )

            if response_msg is not None:
                _has_pr = bool(getattr(response_msg, "blockPresences", []))
                _has_terms = bool(getattr(response_msg, "payment_terms", []))
                _has_blocks = bool(getattr(response_msg, "payload", [])) or bool(
                    getattr(response_msg, "blocks", [])
                )
                logger.warning("=" * 70)
                logger.warning(
                    f"[STEP 2] SERVER SENDING RESPONSE for cid="
                    f"{bytes(entry.block).hex()[:20]}..."
                )
                logger.warning(
                    f"   payment_required={_has_pr}  payment_terms={_has_terms}  "
                    f"has_blocks={_has_blocks}"
                )
                if _has_pr:
                    for _bp in response_msg.blockPresences:
                        logger.warning(
                            f"   BlockPresence type={_bp.type} (2=PaymentRequired)"
                        )
                if _has_terms:
                    for _t in response_msg.payment_terms:
                        logger.warning(
                            f"   PaymentTerms: amount={_t.amount} asset={_t.asset} "
                            f"pay_to={_t.pay_to[:20]}... scheme={_t.scheme}"
                        )
                if _has_blocks:
                    logger.warning(
                        "   ✅ Sending block(s) directly (free/already paid)"
                    )
                logger.warning("=" * 70)
                await self.client._write_message_bytes(
                    stream, response_msg.SerializeToString()
                )

        return True
