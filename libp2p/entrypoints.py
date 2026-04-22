"""
Entry-point-based plugin discovery.

Allows transports, security protocols, and stream muxers to be
registered automatically via Python packaging entry points.  This lets
third-party packages contribute to the libp2p stack simply by declaring
an entry-point in their ``pyproject.toml``::

    [project.entry-points."libp2p.transports"]
    quic = "libp2p.transport.quic:create_provider"

    [project.entry-points."libp2p.security"]
    noise = "libp2p.security.noise:create_provider"

    [project.entry-points."libp2p.muxers"]
    yamux = "libp2p.stream_muxer.yamux:create_provider"

Each entry point must resolve to a **callable** that takes no arguments
and returns a :class:`~libp2p.providers.TransportProvider`,
:class:`~libp2p.providers.SecurityProvider`, or
:class:`~libp2p.providers.MuxerProvider`, respectively.

The main function :func:`discover_and_register` scans all three groups
and populates a :class:`~libp2p.providers.ProviderRegistry`.

See Also
--------
:mod:`libp2p.providers` — provider abstractions and registry.
:mod:`libp2p.network.resolver` — resolver that consumes the registry.

"""

from __future__ import annotations

import logging
import sys
from typing import Any

from libp2p.providers import (
    MuxerProvider,
    ProviderRegistry,
    SecurityProvider,
    TransportProvider,
)

logger = logging.getLogger(__name__)

EP_GROUP_TRANSPORTS = "libp2p.transports"
EP_GROUP_SECURITY = "libp2p.security"
EP_GROUP_MUXERS = "libp2p.muxers"


def _load_entry_points(group: str) -> list[tuple[str, Any]]:
    """
    Load all entry points for *group*.

    Returns a list of ``(name, loaded_object)`` tuples.  Loading errors
    are logged and skipped so one broken plugin cannot take down the
    whole application.
    """
    if sys.version_info >= (3, 12):
        from importlib.metadata import entry_points

        eps = entry_points(group=group)
    else:
        from importlib.metadata import entry_points

        eps = entry_points(group=group)

    results: list[tuple[str, Any]] = []
    for ep in eps:
        try:
            obj = ep.load()
            results.append((ep.name, obj))
        except Exception:
            logger.warning(
                "Failed to load entry point %r from group %r",
                ep.name,
                group,
                exc_info=True,
            )
    return results


def discover_transports() -> list[TransportProvider]:
    """
    Discover transport providers registered via entry points.

    Each entry point must be a callable that returns a
    :class:`~libp2p.providers.TransportProvider`.
    """
    providers: list[TransportProvider] = []
    for name, factory in _load_entry_points(EP_GROUP_TRANSPORTS):
        try:
            provider = factory() if callable(factory) else factory
            if isinstance(provider, TransportProvider):
                providers.append(provider)
                logger.debug("Discovered transport provider: %s", name)
            else:
                logger.warning(
                    "Entry point %r (group %s) did not produce a "
                    "TransportProvider; got %s",
                    name,
                    EP_GROUP_TRANSPORTS,
                    type(provider).__name__,
                )
        except Exception:
            logger.warning(
                "Error creating transport provider from entry point %r",
                name,
                exc_info=True,
            )
    return providers


def discover_security() -> list[SecurityProvider]:
    """
    Discover security providers registered via entry points.

    Each entry point must be a callable that returns a
    :class:`~libp2p.providers.SecurityProvider`.
    """
    providers: list[SecurityProvider] = []
    for name, factory in _load_entry_points(EP_GROUP_SECURITY):
        try:
            provider = factory() if callable(factory) else factory
            if isinstance(provider, SecurityProvider):
                providers.append(provider)
                logger.debug("Discovered security provider: %s", name)
            else:
                logger.warning(
                    "Entry point %r (group %s) did not produce a "
                    "SecurityProvider; got %s",
                    name,
                    EP_GROUP_SECURITY,
                    type(provider).__name__,
                )
        except Exception:
            logger.warning(
                "Error creating security provider from entry point %r",
                name,
                exc_info=True,
            )
    return providers


def discover_muxers() -> list[MuxerProvider]:
    """
    Discover muxer providers registered via entry points.

    Each entry point must be a callable that returns a
    :class:`~libp2p.providers.MuxerProvider`.
    """
    providers: list[MuxerProvider] = []
    for name, factory in _load_entry_points(EP_GROUP_MUXERS):
        try:
            provider = factory() if callable(factory) else factory
            if isinstance(provider, MuxerProvider):
                providers.append(provider)
                logger.debug("Discovered muxer provider: %s", name)
            else:
                logger.warning(
                    "Entry point %r (group %s) did not produce a MuxerProvider; got %s",
                    name,
                    EP_GROUP_MUXERS,
                    type(provider).__name__,
                )
        except Exception:
            logger.warning(
                "Error creating muxer provider from entry point %r",
                name,
                exc_info=True,
            )
    return providers


def discover_and_register(
    registry: ProviderRegistry | None = None,
) -> ProviderRegistry:
    """
    Scan all entry-point groups and register discovered providers.

    Parameters
    ----------
    registry:
        An existing registry to populate.  If ``None``, a new
        :class:`~libp2p.providers.ProviderRegistry` is created.

    Returns
    -------
    ProviderRegistry
        The (possibly new) registry, with all discovered providers
        registered.

    """
    if registry is None:
        registry = ProviderRegistry()

    for tp in discover_transports():
        registry.register_transport(tp)

    for sp in discover_security():
        registry.register_security(sp)

    for mp in discover_muxers():
        registry.register_muxer(mp)

    logger.info("Entry-point discovery complete: %s", registry)
    return registry
