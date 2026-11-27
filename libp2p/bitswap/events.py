"""
Event definitions for the Bitswap module.

Emitted on the host's event bus whenever something observable happens in
Bitswap: wantlist changes, block transfer, message flow, sessions and
provider queries.
"""


class BitswapEvent:
    """
    A Bitswap event, emitted on the host's event bus.

    One event object carries a single occurrence; boolean flags mark which
    kind of event it is and the remaining fields carry its payload.
    """

    peer_id: str | None = None

    want_add: bool = False
    want_cancel: bool = False
    block_received: bool = False
    block_sent: bool = False
    message_sent: bool = False
    message_received: bool = False
    session_new: bool = False
    provider_query: bool = False

    # Fields
    cid: str | None = None
    size_bytes: int | None = None
    kind: str | None = None
    entries: int | None = None
    msg_bytes: int | None = None
    success: bool | None = None
    peers_found: int | None = None
    duration_ms: float | None = None
    priority: int | None = None
    want_type: str | None = None  # "block" or "have"
    providers: list[str] | None = None  # provider peer ids found (bounded)
