"""
Transport and connection capability declarations.

Instead of the core checking ``isinstance(transport, QUICTransport)`` to decide
whether to skip security or muxing upgrades, transports and connections *declare*
what they already provide via simple boolean properties.

Any transport or connection that satisfies the structural protocol (duck typing)
is automatically recognised — no base-class inheritance required.

Example — a hypothetical WebRTC transport that bundles its own DTLS + SCTP::

    class WebRTCTransport(ITransport):
        @property
        def provides_security(self) -> bool:
            return True

        @property
        def provides_muxing(self) -> bool:
            return True

See Also
--------
:pep:`544` — Structural subtyping (static duck typing) via ``typing.Protocol``.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class TransportCapabilities(Protocol):
    """Structural protocol implemented by transports that bundle their own
    security and/or multiplexing layers.

    A transport that does **not** implement these properties is assumed to
    provide neither (``getattr(t, 'provides_security', False)`` → ``False``).
    """

    @property
    def provides_security(self) -> bool:
        """Return ``True`` if this transport includes built-in encryption /
        authentication (e.g. QUIC's integrated TLS 1.3)."""
        ...

    @property
    def provides_muxing(self) -> bool:
        """Return ``True`` if this transport includes built-in stream
        multiplexing (e.g. QUIC's native streams)."""
        ...


@runtime_checkable
class ConnectionCapabilities(Protocol):
    """Structural protocol implemented by connections that are already
    secured and/or multiplexed at creation time.

    A connection that does **not** implement these properties is assumed to
    be neither secure nor muxed.
    """

    @property
    def is_secure(self) -> bool:
        """Return ``True`` if the connection is already encrypted and the
        remote peer's identity has been verified."""
        ...

    @property
    def is_muxed(self) -> bool:
        """Return ``True`` if the connection already supports opening
        multiple independent streams."""
        ...


@runtime_checkable
class NeedsSetup(Protocol):
    """Structural protocol for transports that require lifecycle hooks
    from the swarm (e.g. a background nursery or a back-reference to
    the swarm itself).

    Transports that do **not** need these hooks simply omit the methods.
    """

    def set_background_nursery(self, nursery: object) -> None:
        """Receive the long-lived nursery managed by the swarm."""
        ...

    def set_swarm(self, swarm: object) -> None:
        """Receive a back-reference to the owning swarm."""
        ...
