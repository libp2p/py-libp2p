"""Public API for libp2p's pubsub subsystem (lazy re-exports).

Re-exports the main pubsub classes and the negotiated GossipSub protocol
identifiers so consumers have a stable import surface instead of reaching
into private submodules or hardcoding protocol strings.

The re-exports are *lazy* (PEP 562 ``__getattr__``) on purpose: this package
sits in the middle of several import cycles (``libp2p.custom_types`` imports
``libp2p.pubsub.pb`` while ``libp2p.abc`` is still initializing), so eagerly
importing the heavy pubsub modules here would fail. With lazy attributes, the
modules are only imported once the caller actually accesses a name — by which
point the whole ``libp2p`` package has finished loading.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "GossipSub",
    "PROTOCOL_ID",
    "PROTOCOL_ID_V11",
    "PROTOCOL_ID_V12",
    "PROTOCOL_ID_V13",
    "PROTOCOL_ID_V14",
    "PROTOCOL_ID_V20",
    "Pubsub",
]

_GOSSIPSUB_EXPORTS = {
    "GossipSub",
    "PROTOCOL_ID",
    "PROTOCOL_ID_V11",
    "PROTOCOL_ID_V12",
    "PROTOCOL_ID_V13",
    "PROTOCOL_ID_V14",
    "PROTOCOL_ID_V20",
}


def __getattr__(name: str) -> Any:
    if name == "Pubsub":
        from .pubsub import Pubsub

        return Pubsub
    if name in _GOSSIPSUB_EXPORTS:
        from .gossipsub import (
            GossipSub,
            PROTOCOL_ID,
            PROTOCOL_ID_V11,
            PROTOCOL_ID_V12,
            PROTOCOL_ID_V13,
            PROTOCOL_ID_V14,
            PROTOCOL_ID_V20,
        )

        return {
            "GossipSub": GossipSub,
            "PROTOCOL_ID": PROTOCOL_ID,
            "PROTOCOL_ID_V11": PROTOCOL_ID_V11,
            "PROTOCOL_ID_V12": PROTOCOL_ID_V12,
            "PROTOCOL_ID_V13": PROTOCOL_ID_V13,
            "PROTOCOL_ID_V14": PROTOCOL_ID_V14,
            "PROTOCOL_ID_V20": PROTOCOL_ID_V20,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
