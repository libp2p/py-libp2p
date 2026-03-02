"""
Pull-based connection resolver.

The resolver implements a *pull model*: an application (or the host)
requests a connection with certain capabilities (e.g. ``IMuxedConn``),
and the resolver builds the connection stack automatically from
registered providers.

How it works
------------
1. **Desired capability** — the caller asks for a connection satisfying
   a target interface (e.g. ``IMuxedConn``).
2. **Transport selection** — the resolver picks a transport provider
   that can dial the target multiaddr.
3. **Layer resolution** — using ordering metadata
   (``@after_connection``) and the provider registry, the resolver
   determines which upgrade layers are needed (security, muxer) and in
   what order.
4. **Stack execution** — the resolver dials the transport, then applies
   each upgrade layer in sequence, short-circuiting if the transport
   already provides security / muxing (capability flags).
5. **Fallback** — if a path fails (handshake error, unsupported
   protocol), the resolver tries the next registered transport.

This module is opt-in: existing code using the fixed
``TransportUpgrader`` pipeline continues to work.  The host can switch
to the resolver by calling :meth:`ConnectionResolver.resolve` instead
of the manual dial→upgrade→upgrade sequence.

See Also
--------
:mod:`libp2p.providers` — provider abstractions and registry.
:mod:`libp2p.capabilities` — capability flags.
:mod:`libp2p.requirements` — ordering metadata.

"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from multiaddr import Multiaddr

from libp2p.abc import (
    IMuxedConn,
    IRawConnection,
    ISecureConn,
)
from libp2p.peer.id import ID
from libp2p.providers import (
    MuxerProvider,
    ProviderRegistry,
    SecurityProvider,
    TransportProvider,
)
from libp2p.requirements import get_after_connections
from libp2p.transport.exceptions import (
    MuxerUpgradeFailure,
    SecurityUpgradeFailure,
)

logger = logging.getLogger(__name__)


@dataclass
class ResolvedStack:
    """
    The result of a successful resolution.

    Contains the final connection and metadata about how the stack was
    built, useful for diagnostics and logging.
    """

    raw_conn: IRawConnection | None = None
    secure_conn: ISecureConn | None = None
    muxed_conn: IMuxedConn | None = None

    transport_provider: TransportProvider | None = None
    security_provider: SecurityProvider | None = None
    muxer_provider: MuxerProvider | None = None

    skipped_security: bool = False
    skipped_muxer: bool = False

    @property
    def top_connection(self) -> Any:
        """Return the highest-level connection in the stack."""
        if self.muxed_conn is not None:
            return self.muxed_conn
        if self.secure_conn is not None:
            return self.secure_conn
        return self.raw_conn

    def describes(self) -> str:
        """Human-readable description of the resolved stack."""
        parts: list[str] = []
        if self.transport_provider:
            parts.append(f"transport={self.transport_provider.protocol_name}")
        if self.skipped_security:
            parts.append("security=builtin")
        elif self.security_provider:
            parts.append(f"security={self.security_provider.protocol_id}")
        if self.skipped_muxer:
            parts.append("muxer=builtin")
        elif self.muxer_provider:
            parts.append(f"muxer={self.muxer_provider.protocol_id}")
        return " → ".join(parts) or "(empty)"


class ResolutionError(Exception):
    """No viable connection stack could be built."""


class NoTransportError(ResolutionError):
    """No registered transport can dial the target multiaddr."""


class AllPathsFailedError(ResolutionError):
    """Every transport / upgrade path failed."""

    def __init__(self, failures: list[tuple[str, Exception]]) -> None:
        self.failures = failures
        paths = "; ".join(f"{name}: {err}" for name, err in failures)
        super().__init__(f"All resolution paths failed: {paths}")


class ConnectionResolver:
    """
    Pull-based connection stack builder.

    Given a target multiaddr and a peer ID, the resolver tries every
    registered transport that can dial the address, applies the required
    upgrade layers (security, muxer), and returns the resulting
    connection stack.

    Parameters
    ----------
    registry:
        The :class:`~libp2p.providers.ProviderRegistry` to consult.

    """

    def __init__(self, registry: ProviderRegistry) -> None:
        self._registry = registry

    async def resolve(
        self,
        maddr: Multiaddr,
        peer_id: ID,
        *,
        is_initiator: bool = True,
    ) -> ResolvedStack:
        """
        Resolve a fully-upgraded connection to *peer_id* via *maddr*.

        The resolver iterates over transport providers that match
        *maddr*.  For each, it:

        1. Dials the transport to get a raw connection.
        2. Checks capability flags — if the transport already provides
           security and muxing, returns immediately.
        3. Otherwise, applies security then muxer upgrades using the
           registered providers.
        4. If any step fails, moves to the next transport.

        Parameters
        ----------
        maddr:
            Target multiaddr.
        peer_id:
            Remote peer identity.
        is_initiator:
            Whether we initiated the connection (affects security
            handshake direction).

        Returns
        -------
        ResolvedStack
            The fully-resolved connection stack.

        Raises
        ------
        NoTransportError
            If no transport can dial *maddr*.
        AllPathsFailedError
            If every transport path fails.

        """
        candidates = self._registry.get_transports_for(maddr)
        if not candidates:
            raise NoTransportError(f"No registered transport can dial {maddr}")

        failures: list[tuple[str, Exception]] = []

        for tp in candidates:
            try:
                stack = await self._try_path(tp, maddr, peer_id, is_initiator)
                logger.info(
                    "Resolver: connection established via %s", stack.describes()
                )
                return stack
            except Exception as exc:
                logger.debug("Resolver: path %s failed: %s", tp.protocol_name, exc)
                failures.append((tp.protocol_name, exc))

        raise AllPathsFailedError(failures)

    async def _try_path(
        self,
        tp: TransportProvider,
        maddr: Multiaddr,
        peer_id: ID,
        is_initiator: bool,
    ) -> ResolvedStack:
        """Attempt to build a full stack using one transport provider."""
        stack = ResolvedStack(transport_provider=tp)

        raw_conn = await tp.dial(maddr)
        stack.raw_conn = raw_conn

        if tp.provides_security and tp.provides_muxing:
            stack.skipped_security = True
            stack.skipped_muxer = True
            logger.debug(
                "Transport %s provides security + muxing; skipping upgrades",
                tp.protocol_name,
            )
            return stack

        conn_for_muxer: Any = raw_conn
        if tp.provides_security:
            stack.skipped_security = True
            conn_for_muxer = raw_conn
            logger.debug(
                "Transport %s provides security; skipping security upgrade",
                tp.protocol_name,
            )
        else:
            sec_providers = self._registry.get_security_providers()
            if not sec_providers:
                raise SecurityUpgradeFailure("No security providers registered")
            sec_ok = False
            for sp in sec_providers:
                try:
                    secure_conn = await sp.upgrade(raw_conn, is_initiator, peer_id)
                    stack.secure_conn = secure_conn
                    stack.security_provider = sp
                    conn_for_muxer = secure_conn
                    sec_ok = True
                    break
                except Exception as exc:
                    logger.debug("Security provider %s failed: %s", sp.protocol_id, exc)
                    continue
            if not sec_ok:
                try:
                    await raw_conn.close()
                except Exception:
                    pass
                raise SecurityUpgradeFailure("All security providers failed")

        if tp.provides_muxing:
            stack.skipped_muxer = True
            logger.debug(
                "Transport %s provides muxing; skipping muxer upgrade",
                tp.protocol_name,
            )
        else:
            mux_providers = self._registry.get_muxer_providers()
            if not mux_providers:
                raise MuxerUpgradeFailure("No muxer providers registered")

            for mp in mux_providers:
                after = get_after_connections(mp.muxer_class)
                for iface in after:
                    if not isinstance(conn_for_muxer, iface):
                        logger.warning(
                            "Muxer %s declares @after_connection(%s) "
                            "but connection (%s) does not satisfy it",
                            mp.muxer_class.__name__,
                            iface.__name__,
                            type(conn_for_muxer).__name__,
                        )

            mux_ok = False
            for mp in mux_providers:
                try:
                    muxed = await mp.upgrade(conn_for_muxer, peer_id)
                    stack.muxed_conn = muxed
                    stack.muxer_provider = mp
                    mux_ok = True
                    break
                except Exception as exc:
                    logger.debug("Muxer provider %s failed: %s", mp.protocol_id, exc)
                    continue
            if not mux_ok:
                try:
                    await conn_for_muxer.close()
                except Exception:
                    pass
                raise MuxerUpgradeFailure("All muxer providers failed")

        return stack

    async def upgrade_inbound(
        self,
        raw_conn: IRawConnection,
        *,
        transport_has_security: bool = False,
        transport_has_muxing: bool = False,
    ) -> ResolvedStack:
        """
        Upgrade an inbound (listener-accepted) raw connection.

        Unlike :meth:`resolve`, we already have the raw connection — we
        just need to apply security and muxer layers.
        """
        stack = ResolvedStack(raw_conn=raw_conn)

        if transport_has_security and transport_has_muxing:
            stack.skipped_security = True
            stack.skipped_muxer = True
            return stack

        conn_for_muxer: Any = raw_conn

        # Security
        if transport_has_security:
            stack.skipped_security = True
            conn_for_muxer = raw_conn
        else:
            sec_providers = self._registry.get_security_providers()
            if sec_providers:
                sp = sec_providers[0]
                secure_conn = await sp.upgrade(raw_conn, is_initiator=False)
                stack.secure_conn = secure_conn
                stack.security_provider = sp
                conn_for_muxer = secure_conn
            else:
                raise SecurityUpgradeFailure(
                    "No security providers registered for inbound"
                )

        if transport_has_muxing:
            stack.skipped_muxer = True
        else:
            mux_providers = self._registry.get_muxer_providers()
            if mux_providers:
                peer_id = (
                    stack.secure_conn.get_remote_peer()
                    if stack.secure_conn is not None
                    else ID(b"\x00")
                )
                mp = mux_providers[0]
                muxed = await mp.upgrade(conn_for_muxer, peer_id)
                stack.muxed_conn = muxed
                stack.muxer_provider = mp
            else:
                raise MuxerUpgradeFailure("No muxer providers registered for inbound")

        return stack
