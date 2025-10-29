"""Tests focused on Circuit Relay v2 `_handle_stop_stream` behavior."""

import logging

import pytest
import trio

from libp2p.custom_types import TProtocol
from libp2p.relay.circuit_v2.protocol import CircuitV2Protocol
from libp2p.relay.circuit_v2.resources import RelayLimits
from libp2p.relay.circuit_v2.protocol import (
    DEFAULT_RELAY_LIMITS,
    PROTOCOL_ID,
    STOP_PROTOCOL_ID,
)
from libp2p.relay.circuit_v2.pb.circuit_pb2 import StopMessage, HopMessage
from libp2p.relay.circuit_v2.protocol_buffer import StatusCode
from libp2p.peer.peerstore import env_to_send_in_RPC
from libp2p.tools.async_service import background_trio_service
from libp2p.tools.constants import MAX_READ_LEN
from libp2p.tools.utils import connect
from tests.utils.factories import HostFactory


logger = logging.getLogger(__name__)


async def _read_msg(stream):
    data = await stream.read(MAX_READ_LEN)
    msg = StopMessage()
    msg.ParseFromString(data)
    return msg


@pytest.mark.trio
async def test_stop_handler_invalid_type_returns_malformed():
    async with HostFactory.create_batch_and_listen(2) as hosts:
        relay_host, dst_host = hosts

        protocol = CircuitV2Protocol(relay_host, DEFAULT_RELAY_LIMITS, allow_hop=True)
        async with background_trio_service(protocol):
            await protocol.event_started.wait()

            await connect(dst_host, relay_host)

            stream = await dst_host.new_stream(relay_host.get_id(), [STOP_PROTOCOL_ID])
            # Send STATUS instead of CONNECT
            bad = StopMessage(type=StopMessage.STATUS)
            await stream.write(bad.SerializeToString())

            resp = await _read_msg(stream)
            assert resp.type == StopMessage.STATUS
            assert getattr(resp.status, "code", None) == StatusCode.MALFORMED_MESSAGE

            await stream.close()


@pytest.mark.trio
async def test_stop_handler_unknown_peer_returns_connection_failed():
    async with HostFactory.create_batch_and_listen(3) as hosts:
        src_host, relay_host, dst_host = hosts

        protocol = CircuitV2Protocol(relay_host, DEFAULT_RELAY_LIMITS, allow_hop=True)
        async with background_trio_service(protocol):
            await protocol.event_started.wait()

            await connect(dst_host, relay_host)

            # Do NOT register in `_active_relays` to simulate unknown peer
            stream = await dst_host.new_stream(relay_host.get_id(), [STOP_PROTOCOL_ID])
            env_bytes, _ = env_to_send_in_RPC(dst_host)
            msg = StopMessage(
                type=StopMessage.CONNECT,
                peer=src_host.get_id().to_bytes(),
                senderRecord=env_bytes,
            )
            await stream.write(msg.SerializeToString())

            resp = await _read_msg(stream)
            assert getattr(resp.status, "code", None) == StatusCode.CONNECTION_FAILED

            await stream.close()


