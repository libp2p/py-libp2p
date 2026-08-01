from unittest.mock import AsyncMock, MagicMock

import pytest

from libp2p.bitswap.gated_decision_engine import PaymentGatedDecisionEngine
from libp2p.bitswap.payment_ledger import PaymentLedger
from libp2p.bitswap.pricing_engine import BlockPricingEngine


def test_block_pricing_engine_size_based():
    pricing = BlockPricingEngine(strategy="size_based", units_per_kb=10.0)
    # 500 KB = 512000 bytes
    price = pricing.compute_price("cid1", 512000)
    assert price == 5000


def test_block_pricing_engine_fixed():
    pricing = BlockPricingEngine(strategy="fixed", fixed_price=123)
    price = pricing.compute_price("cid1", 512000)
    assert price == 123


def test_block_pricing_engine_free():
    pricing = BlockPricingEngine(strategy="free")
    price = pricing.compute_price("cid1", 512000)
    assert price == 0


def test_block_pricing_engine_overrides():
    pricing = BlockPricingEngine(strategy="fixed", fixed_price=100)
    pricing.set_price(b"cid2", 50)
    pricing.set_free(b"cid3")

    assert pricing.compute_price(b"cid1".hex(), 10) == 100
    assert pricing.compute_price(b"cid2".hex(), 10) == 50
    assert pricing.compute_price(b"cid3".hex(), 10) == 0


@pytest.mark.trio
async def test_payment_ledger_registration_and_payment():
    ledger = PaymentLedger()

    root_cid = b"root"
    child_cids: list[bytes | str] = [b"child1", b"child2"]

    await ledger.register_dag(root_cid, child_cids)

    assert not ledger.is_paid("peer1", b"child1")

    await ledger.record_payment("peer1", b"root", amount=1000, nonce=b"nonce1")

    # After payment for root, root and children should be considered paid
    assert ledger.is_paid("peer1", b"root")
    assert ledger.is_paid("peer1", b"child1")
    assert ledger.is_paid("peer1", b"child2")

    # Peer 2 has not paid
    assert not ledger.is_paid("peer2", b"root")


@pytest.mark.trio
async def test_payment_ledger_nonce_replay():
    ledger = PaymentLedger()

    await ledger.record_payment("peer1", b"root", amount=1000, nonce=b"nonce1")

    with pytest.raises(ValueError, match="Nonce already used"):
        await ledger.record_payment("peer1", b"root", amount=1000, nonce=b"nonce1")

    # Different nonce should work
    await ledger.record_payment("peer1", b"root", amount=1000, nonce=b"nonce2")


@pytest.mark.trio
async def test_gated_decision_engine_auth():
    # Setup mocks
    blockstore = AsyncMock()
    blockstore.get_block.return_value = b"block data"

    ledger = PaymentLedger()
    pricing = BlockPricingEngine(strategy="fixed", fixed_price=100)

    engine = PaymentGatedDecisionEngine(
        blockstore=blockstore, ledger=ledger, pricing=pricing, tx_verifier=None
    )

    auth = MagicMock()
    auth.cid = b"cid1"
    auth.value = 50
    auth.from_address = "0x..."
    auth.nonce = b"nonce1"

    # Payment less than expected
    response = await engine.handle_payment_authorization("peer1", auth)
    assert len(response.payment_rejections) == 1
    assert "INSUFFICIENT_PAYMENT" in response.payment_rejections[0].reason

    # Payment sufficient
    auth.value = 100
    response = await engine.handle_payment_authorization("peer1", auth)
    assert len(response.payment_receipts) == 1
    assert len(response.payload) == 1
    assert response.payload[0].data == b"block data"

    # Nonce reused
    auth.nonce = b"nonce1"
    # Should still succeed because ledger is_paid will return true
    # and it skips re-verification
    response = await engine.handle_payment_authorization("peer1", auth)
    assert len(response.payment_receipts) == 1
