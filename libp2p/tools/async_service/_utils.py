# Copied from https://github.com/ethereum/async-service

import os
from typing import Any


def get_task_name(value: Any, explicit_name: str | None = None) -> str:
    # inline import to ensure `_utils` is always importable from the rest of
    # the module.
    from .abc import (  # noqa: F401
        ServiceAPI,
    )

    if explicit_name is not None:
        # if an explicit name was provided, just return that.
        return explicit_name
    elif isinstance(value, ServiceAPI):
        # `Service` instance naming rules:
        #
        # 1. __str__ **if** the class implements a custom __str__ method
        # 2. __repr__ **if** the class implements a custom __repr__ method
        # 3. The `Service` class name.
        value_cls = type(value)
        if value_cls.__str__ is not object.__str__:
            return str(value)
        if value_cls.__repr__ is not object.__repr__:
            return repr(value)
        else:
            return value.__class__.__name__
    else:
        try:
            # Prefer the name of the function if it has one
            return str(value.__name__)  # mypy doesn't know __name__ is a `str`
        except AttributeError:
            return repr(value)


def is_verbose_logging_enabled() -> bool:
    return bool(os.environ.get("ASYNC_SERVICE_VERBOSE_LOG", False))
