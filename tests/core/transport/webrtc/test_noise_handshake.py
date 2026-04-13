"""
Tests for Noise prologue construction and DataChannelReadWriter.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from libp2p.transport.webrtc.constants import NOISE_PROLOGUE_PREFIX
from libp2p.transport.webrtc.noise_handshake import (
    DataChannelReadWriter,
    build_noise_prologue,
)


class TestBuildNoisePrologue:
    def test_prologue_starts_with_prefix(self):
        local_fp = b"\x01" * 32
        remote_fp = b"\x02" * 32
        prologue = build_noise_prologue(local_fp, remote_fp)
        assert prologue.startswith(NOISE_PROLOGUE_PREFIX)

    def test_prologue_contains_multihash_encoded_fingerprints(self):
        local_fp = b"\xaa" * 32
        remote_fp = b"\xbb" * 32
        prologue = build_noise_prologue(local_fp, remote_fp)
        # After prefix: local_mh (34 bytes) + remote_mh (34 bytes)
        after_prefix = prologue[len(NOISE_PROLOGUE_PREFIX) :]
        assert len(after_prefix) == 68  # 34 + 34
        # Verify multihash headers
        assert after_prefix[0] == 0x12  # SHA-256 code
        assert after_prefix[1] == 32  # digest length
        assert after_prefix[2:34] == local_fp
        assert after_prefix[34] == 0x12
        assert after_prefix[35] == 32
        assert after_prefix[36:68] == remote_fp

    def test_prologue_total_length(self):
        local_fp = b"\x00" * 32
        remote_fp = b"\xff" * 32
        prologue = build_noise_prologue(local_fp, remote_fp)
        # prefix (20) + local_mh (34) + remote_mh (34) = 88
        expected = len(NOISE_PROLOGUE_PREFIX) + 34 + 34
        assert len(prologue) == expected

    def test_prologue_is_asymmetric(self):
        """Swapping local/remote produces different prologues."""
        fp_a = b"\x01" * 32
        fp_b = b"\x02" * 32
        p1 = build_noise_prologue(fp_a, fp_b)
        p2 = build_noise_prologue(fp_b, fp_a)
        assert p1 != p2

    def test_prologue_with_real_fingerprints(self):
        from libp2p.transport.webrtc.certificate import WebRTCCertificate

        cert_a = WebRTCCertificate.generate()
        cert_b = WebRTCCertificate.generate()
        prologue = build_noise_prologue(cert_a.fingerprint, cert_b.fingerprint)
        assert len(prologue) == len(NOISE_PROLOGUE_PREFIX) + 68


class TestDataChannelReadWriter:
    @pytest.mark.trio
    async def test_write_calls_send_cb(self):
        send_cb = AsyncMock()
        recv_cb = AsyncMock(return_value=b"response")
        rw = DataChannelReadWriter(
            send_cb=send_cb,
            recv_cb=recv_cb,
            is_initiator=True,
        )
        await rw.write(b"hello")
        send_cb.assert_called_once_with(b"hello")

    @pytest.mark.trio
    async def test_read_calls_recv_cb(self):
        send_cb = AsyncMock()
        recv_cb = AsyncMock(return_value=b"data-from-peer")
        rw = DataChannelReadWriter(
            send_cb=send_cb,
            recv_cb=recv_cb,
            is_initiator=False,
        )
        data = await rw.read()
        assert data == b"data-from-peer"

    @pytest.mark.trio
    async def test_close_is_noop(self):
        rw = DataChannelReadWriter(
            send_cb=AsyncMock(),
            recv_cb=AsyncMock(),
            is_initiator=True,
        )
        await rw.close()  # Should not raise

    def test_is_initiator_property(self):
        rw = DataChannelReadWriter(
            send_cb=AsyncMock(),
            recv_cb=AsyncMock(),
            is_initiator=True,
        )
        assert rw.is_initiator is True

    def test_transport_addresses_empty(self):
        rw = DataChannelReadWriter(
            send_cb=AsyncMock(),
            recv_cb=AsyncMock(),
            is_initiator=True,
        )
        assert rw.get_transport_addresses() == []
