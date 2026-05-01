from __future__ import annotations

from typing import cast

import pytest

from examples.request_response.a2a_payment_protocol import (
    CUSTOM_BINDING_URI,
    PROTOCOL_ID,
    A2APaymentDemoServer,
    build_authorization_followup_request,
    build_get_agent_card_request,
    build_get_task_request,
    build_send_message_request,
)
from libp2p.request_response import JSONCodec, RequestContext, RequestResponse
from libp2p.tools.utils import connect
from tests.utils.factories import HostFactory


@pytest.fixture
def server() -> A2APaymentDemoServer:
    return A2APaymentDemoServer()


def test_get_agent_card_returns_custom_binding(server: A2APaymentDemoServer) -> None:
    response = server.process_request(build_get_agent_card_request())

    result = cast(dict[str, object], response["result"])
    interfaces = cast(list[dict[str, object]], result["supportedInterfaces"])
    skills = cast(list[dict[str, object]], result["skills"])
    assert result["name"] == "py-libp2p A2A Filecoin Payment Demo Agent"
    assert interfaces[0]["protocolBinding"] == CUSTOM_BINDING_URI
    assert skills[0]["id"] == "filecoin-pay-store"


def test_send_message_creates_auth_required_task(server: A2APaymentDemoServer) -> None:
    response = server.process_request(
        build_send_message_request(
            request_id="send-message",
            message_id="msg-store-request",
            content_label="report.csv",
            declared_size_bytes=256,
        )
    )

    task = cast(dict[str, object], cast(dict[str, object], response["result"])["task"])
    status = cast(dict[str, object], task["status"])
    metadata = cast(dict[str, object], task["metadata"])
    quote = cast(dict[str, object], metadata["quote"])
    assert status["state"] == "TASK_STATE_AUTH_REQUIRED"
    assert quote["paymentToken"] == "USDFC"
    assert quote["depositNeededUsdfc"] == 5766


def test_authorization_followup_completes_task(server: A2APaymentDemoServer) -> None:
    initial_response = server.process_request(
        build_send_message_request(
            request_id="send-message",
            message_id="msg-store-request",
            content_label="report.csv",
            declared_size_bytes=256,
        )
    )
    initial_task = cast(
        dict[str, object], cast(dict[str, object], initial_response["result"])["task"]
    )
    quote = cast(
        dict[str, object], cast(dict[str, object], initial_task["metadata"])["quote"]
    )
    task_id = cast(str, initial_task["id"])
    context_id = cast(str, initial_task["contextId"])
    quoted_lockup = cast(int, quote["depositNeededUsdfc"])

    followup_response = server.process_request(
        build_authorization_followup_request(
            request_id="authorize-payment",
            message_id="msg-authorize-payment",
            task_id=task_id,
            context_id=context_id,
            max_lockup_usdfc=quoted_lockup,
            payer="f410-test-payer",
        )
    )

    task = cast(
        dict[str, object], cast(dict[str, object], followup_response["result"])["task"]
    )
    status = cast(dict[str, object], task["status"])
    artifacts = cast(list[dict[str, object]], task["artifacts"])
    storage_part = cast(dict[str, object], artifacts[1]["parts"][0])
    storage_data = cast(dict[str, object], storage_part["data"])
    assert status["state"] == "TASK_STATE_COMPLETED"
    assert artifacts[0]["artifactId"] == "payment-authorization"
    assert artifacts[1]["artifactId"] == "storage-receipt"
    assert storage_data["complete"] is True
    assert len(cast(list[dict[str, object]], storage_data["copies"])) == 2


def test_underfunded_authorization_keeps_task_in_auth_required(
    server: A2APaymentDemoServer,
) -> None:
    initial_response = server.process_request(
        build_send_message_request(
            request_id="send-message",
            message_id="msg-store-request",
            content_label="report.csv",
            declared_size_bytes=256,
        )
    )
    initial_task = cast(
        dict[str, object], cast(dict[str, object], initial_response["result"])["task"]
    )
    task_id = cast(str, initial_task["id"])
    context_id = cast(str, initial_task["contextId"])

    followup_response = server.process_request(
        build_authorization_followup_request(
            request_id="authorize-payment",
            message_id="msg-authorize-payment",
            task_id=task_id,
            context_id=context_id,
            max_lockup_usdfc=1,
            payer="f410-test-payer",
        )
    )

    task = cast(
        dict[str, object], cast(dict[str, object], followup_response["result"])["task"]
    )
    status = cast(dict[str, object], task["status"])
    status_message = cast(dict[str, object], status["message"])
    status_parts = cast(list[dict[str, object]], status_message["parts"])
    assert status["state"] == "TASK_STATE_AUTH_REQUIRED"
    assert "maxLockupUsdfc" in cast(str, status_parts[0]["text"])


@pytest.mark.trio
async def test_a2a_payment_round_trip_integration(security_protocol) -> None:
    server = A2APaymentDemoServer()
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:
        rr_client = RequestResponse(hosts[0])
        rr_server = RequestResponse(hosts[1])

        async def handler(
            request: dict[str, object], context: RequestContext
        ) -> dict[str, object]:
            del context
            return server.process_request(request)

        rr_server.set_handler(PROTOCOL_ID, handler=handler, codec=JSONCodec())
        await connect(hosts[0], hosts[1])

        card_response = await rr_client.send_request(
            peer_id=hosts[1].get_id(),
            protocol_ids=[PROTOCOL_ID],
            request=build_get_agent_card_request(),
            codec=JSONCodec(),
        )
        card_result = cast(dict[str, object], card_response["result"])
        assert card_result["name"] == "py-libp2p A2A Filecoin Payment Demo Agent"

        initial_response = await rr_client.send_request(
            peer_id=hosts[1].get_id(),
            protocol_ids=[PROTOCOL_ID],
            request=build_send_message_request(
                request_id="send-message",
                message_id="msg-store-request",
                content_label="hello.txt",
                declared_size_bytes=256,
                copies=3,
            ),
            codec=JSONCodec(),
        )
        initial_task = cast(
            dict[str, object],
            cast(dict[str, object], initial_response["result"])["task"],
        )
        quote = cast(
            dict[str, object],
            cast(dict[str, object], initial_task["metadata"])["quote"],
        )

        followup_response = await rr_client.send_request(
            peer_id=hosts[1].get_id(),
            protocol_ids=[PROTOCOL_ID],
            request=build_authorization_followup_request(
                request_id="authorize-payment",
                message_id="msg-authorize-payment",
                task_id=cast(str, initial_task["id"]),
                context_id=cast(str, initial_task["contextId"]),
                max_lockup_usdfc=cast(int, quote["depositNeededUsdfc"]),
                payer="f410-test-payer",
            ),
            codec=JSONCodec(),
        )
        final_task = cast(
            dict[str, object],
            cast(dict[str, object], followup_response["result"])["task"],
        )
        status = cast(dict[str, object], final_task["status"])
        storage_receipt = cast(list[dict[str, object]], final_task["artifacts"])[1]
        storage_data = cast(
            dict[str, object],
            cast(list[dict[str, object]], storage_receipt["parts"])[0]["data"],
        )

        assert status["state"] == "TASK_STATE_COMPLETED"
        assert storage_data["complete"] is False
        assert len(cast(list[dict[str, object]], storage_data["copies"])) == 2
        assert cast(list[dict[str, object]], storage_data["failedAttempts"]) == [
            {
                "providerId": 3,
                "role": "secondary",
                "error": "provider is unhealthy",
            }
        ]

        fetched_response = await rr_client.send_request(
            peer_id=hosts[1].get_id(),
            protocol_ids=[PROTOCOL_ID],
            request=build_get_task_request(
                request_id="get-task", task_id=cast(str, initial_task["id"])
            ),
            codec=JSONCodec(),
        )
        fetched_task = cast(
            dict[str, object],
            cast(dict[str, object], fetched_response["result"])["task"],
        )
        fetched_status = cast(dict[str, object], fetched_task["status"])
        assert fetched_status["state"] == "TASK_STATE_COMPLETED"
