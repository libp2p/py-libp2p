from __future__ import annotations

import logging
import socket

from multiaddr import Multiaddr

from .networks import get_network_preset

logger = logging.getLogger(__name__)

_DNS_PROTOCOLS = ("dns", "dns4", "dns6", "dnsaddr")
_QUIC_PROTOCOLS = ("quic", "quic-v1", "webtransport")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item not in seen:
            output.append(item)
            seen.add(item)
    return output


def _protocols(addr: str) -> tuple[str, ...]:
    try:
        return tuple(proto.name for proto in Multiaddr(addr).protocols())
    except Exception:
        return ()


def _has_any_protocol(addr: str, names: tuple[str, ...]) -> bool:
    protocols = _protocols(addr)
    return any(name in protocols for name in names)


def _has_protocol(addr: str, name: str) -> bool:
    return name in _protocols(addr)


def get_bootstrap_addresses(network: str, canonical: bool = True) -> list[str]:
    if canonical:
        return list(get_network_preset(network).bootstrap_addresses)
    return get_runtime_bootstrap_addresses(network)


def filter_bootstrap_for_transport(
    addrs: list[str], include_tcp: bool = True, include_quic: bool = False
) -> list[str]:
    filtered: list[str] = []
    for addr in addrs:
        protocols = _protocols(addr)
        if not protocols:
            continue
        if include_tcp and "tcp" in protocols:
            filtered.append(addr)
            continue
        if include_quic and any(proto in protocols for proto in _QUIC_PROTOCOLS):
            filtered.append(addr)
    return _dedupe(filtered)


def _value_for_protocol(maddr: Multiaddr, protocol: str) -> str | None:
    try:
        return maddr.value_for_protocol(protocol)
    except Exception:
        return None


def _extract_dns_host(maddr: Multiaddr) -> str | None:
    for proto in _DNS_PROTOCOLS:
        value = _value_for_protocol(maddr, proto)
        if value:
            return value
    return None


def resolve_dns_bootstrap_to_ip4_tcp(addrs: list[str]) -> list[str]:
    resolved: list[str] = []

    for addr in addrs:
        try:
            maddr = Multiaddr(addr)
        except Exception as exc:
            logger.warning("invalid multiaddr '%s': %s", addr, exc)
            continue

        peer_id = _value_for_protocol(maddr, "p2p")
        tcp_port = _value_for_protocol(maddr, "tcp")
        ip4_addr = _value_for_protocol(maddr, "ip4")

        if peer_id and tcp_port and ip4_addr:
            resolved.append(f"/ip4/{ip4_addr}/tcp/{tcp_port}/p2p/{peer_id}")
            continue

        dns_host = _extract_dns_host(maddr)
        if not (peer_id and tcp_port and dns_host):
            continue

        try:
            infos = socket.getaddrinfo(
                dns_host,
                int(tcp_port),
                socket.AF_INET,
                socket.SOCK_STREAM,
            )
        except OSError as exc:
            logger.warning("dns resolution failed for '%s': %s", addr, exc)
            continue

        for info in infos:
            sockaddr = info[4]
            if not sockaddr:
                continue
            ip4 = sockaddr[0]
            resolved.append(f"/ip4/{ip4}/tcp/{tcp_port}/p2p/{peer_id}")

    return _dedupe(resolved)


def get_runtime_bootstrap_addresses(
    network: str, resolve_dns: bool = True, include_quic: bool = False
) -> list[str]:
    canonical_addrs = list(get_network_preset(network).bootstrap_addresses)
    transport_filtered = filter_bootstrap_for_transport(
        canonical_addrs,
        include_tcp=True,
        include_quic=include_quic,
    )

    tcp_addrs = [addr for addr in transport_filtered if _has_protocol(addr, "tcp")]
    if not resolve_dns:
        return _dedupe(transport_filtered)

    resolved_tcp = resolve_dns_bootstrap_to_ip4_tcp(tcp_addrs)
    if not resolved_tcp:
        logger.warning(
            "no dns bootstrap entries could be resolved for '%s'; returning "
            "transport-filtered addresses",
            network,
        )
        return _dedupe(transport_filtered)

    if include_quic:
        quic_addrs = [
            addr
            for addr in transport_filtered
            if _has_any_protocol(addr, _QUIC_PROTOCOLS)
        ]
        return _dedupe(resolved_tcp + quic_addrs)

    return _dedupe(resolved_tcp)
