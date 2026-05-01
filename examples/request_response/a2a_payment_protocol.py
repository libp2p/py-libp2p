from __future__ import annotations

from collections.abc import Mapping

from libp2p.custom_types import TProtocol

from .a2a_payment_service import (
    CUSTOM_BINDING_URI,
    DEFAULT_COPIES,
    DEFAULT_LOCKUP_EPOCHS,
    DEFAULT_PAYMENT_RATE_USDFC_PER_EPOCH,
    A2APaymentTaskService,
)

PROTOCOL_ID = TProtocol("/example/a2a-filecoin-payment/1.0.0")


class A2APaymentDemoServer:
    """A JSON-RPC wrapper around the shared A2A payment task service."""

    def __init__(self, service: A2APaymentTaskService | None = None) -> None:
        self._service = service or A2APaymentTaskService()

    @property
    def service(self) -> A2APaymentTaskService:
        return self._service

    def process_request(self, envelope: object) -> dict[str, object]:
        if not isinstance(envelope, Mapping):
            return _jsonrpc_error_response(
                None, -32600, "Request payload validation error"
            )

        request_id = envelope.get("id")
        if envelope.get("jsonrpc") != "2.0":
            return _jsonrpc_error_response(request_id, -32600, "jsonrpc must be '2.0'")

        method = envelope.get("method")
        if not isinstance(method, str):
            return _jsonrpc_error_response(
                request_id, -32600, "method must be a string"
            )

        params = envelope.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, Mapping):
            return _jsonrpc_error_response(
                request_id, -32602, "params must be an object"
            )

        try:
            if method == "GetAgentCard":
                return _jsonrpc_result_response(
                    request_id,
                    self._service.build_agent_card(
                        interface_url=(
                            "libp2p://request-response/example/a2a-filecoin-payment"
                        ),
                        protocol_binding=CUSTOM_BINDING_URI,
                        streaming=False,
                    ),
                )
            if method == "SendMessage":
                message = params.get("message")
                if not isinstance(message, Mapping):
                    return _jsonrpc_error_response(
                        request_id, -32602, "message must be an object"
                    )
                return _jsonrpc_result_response(
                    request_id, {"task": self._service.send_message(message)}
                )
            if method == "GetTask":
                task_id = _optional_string(params, "id")
                if task_id is None:
                    return _jsonrpc_error_response(
                        request_id, -32602, "id must be a string"
                    )
                task = self._service.get_task(task_id)
                if task is None:
                    return _jsonrpc_error_response(request_id, -32001, "Task not found")
                return _jsonrpc_result_response(request_id, {"task": task})
            if method == "CancelTask":
                task_id = _optional_string(params, "id")
                if task_id is None:
                    return _jsonrpc_error_response(
                        request_id, -32602, "id must be a string"
                    )
                task = self._service.cancel_task(task_id)
                if task is None:
                    return _jsonrpc_error_response(request_id, -32001, "Task not found")
                return _jsonrpc_result_response(request_id, {"task": task})
            if method == "ListTasks":
                context_id = _optional_string(params, "contextId")
                status = _optional_string(params, "status")
                include_artifacts = params.get("includeArtifacts", True)
                if not isinstance(include_artifacts, bool):
                    return _jsonrpc_error_response(
                        request_id,
                        -32602,
                        "includeArtifacts must be a boolean",
                    )
                tasks = self._service.list_tasks(
                    context_id=context_id,
                    state=status,
                    include_artifacts=include_artifacts,
                )
                return _jsonrpc_result_response(
                    request_id,
                    {
                        "tasks": tasks,
                        "nextPageToken": "",
                        "pageSize": len(tasks),
                        "totalSize": len(tasks),
                    },
                )
        except KeyError:
            return _jsonrpc_error_response(request_id, -32001, "Task not found")
        except RuntimeError as exc:
            return _jsonrpc_error_response(request_id, -32004, str(exc))
        except ValueError as exc:
            message = str(exc)
            if message == "Task is not cancelable in its current state":
                return _jsonrpc_error_response(request_id, -32002, message)
            return _jsonrpc_error_response(request_id, -32602, message)

        return _jsonrpc_error_response(request_id, -32601, "Method not found")


def build_agent_card() -> dict[str, object]:
    service = A2APaymentTaskService()
    return service.build_agent_card(
        interface_url="libp2p://request-response/example/a2a-filecoin-payment",
        protocol_binding=CUSTOM_BINDING_URI,
        streaming=False,
    )


def build_get_agent_card_request(request_id: str = "agent-card") -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "GetAgentCard",
        "params": {},
    }


def build_get_task_request(*, request_id: str, task_id: str) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "GetTask",
        "params": {"id": task_id},
    }


def build_send_message_request(
    *,
    request_id: str,
    message_id: str,
    content_label: str,
    declared_size_bytes: int,
    copies: int = DEFAULT_COPIES,
    with_cdn: bool = False,
    payment_rate_usdfc_per_epoch: int = DEFAULT_PAYMENT_RATE_USDFC_PER_EPOCH,
    lockup_epochs: int = DEFAULT_LOCKUP_EPOCHS,
    payment_token: str = "USDFC",
) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": message_id,
                "role": "ROLE_USER",
                "parts": [
                    {
                        "data": {
                            "action": "store_data",
                            "contentLabel": content_label,
                            "declaredSizeBytes": declared_size_bytes,
                            "copies": copies,
                            "withCDN": with_cdn,
                            "paymentRateUsdfcPerEpoch": payment_rate_usdfc_per_epoch,
                            "lockupEpochs": lockup_epochs,
                            "paymentToken": payment_token,
                        },
                        "mediaType": "application/json",
                    }
                ],
            }
        },
    }


def build_authorization_followup_request(
    *,
    request_id: str,
    message_id: str,
    task_id: str,
    context_id: str,
    max_lockup_usdfc: int,
    payer: str,
    payment_token: str = "USDFC",
) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": message_id,
                "contextId": context_id,
                "taskId": task_id,
                "role": "ROLE_USER",
                "parts": [
                    {
                        "data": {
                            "paymentAuthorization": {
                                "approved": True,
                                "payer": payer,
                                "maxLockupUsdfc": max_lockup_usdfc,
                                "paymentToken": payment_token,
                            }
                        },
                        "mediaType": "application/json",
                    }
                ],
            }
        },
    }


def _jsonrpc_result_response(
    request_id: object, result: Mapping[str, object]
) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": dict(result),
    }


def _jsonrpc_error_response(
    request_id: object, code: int, message: str
) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


def _optional_string(message: Mapping[str, object], field_name: str) -> str | None:
    value = message.get(field_name)
    if isinstance(value, str) and value:
        return value
    return None
