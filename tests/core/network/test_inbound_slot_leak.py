"""
Regression tests for the inbound-connection limiter slot leak.

The inbound ``trio.CapacityLimiter`` used to release its token only when the
inbound handler returned — but a registered connection keeps its handler alive
until swarm shutdown.  Every inbound connection that ever closed therefore
leaked one slot permanently.  After ``max_connections - min_connections``
cumulative inbound connections the limiter saturated and every new inbound
connection was rejected *after* the transport handshake had succeeded
(symptom: remote peer "connects" then drops a few seconds later).

The fix transfers slot ownership to a per-connection waiter that releases it
as soon as ``SwarmConn.event_closed`` fires.
"""

from contextlib import AsyncExitStack

import pytest
from multiaddr import Multiaddr
import trio
from trio.testing import wait_all_tasks_blocked

from libp2p import new_swarm
from libp2p.network.config import ConnectionConfig
from libp2p.tools.anyio_service import background_trio_service
from libp2p.tools.utils import connect_swarm

pytestmark = pytest.mark.trio


def _server_conn_config() -> ConnectionConfig:
    # Small inbound cap so the test can exhaust it quickly:
    # cap = max_connections - min_connections = 3
    return ConnectionConfig(
        max_connections=4,
        min_connections=1,
        low_watermark=1,
        high_watermark=4,
        max_connections_per_peer=8,
        auto_connect_interval=3600.0,
    )


async def _disconnect_from_server(server_swarm, client_swarm) -> None:
    """Close every connection between client and server from the client side."""
    server_peer_id = server_swarm.get_peer_id()
    conns = list(client_swarm.connections.get(server_peer_id, []))
    for conn in conns:
        await conn.close()


@pytest.mark.parametrize("num_clients", [3])
async def test_inbound_slots_released_after_connection_close(num_clients):
    """Sequential connect/disconnect churn must not exhaust inbound slots."""
    server_swarm = new_swarm(connection_config=_server_conn_config())
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(background_trio_service(server_swarm))
        await server_swarm.listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))

        limiter = server_swarm._inbound_limiter
        cap = int(limiter.total_tokens)
        assert cap == 3

        clients = []
        for _ in range(num_clients):
            client = new_swarm()
            await stack.enter_async_context(background_trio_service(client))
            await client.listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
            clients.append(client)

        if True:
            for round_num in range(3):
                for client in clients:
                    await connect_swarm(client, server_swarm)

                live = len(
                    [
                        c
                        for peer_conns in server_swarm.connections.values()
                        for c in peer_conns
                    ]
                )
                assert live == num_clients

                await wait_all_tasks_blocked()

                borrowed_with_live_conns = int(limiter.borrowed_tokens)
                assert borrowed_with_live_conns == num_clients, (
                    f"round {round_num}: expected {num_clients} slots held "
                    f"for {num_clients} live connections, got "
                    f"{borrowed_with_live_conns}"
                )

                for client in clients:
                    await _disconnect_from_server(server_swarm, client)

                await wait_all_tasks_blocked()
                await trio.sleep(0.05)
                await wait_all_tasks_blocked()

                borrowed_after_close = int(limiter.borrowed_tokens)
                assert borrowed_after_close == 0, (
                    f"round {round_num}: inbound slots leaked! "
                    f"{borrowed_after_close}/{cap} slots still held after all "
                    "connections closed"
                )
                assert int(limiter.available_tokens) == cap


async def test_new_inbound_accepted_after_previous_peers_disconnect():
    """
    A fresh peer must be able to connect after others churned through.

    With the leak, cumulative inbound connections (even long-since closed)
    permanently consumed slots; once ``cap`` was reached every subsequent
    inbound connection was rejected post-handshake.
    """
    server_swarm = new_swarm(connection_config=_server_conn_config())
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(background_trio_service(server_swarm))
        await server_swarm.listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))

        limiter = server_swarm._inbound_limiter

        churn_client = new_swarm()
        await stack.enter_async_context(background_trio_service(churn_client))
        await churn_client.listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))

        final_client = new_swarm()
        await stack.enter_async_context(background_trio_service(final_client))
        await final_client.listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))

        if True:
            # Burn through more connect/disconnect cycles than the cap (3).
            for i in range(6):
                await connect_swarm(churn_client, server_swarm)
                assert len(server_swarm.connections) > 0
                await _disconnect_from_server(server_swarm, churn_client)
                await wait_all_tasks_blocked()
                await trio.sleep(0.02)
                await wait_all_tasks_blocked()
                assert int(limiter.borrowed_tokens) == 0, (
                    f"cycle {i}: slots leaked ({limiter.borrowed_tokens} held)"
                )

            # The cap has been exceeded cumulatively (6 > 3).  A brand-new
            # peer must still be able to connect.
            await connect_swarm(final_client, server_swarm)
            assert server_swarm.get_peer_id() in final_client.connections, (
                "fresh peer rejected after prior peers churned — slots leaked"
            )
