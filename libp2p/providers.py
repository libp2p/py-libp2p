"""
Connection-layer provider abstractions.

A *connection provider* is any component that can transform one kind of
connection into another (e.g. ``IRawConnection → ISecureConn``) or that
can produce connections from scratch (e.g. a transport that dials a peer).

The resolver (:mod:`libp2p.network.resolver`) uses this registry to
build a connection stack dynamically at dial/listen time.

Terminology
-----------
* **Transport** — incoming IO; bottom touches the network, top exposes a
  connection.  Implements :class:`ProvidesTransport`.
* **Connection layer** — transitive IO; consumes one connection and
  produces a higher-level one.  Implements :class:`ProvidesConnection`.
* **Protocol** — outgoing IO; runs on a fully-upgraded connection.

See Also
--------
:mod:`libp2p.capabilities` — capability flags (``provides_security``,
    ``provides_muxing``).
:mod:`libp2p.requirements` — ``@after_connection`` ordering metadata.

"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from libp2p.abc import (
    IMuxedConn,
    IRawConnection,
    ISecureConn,
    ISecureTransport,
    ITransport,
)
from libp2p.custom_types import (
    TMuxerClass,
    TMuxerOptions,
    TProtocol,
    TSecurityOptions,
)
from libp2p.peer.id import ID

logger = logging.getLogger(__name__)


@runtime_checkable
class ProvidesTransport(Protocol):
    """
    Structural protocol for components that can produce raw connections
    from a network address.

    Every :class:`~libp2p.abc.ITransport` is automatically a
    ``ProvidesTransport`` — the protocol simply formalises the concept so
    the resolver can discover and iterate over transport providers
    without hard-coding transport classes.
    """

    def can_dial(self, maddr: Any) -> bool:
        """Return ``True`` if this provider can dial the given multiaddr."""
        ...

    async def dial(self, maddr: Any) -> IRawConnection:
        """Dial the multiaddr and return a raw connection."""
        ...


@runtime_checkable
class ProvidesConnection(Protocol):
    """
    Structural protocol for components that can *upgrade* an existing
    connection to a higher-level one.

    Examples
    --------
    * A security transport consumes ``IRawConnection`` and produces
      ``ISecureConn`` → provides ``ISecureConn``.
    * A muxer consumes ``ISecureConn`` and produces ``IMuxedConn``
      → provides ``IMuxedConn``.

    """

    @property
    def provides_interface(self) -> type:
        """
        The connection interface this provider produces
        (e.g. ``ISecureConn``, ``IMuxedConn``).
        """
        ...

    @property
    def requires_interface(self) -> type:
        """
        The connection interface this provider consumes
        (e.g. ``IRawConnection``, ``ISecureConn``).
        """
        ...


class SecurityProvider:
    """
    Wraps an :class:`~libp2p.abc.ISecureTransport` as a
    :class:`ProvidesConnection`.

    Consumes ``IRawConnection``, produces ``ISecureConn``.
    """

    def __init__(
        self,
        protocol_id: TProtocol,
        transport: ISecureTransport,
    ) -> None:
        self.protocol_id = protocol_id
        self.transport = transport

    @property
    def provides_interface(self) -> type:
        return ISecureConn

    @property
    def requires_interface(self) -> type:
        return IRawConnection

    async def upgrade(
        self,
        conn: IRawConnection,
        is_initiator: bool,
        peer_id: ID | None = None,
    ) -> ISecureConn:
        if is_initiator:
            if peer_id is None:
                raise ValueError("peer_id required for outbound security upgrade")
            return await self.transport.secure_outbound(conn, peer_id)
        return await self.transport.secure_inbound(conn)

    def __repr__(self) -> str:
        return f"SecurityProvider({self.protocol_id!r})"


class MuxerProvider:
    """
    Wraps a muxer class as a :class:`ProvidesConnection`.

    Consumes ``ISecureConn``, produces ``IMuxedConn``.
    """

    def __init__(
        self,
        protocol_id: TProtocol,
        muxer_class: TMuxerClass,
    ) -> None:
        self.protocol_id = protocol_id
        self.muxer_class = muxer_class

    @property
    def provides_interface(self) -> type:
        return IMuxedConn

    @property
    def requires_interface(self) -> type:
        return ISecureConn

    async def upgrade(
        self,
        conn: ISecureConn,
        peer_id: ID,
    ) -> IMuxedConn:
        return self.muxer_class(conn, peer_id)

    def __repr__(self) -> str:
        return f"MuxerProvider({self.protocol_id!r})"


class TransportProvider:
    """
    Wraps an :class:`~libp2p.abc.ITransport` as a
    :class:`ProvidesTransport`.

    Optionally supports multiaddr matching so the resolver can select the
    right transport for a dial target.
    """

    def __init__(
        self,
        protocol_name: str,
        transport: ITransport,
        *,
        matcher: Any | None = None,
    ) -> None:
        self.protocol_name = protocol_name
        self.transport = transport
        self._matcher = matcher

    def can_dial(self, maddr: Any) -> bool:
        if self._matcher is not None:
            return bool(self._matcher(maddr))
        try:
            protocols = [p.name for p in maddr.protocols()]
            return self.protocol_name in protocols
        except Exception:
            return False

    async def dial(self, maddr: Any) -> IRawConnection:
        return await self.transport.dial(maddr)

    @property
    def provides_security(self) -> bool:
        return getattr(self.transport, "provides_security", False)

    @property
    def provides_muxing(self) -> bool:
        return getattr(self.transport, "provides_muxing", False)

    def __repr__(self) -> str:
        return f"TransportProvider({self.protocol_name!r})"


class ProviderRegistry:
    """
    Central registry of transport and connection-layer providers.

    The :class:`~libp2p.network.resolver.ConnectionResolver` consults
    this registry when building connection stacks.
    """

    def __init__(self) -> None:
        self._transport_providers: list[TransportProvider] = []
        self._security_providers: list[SecurityProvider] = []
        self._muxer_providers: list[MuxerProvider] = []

    def register_transport(self, provider: TransportProvider) -> None:
        self._transport_providers.append(provider)
        logger.debug("Registered transport provider: %s", provider)

    def register_security(self, provider: SecurityProvider) -> None:
        self._security_providers.append(provider)
        logger.debug("Registered security provider: %s", provider)

    def register_muxer(self, provider: MuxerProvider) -> None:
        self._muxer_providers.append(provider)
        logger.debug("Registered muxer provider: %s", provider)

    def register_security_options(self, opts: TSecurityOptions) -> None:
        """Populate from the legacy ``TSecurityOptions`` mapping."""
        for proto, transport in opts.items():
            self.register_security(SecurityProvider(proto, transport))

    def register_muxer_options(self, opts: TMuxerOptions) -> None:
        """Populate from the legacy ``TMuxerOptions`` mapping."""
        for proto, muxer_cls in opts.items():
            self.register_muxer(MuxerProvider(proto, muxer_cls))

    def get_transports(self) -> list[TransportProvider]:
        return list(self._transport_providers)

    def get_transports_for(self, maddr: Any) -> list[TransportProvider]:
        """Return providers that can dial *maddr*."""
        return [tp for tp in self._transport_providers if tp.can_dial(maddr)]

    def get_security_providers(self) -> list[SecurityProvider]:
        return list(self._security_providers)

    def get_muxer_providers(self) -> list[MuxerProvider]:
        return list(self._muxer_providers)

    def has_security(self) -> bool:
        return len(self._security_providers) > 0

    def has_muxer(self) -> bool:
        return len(self._muxer_providers) > 0

    def __repr__(self) -> str:
        return (
            f"ProviderRegistry("
            f"transports={len(self._transport_providers)}, "
            f"security={len(self._security_providers)}, "
            f"muxers={len(self._muxer_providers)})"
        )
