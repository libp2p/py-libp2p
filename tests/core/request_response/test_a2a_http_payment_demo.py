from __future__ import annotations

import json
from typing import Any, cast

import pytest

from libp2p.filecoin.address import DEMO_F410_PAYER

a2a = pytest.importorskip("a2a")
httpx = pytest.importorskip("httpx")

from examples.request_response.a2a_http_payment_demo import (  # noqa: E402
    create_a2a_http_app,
)


def _jsonrpc_headers() -> dict[str, str]:
    return {"A2A-Version": "1.0", "Content-Type": "application/json"}


def _parse_sse_payloads(raw: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        payloads.append(json.loads(line.removeprefix("data: ")))
    return payloads


@pytest.mark.trio
async def test_agent_card_route_exposes_jsonrpc_interface() -> None:
    app = create_a2a_http_app(public_base_url="http://testserver")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.get("/.well-known/agent-card.json")

    assert response.status_code == 200
    body = response.json()
    interfaces = cast(list[dict[str, object]], body["supportedInterfaces"])
    assert interfaces[0]["protocolBinding"] == "JSONRPC"
    assert interfaces[0]["url"] == "http://testserver/rpc"


@pytest.mark.trio
async def test_send_message_over_jsonrpc_returns_auth_required_task() -> None:
    app = create_a2a_http_app(public_base_url="http://testserver")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/rpc",
            headers=_jsonrpc_headers(),
            json={
                "jsonrpc": "2.0",
                "id": "send-message",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "messageId": "msg-store-request",
                        "role": "ROLE_USER",
                        "parts": [
                            {
                                "data": {
                                    "action": "store_data",
                                    "contentLabel": "report.csv",
                                    "declaredSizeBytes": 256,
                                },
                                "mediaType": "application/json",
                            }
                        ],
                    }
                },
            },
        )

    assert response.status_code == 200
    task = response.json()["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_AUTH_REQUIRED"
    assert task["metadata"]["executionBackend"] == "simulation"


@pytest.mark.trio
async def test_streaming_followup_emits_working_artifacts_and_completion() -> None:
    app = create_a2a_http_app(public_base_url="http://testserver")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        initial = await client.post(
            "/rpc",
            headers=_jsonrpc_headers(),
            json={
                "jsonrpc": "2.0",
                "id": "send-message",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "messageId": "msg-store-request",
                        "role": "ROLE_USER",
                        "parts": [
                            {
                                "data": {
                                    "action": "store_data",
                                    "contentLabel": "hello.txt",
                                    "declaredSizeBytes": 256,
                                    "copies": 3,
                                },
                                "mediaType": "application/json",
                            }
                        ],
                    }
                },
            },
        )
        initial_task = initial.json()["result"]["task"]
        quote = initial_task["metadata"]["quote"]

        async with client.stream(
            "POST",
            "/rpc",
            headers=_jsonrpc_headers(),
            json={
                "jsonrpc": "2.0",
                "id": "stream-message",
                "method": "SendStreamingMessage",
                "params": {
                    "message": {
                        "messageId": "msg-authorize-payment",
                        "taskId": initial_task["id"],
                        "contextId": initial_task["contextId"],
                        "role": "ROLE_USER",
                        "parts": [
                            {
                                "data": {
                                    "paymentAuthorization": {
                                        "approved": True,
                                        "payer": DEMO_F410_PAYER,
                                        "maxLockupUsdfc": quote["depositNeededUsdfc"],
                                        "paymentToken": quote["paymentToken"],
                                    }
                                },
                                "mediaType": "application/json",
                            }
                        ],
                    }
                },
            },
        ) as stream_response:
            raw = await stream_response.aread()

    body = raw.decode()
    payloads = _parse_sse_payloads(body)
    assert len(payloads) == 4
    assert payloads[0]["result"]["task"]["status"]["state"] == "TASK_STATE_WORKING"
    assert (
        payloads[1]["result"]["artifactUpdate"]["artifact"]["artifactId"]
        == "payment-authorization"
    )
    assert (
        payloads[2]["result"]["artifactUpdate"]["artifact"]["artifactId"]
        == "storage-receipt"
    )
    assert (
        payloads[3]["result"]["statusUpdate"]["status"]["state"]
        == "TASK_STATE_COMPLETED"
    )
