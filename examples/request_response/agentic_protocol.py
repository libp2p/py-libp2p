from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import time
from typing import Final

from libp2p.custom_types import TProtocol

PROTOCOL_ID = TProtocol("/example/agentic-storage/1.0.0")

AGENT_NAME: Final = "storage-agent"
AGENT_VERSION: Final = "1.0.0"
SUPPORTED_TASKS: Final[tuple[str, ...]] = ("store_intent",)
REQUIRED_SESSION_PERMISSIONS: Final[tuple[str, ...]] = (
    "CreateDataSetPermission",
    "AddPiecesPermission",
)
DEFAULT_COPIES: Final = 2
DEFAULT_WITH_CDN: Final = False
MAX_COPIES: Final = 3
MIN_DECLARED_SIZE_BYTES: Final = 127
MAX_DECLARED_SIZE_BYTES: Final = 1_065_353_216
MAX_DATASET_METADATA_PAIRS: Final = 10
MAX_PIECE_METADATA_PAIRS: Final = 5

PROVIDER_CATALOG: Final[tuple[dict[str, object], ...]] = (
    {
        "provider_id": 1,
        "name": "warm-storage-primary",
        "role": "primary",
        "endorsed": True,
        "healthy": True,
        "service_url": "https://provider-1.invalid/pdp",
    },
    {
        "provider_id": 2,
        "name": "warm-storage-secondary",
        "role": "secondary",
        "endorsed": False,
        "healthy": True,
        "service_url": "https://provider-2.invalid/pdp",
    },
    {
        "provider_id": 3,
        "name": "warm-storage-secondary-draining",
        "role": "secondary",
        "endorsed": False,
        "healthy": False,
        "service_url": "https://provider-3.invalid/pdp",
    },
)


def build_capability_query() -> dict[str, object]:
    return {"type": "capability_query"}


def build_capability_response() -> dict[str, object]:
    return {
        "type": "capability_response",
        "agent": {
            "name": AGENT_NAME,
            "version": AGENT_VERSION,
        },
        "protocol": str(PROTOCOL_ID),
        "supported_tasks": list(SUPPORTED_TASKS),
        "auth": {
            "modes": ["root", "session_key"],
            "required_session_permissions": list(REQUIRED_SESSION_PERMISSIONS),
        },
        "defaults": {
            "copies": DEFAULT_COPIES,
            "with_cdn": DEFAULT_WITH_CDN,
        },
        "limits": {
            "min_declared_size_bytes": MIN_DECLARED_SIZE_BYTES,
            "max_declared_size_bytes": MAX_DECLARED_SIZE_BYTES,
            "max_dataset_metadata_pairs": MAX_DATASET_METADATA_PAIRS,
            "max_piece_metadata_pairs": MAX_PIECE_METADATA_PAIRS,
            "max_copies": MAX_COPIES,
        },
        "providers": [provider.copy() for provider in PROVIDER_CATALOG],
    }


def build_store_intent(
    *,
    task_id: str,
    content_label: str,
    declared_size_bytes: int,
    copies: int = DEFAULT_COPIES,
    with_cdn: bool = DEFAULT_WITH_CDN,
    dataset_metadata: Mapping[str, str] | None = None,
    piece_metadata: Mapping[str, str] | None = None,
    authorization: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "type": "store_intent",
        "task_id": task_id,
        "content_label": content_label,
        "declared_size_bytes": declared_size_bytes,
        "copies": copies,
        "with_cdn": with_cdn,
        "dataset_metadata": dict(dataset_metadata or {}),
        "piece_metadata": dict(piece_metadata or {}),
        "authorization": dict(authorization or {"mode": "root"}),
    }


def process_request(message: object) -> dict[str, object]:
    if not isinstance(message, Mapping):
        return _error("invalid_request", "request must be a JSON object")

    request_type = message.get("type")
    if not isinstance(request_type, str):
        return _error("invalid_request", "request type must be a string")

    if request_type == "capability_query":
        return build_capability_response()
    if request_type == "store_intent":
        return _handle_store_intent(message)
    return _error(
        "unsupported_request_type",
        f"unsupported request type: {request_type}",
    )


def _handle_store_intent(message: Mapping[str, object]) -> dict[str, object]:
    task_id = _require_string(message, "task_id")
    content_label = _require_string(message, "content_label")
    declared_size_bytes = _require_int(message, "declared_size_bytes")
    copies = _optional_int(message, "copies", DEFAULT_COPIES)
    with_cdn = _optional_bool(message, "with_cdn", DEFAULT_WITH_CDN)
    dataset_metadata, dataset_metadata_errors = _parse_string_map(
        message.get("dataset_metadata", {}),
        field_name="dataset_metadata",
        max_pairs=MAX_DATASET_METADATA_PAIRS,
    )
    piece_metadata, piece_metadata_errors = _parse_string_map(
        message.get("piece_metadata", {}),
        field_name="piece_metadata",
        max_pairs=MAX_PIECE_METADATA_PAIRS,
    )
    authorization = _require_mapping(message, "authorization")

    errors: list[str] = []
    if task_id is None:
        errors.append("task_id must be a non-empty string")
    if content_label is None:
        errors.append("content_label must be a non-empty string")
    if declared_size_bytes is None:
        errors.append("declared_size_bytes must be an integer")
    if copies is None:
        errors.append("copies must be an integer")
    if with_cdn is None:
        errors.append("with_cdn must be a boolean")
    errors.extend(dataset_metadata_errors)
    errors.extend(piece_metadata_errors)
    if authorization is None:
        errors.append("authorization must be an object")

    if declared_size_bytes is not None and (
        declared_size_bytes < MIN_DECLARED_SIZE_BYTES
        or declared_size_bytes > MAX_DECLARED_SIZE_BYTES
    ):
        errors.append(
            "declared_size_bytes must be between "
            f"{MIN_DECLARED_SIZE_BYTES} and {MAX_DECLARED_SIZE_BYTES}"
        )

    if copies is not None and (copies < 1 or copies > MAX_COPIES):
        errors.append(f"copies must be between 1 and {MAX_COPIES}")

    auth_notes: list[str] = []
    if authorization is not None:
        errors.extend(_validate_authorization(authorization, auth_notes))

    if errors or task_id is None or content_label is None:
        return _rejected_result(
            task_id=task_id or "unknown-task",
            requested_copies=copies if copies is not None else DEFAULT_COPIES,
            errors=errors,
            notes=auth_notes,
        )

    assert declared_size_bytes is not None
    assert copies is not None
    assert with_cdn is not None
    assert dataset_metadata is not None
    assert piece_metadata is not None

    piece_cid = _make_piece_cid(
        content_label=content_label,
        declared_size_bytes=declared_size_bytes,
        with_cdn=with_cdn,
        dataset_metadata=dataset_metadata,
        piece_metadata=piece_metadata,
    )

    copies_result: list[dict[str, object]] = []
    failed_attempts: list[dict[str, object]] = []
    notes = list(auth_notes)

    for provider in PROVIDER_CATALOG[:copies]:
        provider_id = provider["provider_id"]
        role = provider["role"]
        healthy = provider["healthy"]
        if not isinstance(provider_id, int):
            raise TypeError("provider_id must be an integer")
        if not isinstance(role, str):
            raise TypeError("provider role must be a string")
        if not isinstance(healthy, bool):
            raise TypeError("provider healthy flag must be a boolean")
        if not healthy:
            failed_attempts.append(
                {
                    "provider_id": provider_id,
                    "role": role,
                    "error": "provider is unhealthy",
                }
            )
            continue

        copies_result.append(
            {
                "provider_id": provider_id,
                "data_set_id": _stable_identifier("data-set", piece_cid, provider_id),
                "piece_id": _stable_identifier("piece", piece_cid, provider_id),
                "role": role,
                "retrieval_url": (
                    f"https://provider-{provider_id}.invalid/pieces/{piece_cid}"
                ),
                "is_new_data_set": True,
            }
        )

    complete = len(copies_result) == copies
    if with_cdn:
        notes.append("CDN is accepted as a simulation-only flag in this example.")
    if not complete:
        notes.append(
            "Not enough healthy providers were available to satisfy all "
            "requested copies."
        )

    return {
        "type": "store_result",
        "task_id": task_id,
        "status": "complete" if complete else "partial",
        "complete": complete,
        "piece_cid": piece_cid,
        "requested_copies": copies,
        "copies": copies_result,
        "failed_attempts": failed_attempts,
        "errors": [],
        "notes": notes,
    }


def _validate_authorization(
    authorization: Mapping[str, object], notes: list[str]
) -> list[str]:
    errors: list[str] = []
    mode = authorization.get("mode")
    if not isinstance(mode, str):
        return ["authorization.mode must be a string"]

    if mode == "root":
        notes.append("Accepted root authorization for simulated storage task.")
        return errors

    if mode != "session_key":
        return ["authorization.mode must be 'root' or 'session_key'"]

    expires_at = _require_int(authorization, "expires_at")
    if expires_at is None:
        errors.append("authorization.expires_at must be an integer unix timestamp")
    elif expires_at <= int(time.time()):
        errors.append("session key authorization has expired")

    permissions_value = authorization.get("permissions")
    if not isinstance(permissions_value, list) or any(
        not isinstance(permission, str) for permission in permissions_value
    ):
        errors.append("authorization.permissions must be a list of strings")
    else:
        missing_permissions = [
            permission
            for permission in REQUIRED_SESSION_PERMISSIONS
            if permission not in permissions_value
        ]
        if missing_permissions:
            missing = ", ".join(missing_permissions)
            errors.append(f"session key is missing required permissions: {missing}")

    if not errors:
        notes.append(
            "Accepted simulated session key authorization. Real Synapse uses "
            "bytes32 permission hashes instead of the human-readable names in "
            "this example."
        )

    return errors


def _require_string(message: Mapping[str, object], field_name: str) -> str | None:
    value = message.get(field_name)
    if isinstance(value, str) and value:
        return value
    return None


def _require_int(message: Mapping[str, object], field_name: str) -> int | None:
    value = message.get(field_name)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _optional_int(
    message: Mapping[str, object], field_name: str, default: int
) -> int | None:
    if field_name not in message:
        return default
    return _require_int(message, field_name)


def _optional_bool(
    message: Mapping[str, object], field_name: str, default: bool
) -> bool | None:
    if field_name not in message:
        return default
    value = message.get(field_name)
    if isinstance(value, bool):
        return value
    return None


def _require_mapping(
    message: Mapping[str, object], field_name: str
) -> Mapping[str, object] | None:
    value = message.get(field_name)
    if isinstance(value, Mapping):
        return value
    return None


def _parse_string_map(
    value: object,
    *,
    field_name: str,
    max_pairs: int,
) -> tuple[dict[str, str] | None, list[str]]:
    if not isinstance(value, Mapping):
        return None, [
            f"{field_name} must be an object with string keys and string values"
        ]
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            return None, [
                f"{field_name} must be an object with string keys and string values"
            ]
        result[key] = item
    if len(result) > max_pairs:
        return None, [f"{field_name} must contain at most {max_pairs} entries"]
    return result, []


def _make_piece_cid(
    *,
    content_label: str,
    declared_size_bytes: int,
    with_cdn: bool,
    dataset_metadata: Mapping[str, str],
    piece_metadata: Mapping[str, str],
) -> str:
    payload = {
        "content_label": content_label,
        "declared_size_bytes": declared_size_bytes,
        "with_cdn": with_cdn,
        "dataset_metadata": dict(sorted(dataset_metadata.items())),
        "piece_metadata": dict(sorted(piece_metadata.items())),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"simulated-bafkzcib-{digest[:32]}"


def _stable_identifier(kind: str, piece_cid: str, provider_id: int) -> int:
    digest = hashlib.sha256(f"{kind}:{piece_cid}:{provider_id}".encode()).digest()
    return int.from_bytes(digest[:6], byteorder="big")


def _rejected_result(
    *,
    task_id: str,
    requested_copies: int,
    errors: list[str],
    notes: list[str],
) -> dict[str, object]:
    return {
        "type": "store_result",
        "task_id": task_id,
        "status": "rejected",
        "complete": False,
        "piece_cid": None,
        "requested_copies": requested_copies,
        "copies": [],
        "failed_attempts": [],
        "errors": errors,
        "notes": notes,
    }


def _error(code: str, message: str) -> dict[str, object]:
    return {
        "type": "error",
        "code": code,
        "message": message,
    }
