"""Tests for perf protocol client-side functionality."""

import struct

import pytest

from libp2p.perf import PerfService
from tests.utils.factories import host_pair_factory


@pytest.mark.trio
async def test_client_upload_small_size(security_protocol):
    """Test client upload with small sizes: 0, 1, 100, 1024 bytes."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        server = PerfService(host_a)
        client = PerfService(host_b)
        await server.start()

        # Test various small upload sizes
        test_sizes = [0, 1, 100, 1024]

        for send_bytes in test_sizes:
            recv_bytes = 0  # No download for this test
            results = []
            async for output in client.measure_performance(
                host_a.get_addrs()[0].encapsulate(f"/p2p/{host_a.get_id()}"),
                send_bytes,
                recv_bytes,
            ):
                results.append(output)

            final = results[-1]
            assert final["type"] == "final"
            assert final["upload_bytes"] == send_bytes, (
                f"Expected upload_bytes={send_bytes}, got {final['upload_bytes']}"
            )


@pytest.mark.trio
async def test_client_download_small_size(security_protocol):
    """Test client download with small sizes: 0, 1, 100, 1024 bytes."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        server = PerfService(host_a)
        client = PerfService(host_b)
        await server.start()

        # Test various small download sizes
        test_sizes = [0, 1, 100, 1024]

        for recv_bytes in test_sizes:
            send_bytes = 8  # Minimal upload (just header size worth)
            results = []
            async for output in client.measure_performance(
                host_a.get_addrs()[0].encapsulate(f"/p2p/{host_a.get_id()}"),
                send_bytes,
                recv_bytes,
            ):
                results.append(output)

            final = results[-1]
            assert final["type"] == "final"
            assert final["download_bytes"] == recv_bytes, (
                f"Expected download_bytes={recv_bytes}, got {final['download_bytes']}"
            )


@pytest.mark.trio
async def test_client_asymmetric_upload_download(security_protocol):
    """Test asymmetric transfer: upload 100 bytes, download 1000 bytes."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        server = PerfService(host_a)
        client = PerfService(host_b)
        await server.start()

        send_bytes = 100
        recv_bytes = 1000

        results = []
        async for output in client.measure_performance(
            host_a.get_addrs()[0].encapsulate(f"/p2p/{host_a.get_id()}"),
            send_bytes,
            recv_bytes,
        ):
            results.append(output)

        final = results[-1]
        assert final["type"] == "final"
        assert final["upload_bytes"] == send_bytes
        assert final["download_bytes"] == recv_bytes


@pytest.mark.trio
async def test_client_final_output_correct(security_protocol):
    """Verify final PerfOutput has correct structure and byte counts."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        server = PerfService(host_a)
        client = PerfService(host_b)
        await server.start()

        send_bytes = 512
        recv_bytes = 256

        results = []
        async for output in client.measure_performance(
            host_a.get_addrs()[0].encapsulate(f"/p2p/{host_a.get_id()}"),
            send_bytes,
            recv_bytes,
        ):
            results.append(output)

        # Verify we got at least a final result
        assert len(results) >= 1

        final = results[-1]
        assert final["type"] == "final"
        assert final["upload_bytes"] == send_bytes
        assert final["download_bytes"] == recv_bytes
        assert final["time_seconds"] > 0


def test_client_header_format():
    """Verify the 8-byte header format is correct (unit test)."""
    # Test that the header format used by the client is correct
    # The client uses struct.pack(">Q", recv_bytes) to create the header

    test_values = [0, 1, 100, 1024, 65536, 1024 * 1024]

    for recv_bytes in test_values:
        header = struct.pack(">Q", recv_bytes)

        # Verify header is exactly 8 bytes
        assert len(header) == 8

        # Verify it can be correctly parsed back
        parsed = struct.unpack(">Q", header)[0]
        assert parsed == recv_bytes
