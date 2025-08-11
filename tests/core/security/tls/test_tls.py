from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest


# Placeholder factory to satisfy static checks; real TLS wiring not implemented yet.
@asynccontextmanager
async def tls_conn_factory(nursery: Any) -> AsyncIterator[tuple[Any, Any]]:
    """Placeholder factory for TLS connection testing."""
    if False:  # pragma: no cover
        yield (None, None)
    raise NotImplementedError("TLS connection factory not implemented")


DATA_0 = b"hello"
DATA_1 = b"x" * 1500
DATA_2 = b"bye!"


@pytest.mark.trio
async def test_tls_transport(nursery):
    async with tls_conn_factory(nursery):
        # handshake succeeds if factory returns
        pass


@pytest.mark.trio
async def test_tls_connection(nursery):
    async with tls_conn_factory(nursery) as (local, remote):
        await local.write(DATA_0)
        await local.write(DATA_1)

        assert DATA_0 == await remote.read(len(DATA_0))
        assert DATA_1 == await remote.read(len(DATA_1))

        await local.write(DATA_2)
        assert DATA_2 == await remote.read(len(DATA_2))
