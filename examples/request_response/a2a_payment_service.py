from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import time
from typing import Final, Protocol

CUSTOM_BINDING_URI: Final = "https://libp2p.io/bindings/libp2p-request-response/v1"
DEFAULT_PAYMENT_TOKEN: Final = "USDFC"
DEFAULT_PAYMENT_RATE_USDFC_PER_EPOCH: Final = 1
DEFAULT_LOCKUP_EPOCHS: Final = 2880
DEFAULT_COPIES: Final = 2
DEFAULT_WITH_CDN: Final = False
MIN_DECLARED_SIZE_BYTES: Final = 127
MAX_DECLARED_SIZE_BYTES: Final = 1_065_353_216
MAX_COPIES: Final = 3

PROVIDER_CATALOG: Final[tuple[dict[str, object], ...]] = (
    {
        "provider_id": 1,
        "name": "warm-storage-primary",
        "role": "primary",
        "healthy": True,
        "operator_id": "fwss-primary",
    },
    {
        "provider_id": 2,
        "name": "warm-storage-secondary",
        "role": "secondary",
        "healthy": True,
        "operator_id": "fwss-secondary",
    },
    {
        "provider_id": 3,
        "name": "warm-storage-draining",
        "role": "secondary",
        "healthy": False,
        "operator_id": "fwss-draining",
    },
)


class StorageExecutionBackend(Protocol):
    name: str

    def prepare_quote(
        self,
        *,
        task_id: str,
        request_payload: Mapping[str, object],
        base_quote: Mapping[str, object],
    ) -> Mapping[str, object] | None: ...

    def execute_storage(
        self,
        *,
        request_payload: Mapping[str, object],
        quote: Mapping[str, object],
        payment_authorization: Mapping[str, object],
    ) -> dict[str, object]: ...


@dataclass(slots=True)
class _TaskRecord:
    task_id: str
    context_id: str
    request_payload: dict[str, object]
    quote: dict[str, object]
    task: dict[str, object]
    history: list[dict[str, object]] = field(default_factory=list)


class SimulatedStorageBackend:
    name = "simulation"

    def prepare_quote(
        self,
        *,
        task_id: str,
        request_payload: Mapping[str, object],
        base_quote: Mapping[str, object],
    ) -> Mapping[str, object] | None:
        del task_id, request_payload, base_quote
        return None

    def execute_storage(
        self,
        *,
        request_payload: Mapping[str, object],
        quote: Mapping[str, object],
        payment_authorization: Mapping[str, object],
    ) -> dict[str, object]:
        del payment_authorization
        return _build_simulated_storage_result(request_payload, quote)


class A2APaymentTaskService:
    """Shared task service used by both libp2p and HTTP A2A entrypoints."""

    def __init__(
        self, execution_backend: StorageExecutionBackend | None = None
    ) -> None:
        self._tasks: dict[str, _TaskRecord] = {}
        self._execution_backend = execution_backend or SimulatedStorageBackend()

    @property
    def execution_backend_name(self) -> str:
        return self._execution_backend.name

    def build_agent_card(
        self,
        *,
        interface_url: str,
        protocol_binding: str,
        streaming: bool,
    ) -> dict[str, object]:
        return {
            "name": "py-libp2p A2A Filecoin Payment Demo Agent",
            "description": (
                "A local demo agent that models A2A task semantics for Filecoin-style "
                "payment approval and storage execution on top of py-libp2p."
            ),
            "version": "0.2.0",
            "documentationUrl": "https://github.com/libp2p/py-libp2p",
            "capabilities": {
                "streaming": streaming,
                "pushNotifications": False,
                "extendedAgentCard": False,
            },
            "supportedInterfaces": [
                {
                    "url": interface_url,
                    "protocolBinding": protocol_binding,
                    "protocolVersion": "1.0",
                }
            ],
            "defaultInputModes": ["application/json"],
            "defaultOutputModes": ["application/json", "text/plain"],
            "skills": [
                {
                    "id": "filecoin-pay-store",
                    "name": "Quote, authorize, and store data",
                    "description": (
                        "Produces a Filecoin Pay-style quote, waits for payment "
                        "authorization, and then returns a storage receipt artifact."
                    ),
                    "tags": [
                        "filecoin",
                        "payments",
                        "storage",
                        "a2a",
                        "agentic",
                    ],
                    "examples": [
                        "Quote and store report.csv with two copies",
                        "Authorize a USDFC rail and then commit a storage task",
                    ],
                    "inputModes": ["application/json"],
                    "outputModes": ["application/json", "text/plain"],
                }
            ],
        }

    def send_message(self, message: Mapping[str, object]) -> dict[str, object]:
        role = message.get("role")
        if role != "ROLE_USER":
            raise ValueError("message.role must be ROLE_USER")

        payload = _extract_payload(message)
        if payload is None:
            raise ValueError("message must include one application/json data part")

        task_id = _optional_string(message, "taskId")
        if task_id is None:
            return self._create_task_from_message(message, payload)
        return self._continue_task(task_id, message, payload)

    def get_task(self, task_id: str) -> dict[str, object] | None:
        record = self._tasks.get(task_id)
        if record is None:
            return None
        return _copy_message(record.task)

    def list_tasks(
        self,
        *,
        context_id: str | None = None,
        state: str | None = None,
        include_artifacts: bool = True,
    ) -> list[dict[str, object]]:
        tasks: list[dict[str, object]] = []
        for record in self._tasks.values():
            task = record.task
            if context_id and task.get("contextId") != context_id:
                continue
            task_state = task.get("status", {}).get("state")
            if state and task_state != state:
                continue
            task_copy = _copy_message(task)
            if not include_artifacts:
                task_copy.pop("artifacts", None)
            tasks.append(task_copy)
        tasks.sort(
            key=lambda task: str(task.get("status", {}).get("timestamp", "")),
            reverse=True,
        )
        return tasks

    def cancel_task(self, task_id: str) -> dict[str, object] | None:
        record = self._tasks.get(task_id)
        if record is None:
            return None

        state = record.task["status"]["state"]
        if state in (
            "TASK_STATE_COMPLETED",
            "TASK_STATE_FAILED",
            "TASK_STATE_CANCELED",
            "TASK_STATE_REJECTED",
        ):
            raise ValueError("Task is not cancelable in its current state")

        record.task["status"] = {
            "state": "TASK_STATE_CANCELED",
            "message": _agent_text_message(
                text="Task canceled before payment authorization completed.",
                context_id=record.context_id,
                task_id=record.task_id,
            ),
            "timestamp": _timestamp_now(),
        }
        return _copy_message(record.task)

    def build_streaming_working_task(
        self,
        *,
        task_id: str,
        context_id: str,
        message: str,
    ) -> dict[str, object]:
        record = self._tasks.get(task_id)
        if record is None:
            raise KeyError(task_id)
        task = _copy_message(record.task)
        task["status"] = {
            "state": "TASK_STATE_WORKING",
            "message": _agent_text_message(
                text=message,
                context_id=context_id,
                task_id=task_id,
            ),
            "timestamp": _timestamp_now(),
        }
        return task

    def _create_task_from_message(
        self,
        message: Mapping[str, object],
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        action = payload.get("action")
        if action != "store_data":
            raise ValueError("action must be 'store_data' for this demo")

        request_payload, errors = normalize_store_request(payload)
        if errors:
            raise ValueError("; ".join(errors))

        content_label = request_payload["contentLabel"]
        declared_size_bytes = request_payload["declaredSizeBytes"]
        copies = request_payload["copies"]
        with_cdn = request_payload["withCDN"]
        payment_rate = request_payload["paymentRateUsdfcPerEpoch"]
        lockup_epochs = request_payload["lockupEpochs"]
        token = request_payload["paymentToken"]
        if not isinstance(content_label, str):
            raise TypeError("contentLabel must be a string")
        if not isinstance(declared_size_bytes, int):
            raise TypeError("declaredSizeBytes must be an integer")
        if not isinstance(copies, int):
            raise TypeError("copies must be an integer")
        if not isinstance(with_cdn, bool):
            raise TypeError("withCDN must be a boolean")
        if not isinstance(payment_rate, int):
            raise TypeError("paymentRateUsdfcPerEpoch must be an integer")
        if not isinstance(lockup_epochs, int):
            raise TypeError("lockupEpochs must be an integer")
        if not isinstance(token, str):
            raise TypeError("paymentToken must be a string")

        task_id = task_id_from_payload(request_payload)
        context_id = context_id_from_task_id(task_id)
        quote = build_payment_quote(
            task_id=task_id,
            content_label=content_label,
            declared_size_bytes=declared_size_bytes,
            copies=copies,
            payment_rate_usdfc_per_epoch=payment_rate,
            lockup_epochs=lockup_epochs,
            payment_token=token,
            execution_backend=self._execution_backend.name,
        )
        backend_quote = self._execution_backend.prepare_quote(
            task_id=task_id,
            request_payload=request_payload,
            base_quote=quote,
        )
        if backend_quote:
            quote["backendQuote"] = json.loads(json.dumps(backend_quote))

        auth_message = _agent_text_message(
            text=(
                "Authorize a Filecoin Pay rail to continue. "
                f"depositNeeded={quote['depositNeededUsdfc']} {quote['paymentToken']}, "
                f"streamingLockup={quote['streamingLockupUsdfc']} "
                f"{quote['paymentToken']}, "
                f"fixedLockup={quote['fixedLockupUsdfc']} {quote['paymentToken']}."
            ),
            context_id=context_id,
            task_id=task_id,
        )
        task = {
            "id": task_id,
            "contextId": context_id,
            "status": {
                "state": "TASK_STATE_AUTH_REQUIRED",
                "message": auth_message,
                "timestamp": _timestamp_now(),
            },
            "history": [_copy_message(message)],
            "metadata": {
                "quote": quote,
                "customBinding": CUSTOM_BINDING_URI,
                "executionBackend": self._execution_backend.name,
                "notes": [
                    "This demo models A2A task semantics over py-libp2p.",
                    (
                        "The payment quote mirrors Filecoin Pay concepts: "
                        "payment rail, lockup, and operator approval."
                    ),
                ],
            },
        }
        self._tasks[task_id] = _TaskRecord(
            task_id=task_id,
            context_id=context_id,
            request_payload=request_payload,
            quote=quote,
            task=task,
            history=[_copy_message(message)],
        )
        return _copy_message(task)

    def _continue_task(
        self,
        task_id: str,
        message: Mapping[str, object],
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        record = self._tasks.get(task_id)
        if record is None:
            raise KeyError("Task not found")

        state = record.task["status"]["state"]
        if state in (
            "TASK_STATE_COMPLETED",
            "TASK_STATE_FAILED",
            "TASK_STATE_CANCELED",
            "TASK_STATE_REJECTED",
        ):
            raise RuntimeError("Messages sent to terminal tasks are not supported")

        record.history.append(_copy_message(message))
        record.task["history"] = list(record.history)

        payment_authorization = payload.get("paymentAuthorization")
        if not isinstance(payment_authorization, Mapping):
            record.task["status"] = {
                "state": "TASK_STATE_AUTH_REQUIRED",
                "message": _agent_text_message(
                    text="Payment authorization is still required to continue.",
                    context_id=record.context_id,
                    task_id=record.task_id,
                ),
                "timestamp": _timestamp_now(),
            }
            return _copy_message(record.task)

        auth_errors = validate_payment_authorization(
            payment_authorization, record.quote
        )
        if auth_errors:
            record.task["status"] = {
                "state": "TASK_STATE_AUTH_REQUIRED",
                "message": _agent_text_message(
                    text="Authorization rejected: " + "; ".join(auth_errors),
                    context_id=record.context_id,
                    task_id=record.task_id,
                ),
                "timestamp": _timestamp_now(),
            }
            return _copy_message(record.task)

        storage_result = self._execution_backend.execute_storage(
            request_payload=record.request_payload,
            quote=record.quote,
            payment_authorization=payment_authorization,
        )
        storage_artifact = build_storage_artifact(storage_result)
        payment_artifact = build_payment_artifact(record.quote, payment_authorization)
        piece_cid = storage_result["pieceCid"]
        complete = storage_result["complete"]
        if not isinstance(piece_cid, str):
            raise TypeError("pieceCid must be a string")
        if not isinstance(complete, bool):
            raise TypeError("complete must be a boolean")

        record.task = {
            "id": record.task_id,
            "contextId": record.context_id,
            "status": {
                "state": "TASK_STATE_COMPLETED",
                "message": _agent_text_message(
                    text=(
                        (
                            "Payment rail approved and storage task "
                            f"completed for {piece_cid}."
                        )
                        if complete
                        else (
                            "Payment rail approved and storage task completed "
                            "with partial provider fulfilment for "
                            f"{piece_cid}."
                        )
                    ),
                    context_id=record.context_id,
                    task_id=record.task_id,
                ),
                "timestamp": _timestamp_now(),
            },
            "history": list(record.history),
            "artifacts": [payment_artifact, storage_artifact],
            "metadata": {
                "quote": record.quote,
                "paymentAuthorization": dict(payment_authorization),
                "executionBackend": self._execution_backend.name,
                "customBinding": CUSTOM_BINDING_URI,
            },
        }
        return _copy_message(record.task)


def normalize_store_request(
    payload: Mapping[str, object],
) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []

    content_label = payload.get("contentLabel")
    if not isinstance(content_label, str) or not content_label:
        errors.append("contentLabel must be a non-empty string")

    declared_size_bytes = _coerce_json_int(payload.get("declaredSizeBytes"))
    if declared_size_bytes is None:
        errors.append("declaredSizeBytes must be an integer")
    elif not (
        MIN_DECLARED_SIZE_BYTES <= declared_size_bytes <= MAX_DECLARED_SIZE_BYTES
    ):
        errors.append(
            "declaredSizeBytes must be between "
            f"{MIN_DECLARED_SIZE_BYTES} and {MAX_DECLARED_SIZE_BYTES}"
        )

    copies = _coerce_json_int(payload.get("copies", DEFAULT_COPIES))
    if copies is None:
        errors.append("copies must be an integer")
    elif not (1 <= copies <= MAX_COPIES):
        errors.append(f"copies must be between 1 and {MAX_COPIES}")

    with_cdn = payload.get("withCDN", DEFAULT_WITH_CDN)
    if not isinstance(with_cdn, bool):
        errors.append("withCDN must be a boolean")

    payment_rate = _coerce_json_int(
        payload.get("paymentRateUsdfcPerEpoch", DEFAULT_PAYMENT_RATE_USDFC_PER_EPOCH)
    )
    if payment_rate is None or payment_rate <= 0:
        errors.append("paymentRateUsdfcPerEpoch must be a positive integer")

    lockup_epochs = _coerce_json_int(payload.get("lockupEpochs", DEFAULT_LOCKUP_EPOCHS))
    if lockup_epochs is None or lockup_epochs <= 0:
        errors.append("lockupEpochs must be a positive integer")

    payment_token = payload.get("paymentToken", DEFAULT_PAYMENT_TOKEN)
    if not isinstance(payment_token, str) or not payment_token:
        errors.append("paymentToken must be a non-empty string")

    return (
        {
            "contentLabel": content_label,
            "declaredSizeBytes": declared_size_bytes,
            "copies": copies,
            "withCDN": with_cdn,
            "paymentRateUsdfcPerEpoch": payment_rate,
            "lockupEpochs": lockup_epochs,
            "paymentToken": payment_token,
        },
        errors,
    )


def build_payment_quote(
    *,
    task_id: str,
    content_label: str,
    declared_size_bytes: int,
    copies: int,
    payment_rate_usdfc_per_epoch: int,
    lockup_epochs: int,
    payment_token: str,
    execution_backend: str,
) -> dict[str, object]:
    fixed_lockup = (
        max(
            1,
            (declared_size_bytes + MIN_DECLARED_SIZE_BYTES - 1)
            // MIN_DECLARED_SIZE_BYTES,
        )
        * copies
    )
    streaming_lockup = payment_rate_usdfc_per_epoch * lockup_epochs * copies
    deposit_needed = fixed_lockup + streaming_lockup
    rail_id = f"rail-{stable_digest(content_label, declared_size_bytes, copies)[:10]}"
    return {
        "railId": rail_id,
        "taskId": task_id,
        "paymentToken": payment_token,
        "paymentRateUsdfcPerEpoch": payment_rate_usdfc_per_epoch,
        "lockupEpochs": lockup_epochs,
        "streamingLockupUsdfc": streaming_lockup,
        "fixedLockupUsdfc": fixed_lockup,
        "depositNeededUsdfc": deposit_needed,
        "operator": "fwss-operator",
        "validator": "pdp-validator",
        "service": "warm-storage",
        "executionBackend": execution_backend,
    }


def build_payment_artifact(
    quote: Mapping[str, object], authorization: Mapping[str, object]
) -> dict[str, object]:
    return {
        "artifactId": "payment-authorization",
        "name": "Filecoin Pay authorization",
        "description": "Approved payment rail details for the storage task.",
        "parts": [
            {
                "data": {
                    "railId": quote["railId"],
                    "paymentToken": quote["paymentToken"],
                    "depositNeededUsdfc": quote["depositNeededUsdfc"],
                    "streamingLockupUsdfc": quote["streamingLockupUsdfc"],
                    "fixedLockupUsdfc": quote["fixedLockupUsdfc"],
                    "payer": authorization["payer"],
                    "approved": authorization["approved"],
                },
                "mediaType": "application/json",
            }
        ],
    }


def build_storage_artifact(storage_result: Mapping[str, object]) -> dict[str, object]:
    return {
        "artifactId": "storage-receipt",
        "name": "Storage receipt",
        "description": "Storage result for the authorized task.",
        "parts": [
            {
                "data": json.loads(json.dumps(storage_result)),
                "mediaType": "application/json",
            }
        ],
    }


def validate_payment_authorization(
    authorization: Mapping[str, object], quote: Mapping[str, object]
) -> list[str]:
    errors: list[str] = []
    approved = authorization.get("approved")
    payer = authorization.get("payer")
    max_lockup_usdfc = _coerce_json_int(authorization.get("maxLockupUsdfc"))
    payment_token = authorization.get("paymentToken")

    if approved is not True:
        errors.append("approved must be true")
    if not isinstance(payer, str) or not payer:
        errors.append("payer must be a non-empty string")
    if max_lockup_usdfc is None:
        errors.append("maxLockupUsdfc must be an integer")
    elif max_lockup_usdfc < quote["depositNeededUsdfc"]:
        errors.append(f"maxLockupUsdfc must be at least {quote['depositNeededUsdfc']}")
    if payment_token != quote["paymentToken"]:
        errors.append("paymentToken must match the quoted token")
    return errors


def extract_payload(message: Mapping[str, object]) -> Mapping[str, object] | None:
    return _extract_payload(message)


def task_id_from_payload(payload: Mapping[str, object]) -> str:
    return f"task-{stable_digest(payload, separators=True)[:10]}"


def context_id_from_task_id(task_id: str) -> str:
    return f"ctx-{task_id.removeprefix('task-')}"


def stable_digest(*parts: object, separators: bool = False) -> str:
    if len(parts) == 1 and isinstance(parts[0], Mapping):
        payload = json.dumps(
            parts[0], sort_keys=True, separators=(",", ":") if separators else None
        )
    else:
        payload = ":".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def timestamp_now() -> str:
    return _timestamp_now()


def _build_simulated_storage_result(
    request_payload: Mapping[str, object], quote: Mapping[str, object]
) -> dict[str, object]:
    content_label = request_payload["contentLabel"]
    declared_size_bytes = request_payload["declaredSizeBytes"]
    copies = request_payload["copies"]
    with_cdn = request_payload["withCDN"]
    if not isinstance(content_label, str):
        raise TypeError("contentLabel must be a string")
    if not isinstance(declared_size_bytes, int):
        raise TypeError("declaredSizeBytes must be an integer")
    if not isinstance(copies, int):
        raise TypeError("copies must be an integer")
    if not isinstance(with_cdn, bool):
        raise TypeError("withCDN must be a boolean")

    piece_cid = _make_piece_cid(content_label, declared_size_bytes, copies, with_cdn)
    successful_copies: list[dict[str, object]] = []
    failed_attempts: list[dict[str, object]] = []
    for provider in PROVIDER_CATALOG[:copies]:
        provider_id = provider["provider_id"]
        role = provider["role"]
        healthy = provider["healthy"]
        operator_id = provider["operator_id"]
        if not isinstance(provider_id, int):
            raise TypeError("provider_id must be an integer")
        if not isinstance(role, str):
            raise TypeError("role must be a string")
        if not isinstance(healthy, bool):
            raise TypeError("healthy must be a boolean")
        if not isinstance(operator_id, str):
            raise TypeError("operator_id must be a string")
        if not healthy:
            failed_attempts.append(
                {
                    "providerId": provider_id,
                    "role": role,
                    "error": "provider is unhealthy",
                }
            )
            continue
        successful_copies.append(
            {
                "providerId": provider_id,
                "operatorId": operator_id,
                "pieceId": _stable_int("piece", piece_cid, provider_id),
                "dataSetId": _stable_int("dataset", piece_cid, provider_id),
                "retrievalUrl": (
                    f"https://provider-{provider_id}.invalid/pieces/{piece_cid}"
                ),
                "role": role,
            }
        )

    complete = len(successful_copies) == copies
    return {
        "pieceCid": piece_cid,
        "contentLabel": content_label,
        "declaredSizeBytes": declared_size_bytes,
        "requestedCopies": copies,
        "complete": complete,
        "copies": successful_copies,
        "failedAttempts": failed_attempts,
        "withCDN": with_cdn,
        "railId": quote["railId"],
        "executionBackend": "simulation",
    }


def _extract_payload(message: Mapping[str, object]) -> Mapping[str, object] | None:
    parts = message.get("parts")
    if not isinstance(parts, list) or not parts:
        return None
    part = parts[0]
    if not isinstance(part, Mapping):
        return None
    if part.get("mediaType") != "application/json":
        return None
    data = part.get("data")
    if not isinstance(data, Mapping):
        return None
    return data


def _make_piece_cid(
    content_label: str,
    declared_size_bytes: int,
    copies: int,
    with_cdn: bool,
) -> str:
    payload = {
        "contentLabel": content_label,
        "declaredSizeBytes": declared_size_bytes,
        "copies": copies,
        "withCDN": with_cdn,
    }
    return f"simulated-bafkzcib-{stable_digest(payload, separators=True)[:32]}"


def _stable_int(kind: str, piece_cid: str, provider_id: int) -> int:
    digest = hashlib.sha256(f"{kind}:{piece_cid}:{provider_id}".encode()).digest()
    return int.from_bytes(digest[:6], byteorder="big")


def _timestamp_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _agent_text_message(
    *, text: str, context_id: str, task_id: str
) -> dict[str, object]:
    return {
        "messageId": f"msg-{stable_digest(text, context_id, task_id)[:12]}",
        "contextId": context_id,
        "taskId": task_id,
        "role": "ROLE_AGENT",
        "parts": [{"text": text, "mediaType": "text/plain"}],
    }


def _copy_message(message: Mapping[str, object]) -> dict[str, object]:
    return json.loads(json.dumps(message))


def _optional_string(message: Mapping[str, object], field_name: str) -> str | None:
    value = message.get(field_name)
    if isinstance(value, str) and value:
        return value
    return None


def _coerce_json_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None
