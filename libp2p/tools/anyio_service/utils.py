"""Utility helpers for the AnyIO service implementation."""

from __future__ import annotations

import os
from typing import Any

__all__ = [
    "get_task_name",
    "is_verbose_logging_enabled",
]


def get_task_name(value: Any, explicit_name: str | None = None) -> str:
    """
    Return a human-readable task name.

    Mirrors the logic from the original implementation so that log messages stay
    identical after the refactor.
    """
    if explicit_name is not None:
        return explicit_name

    # Avoid circular import at top level
    from .api import ServiceAPI  # type: ignore  # imported lazily

    if hasattr(value, "__class__") and isinstance(value, ServiceAPI):
        value_cls = type(value)
        if value_cls.__str__ is not object.__str__:
            return str(value)
        if value_cls.__repr__ is not object.__repr__:
            return repr(value)
        return value.__class__.__name__

    try:
        return str(value.__name__)  # functions / callables
    except AttributeError:
        return repr(value)


def is_verbose_logging_enabled() -> bool:
    """Check if verbose logging is enabled via environment variable."""
    return os.environ.get("LIBP2P_ANYIO_SERVICE_DEBUG", "").lower() in (
        "1",
        "true",
        "yes",
    )
