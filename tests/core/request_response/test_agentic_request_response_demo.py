from __future__ import annotations

import time
from typing import cast

import pytest

from examples.request_response.agentic_protocol import (
    MAX_DATASET_METADATA_PAIRS,
    MAX_DECLARED_SIZE_BYTES,
    PROTOCOL_ID,
    REQUIRED_SESSION_PERMISSIONS,
    build_capability_query,
    build_store_intent,
    process_request,
)
from libp2p.request_response import JSONCodec, RequestResponse
from libp2p.tools.utils import connect
from tests.utils.factories import HostFactory


def _session_authorization(
    *,
    expires_at: int | None = None,
    permissions: list[str] | None = None,
) -> dict[str, object]:
    return {
        "mode": "session_key",
        "expires_at": expires_at if expires_at is not None else int(time.time()) + 3600,
        "permissions": permissions
        if permissions is not None
        else list(REQUIRED_SESSION_PERMISSIONS),
    }


def test_capability_query_returns_expected_shape() -> None:
    response = process_request(build_capability_query())

    assert response["type"] == "capability_response"
    assert response["protocol"] == str(PROTOCOL_ID)
    assert response["supported_tasks"] == ["store_intent"]
    assert response["auth"] == {
        "modes": ["root", "session_key"],
        "required_session_permissions": list(REQUIRED_SESSION_PERMISSIONS),
    }
    assert response["defaults"] == {"copies": 2, "with_cdn": False}


@pytest.mark.parametrize(
    ("message", "code"),
    (
        ({}, "invalid_request"),
        ({"type": 7}, "invalid_request"),
        ({"type": "unknown"}, "unsupported_request_type"),
    ),
)
def test_invalid_or_unknown_request_types_return_error(
    message: object, code: str
) -> None:
    response = process_request(message)

    assert response["type"] == "error"
    assert response["code"] == code


@pytest.mark.parametrize("declared_size_bytes", (126, MAX_DECLARED_SIZE_BYTES + 1))
def test_store_intent_rejects_out_of_range_size(declared_size_bytes: int) -> None:
    response = process_request(
        build_store_intent(
            task_id="task-size",
            content_label="hello.txt",
            declared_size_bytes=declared_size_bytes,
            authorization={"mode": "root"},
        )
    )

    errors = cast(list[str], response["errors"])
    assert response["status"] == "rejected"
    assert response["complete"] is False
    assert any("declared_size_bytes" in error for error in errors)


def test_store_intent_rejects_excess_dataset_metadata() -> None:
    dataset_metadata = {
        f"key-{index}": f"value-{index}"
        for index in range(MAX_DATASET_METADATA_PAIRS + 1)
    }

    response = process_request(
        build_store_intent(
            task_id="task-metadata",
            content_label="hello.txt",
            declared_size_bytes=256,
            dataset_metadata=dataset_metadata,
            authorization={"mode": "root"},
        )
    )

    errors = cast(list[str], response["errors"])
    assert response["status"] == "rejected"
    assert response["complete"] is False
    assert any("dataset_metadata" in error for error in errors)


def test_store_intent_rejects_expired_session_key() -> None:
    response = process_request(
        build_store_intent(
            task_id="task-expired",
            content_label="hello.txt",
            declared_size_bytes=256,
            authorization=_session_authorization(expires_at=int(time.time()) - 60),
        )
    )

    errors = cast(list[str], response["errors"])
    assert response["status"] == "rejected"
    assert any("expired" in error for error in errors)


def test_store_intent_rejects_missing_session_permissions() -> None:
    response = process_request(
        build_store_intent(
            task_id="task-perms",
            content_label="hello.txt",
            declared_size_bytes=256,
            authorization=_session_authorization(
                permissions=[REQUIRED_SESSION_PERMISSIONS[0]]
            ),
        )
    )

    errors = cast(list[str], response["errors"])
    assert response["status"] == "rejected"
    assert any("missing required permissions" in error for error in errors)


def test_store_intent_completes_with_two_copies() -> None:
    response = process_request(
        build_store_intent(
            task_id="task-complete",
            content_label="hello.txt",
            declared_size_bytes=256,
            copies=2,
            authorization={"mode": "root"},
        )
    )

    copies = cast(list[dict[str, object]], response["copies"])
    failed_attempts = cast(list[dict[str, object]], response["failed_attempts"])
    assert response["status"] == "complete"
    assert response["complete"] is True
    assert len(copies) == 2
    assert failed_attempts == []


def test_store_intent_returns_partial_result_with_three_copies() -> None:
    response = process_request(
        build_store_intent(
            task_id="task-partial",
            content_label="hello.txt",
            declared_size_bytes=256,
            copies=3,
            authorization={"mode": "root"},
        )
    )

    copies = cast(list[dict[str, object]], response["copies"])
    failed_attempts = cast(list[dict[str, object]], response["failed_attempts"])
    assert response["status"] == "partial"
    assert response["complete"] is False
    assert len(copies) == 2
    assert failed_attempts == [
        {
            "provider_id": 3,
            "role": "secondary",
            "error": "provider is unhealthy",
        }
    ]


@pytest.mark.trio
async def test_agentic_request_response_round_trip_integration(
    security_protocol,
) -> None:
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:
        rr_client = RequestResponse(hosts[0])
        rr_server = RequestResponse(hosts[1])

        async def handler(
            request: dict[str, object], context: object
        ) -> dict[str, object]:
            del context
            return process_request(request)

        rr_server.set_handler(PROTOCOL_ID, handler=handler, codec=JSONCodec())
        await connect(hosts[0], hosts[1])

        capability_response = await rr_client.send_request(
            peer_id=hosts[1].get_id(),
            protocol_ids=[PROTOCOL_ID],
            request=build_capability_query(),
            codec=JSONCodec(),
        )
        assert capability_response["type"] == "capability_response"

        task_id = "task-round-trip"
        store_result = await rr_client.send_request(
            peer_id=hosts[1].get_id(),
            protocol_ids=[PROTOCOL_ID],
            request=build_store_intent(
                task_id=task_id,
                content_label="hello.txt",
                declared_size_bytes=256,
                copies=3,
                authorization={"mode": "root"},
            ),
            codec=JSONCodec(),
        )

        copies = cast(list[dict[str, object]], store_result["copies"])
        failed_attempts = cast(list[dict[str, object]], store_result["failed_attempts"])
        assert store_result["task_id"] == task_id
        assert store_result["complete"] is False
        assert len(copies) == 2
        assert failed_attempts == [
            {
                "provider_id": 3,
                "role": "secondary",
                "error": "provider is unhealthy",
            }
        ]
