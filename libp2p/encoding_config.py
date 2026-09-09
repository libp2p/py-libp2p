from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import threading

import multibase

_lock = threading.Lock()
_default_encoding: str = "base58btc"


def get_default_encoding() -> str:
    """Return the current default multibase encoding (e.g. ``'base58btc'``)."""
    return _default_encoding


def set_default_encoding(encoding: str) -> None:
    """
    Set the process-wide default multibase encoding.

    Writes are protected by an internal lock.  Reads via
    :func:`get_default_encoding` are **not** locked, so a concurrent
    reader may briefly see a stale value.

    Parameters
    ----------
    encoding : str
        A multibase encoding name recognised by *py-multibase*
        (e.g. ``'base58btc'``, ``'base32'``, ``'base64'``,
        ``'base64url'``, …).

    Raises
    ------
    ValueError
        If *encoding* is not supported by *py-multibase*.

    """
    global _default_encoding

    if not multibase.is_encoding_supported(encoding):
        supported = ", ".join(multibase.list_encodings())
        raise ValueError(
            f"Unsupported encoding {encoding!r}. Supported encodings: {supported}"
        )

    with _lock:
        _default_encoding = encoding


@contextmanager
def encoding_override(encoding: str) -> Iterator[None]:
    """
    Temporarily override the default encoding within a ``with`` block.

    The previous encoding is restored when the block exits—even on exceptions.

    .. warning:: **Thread-safety caveat**

       The lock is only held for the individual *write* operations (setting
       and restoring the default), **not** for the entire duration of the
       ``with`` block.  This means that if two threads use
       ``encoding_override`` concurrently, they can interleave and one
       thread's override may be visible to the other.  For multi-threaded
       applications that require isolation, prefer passing an explicit
       *encoding* parameter to ``to_multibase()`` / ``bytes_to_multibase()``
       instead of relying on the global default.

    Parameters
    ----------
    encoding : str
        A multibase encoding name recognised by *py-multibase*.

    Raises
    ------
    ValueError
        If *encoding* is not supported.

    Example
    -------
    >>> with encoding_override("base32"):
    ...     peer_id.to_multibase()  # uses base32
    ...
    >>> peer_id.to_multibase()      # back to the previous default

    """
    previous = get_default_encoding()
    set_default_encoding(encoding)
    try:
        yield
    finally:
        with _lock:
            global _default_encoding
            _default_encoding = previous


def list_supported_encodings() -> list[str]:
    """Return a sorted list of all encoding names supported by *py-multibase*."""
    return sorted(multibase.list_encodings())
