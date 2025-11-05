from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import ipaddress
from threading import RLock


@dataclass(frozen=True)
class CIDRRule:
    network: ipaddress.IPv4Network | ipaddress.IPv6Network
    max_connections: int


class CIDRLimiter:
    """
    Simple per-subnet connection limiter.

    Maintains counters per configured CIDR network and enforces a maximum
    number of simultaneous connections that match each network.
    """

    def __init__(self, rules: Iterable[tuple[str, int]] | None = None) -> None:
        self._rules: list[CIDRRule] = []
        self._counts: dict[ipaddress.IPv4Network | ipaddress.IPv6Network, int] = {}
        self._lock = RLock()

        if rules:
            for cidr, limit in rules:
                try:
                    net = ipaddress.ip_network(cidr, strict=False)
                    rule = CIDRRule(network=net, max_connections=max(0, int(limit)))
                    self._rules.append(rule)
                    self._counts.setdefault(net, 0)
                except Exception:
                    # Skip invalid CIDRs silently; callers may validate separately
                    continue

    def allow(self, endpoint_ip: str | None) -> bool:
        """Return True if connection from endpoint_ip is allowed under rules."""
        if not self._rules or not endpoint_ip:
            return True
        try:
            ip = ipaddress.ip_address(endpoint_ip)
        except Exception:
            return True  # Fail-open if IP cannot be parsed

        with self._lock:
            for rule in self._rules:
                if ip in rule.network:
                    current = self._counts.get(rule.network, 0)
                    if current >= rule.max_connections:
                        return False
            return True

    def acquire(self, endpoint_ip: str | None) -> bool:
        """Attempt to acquire a slot for endpoint_ip, updating counters on success."""
        if not self._rules or not endpoint_ip:
            return True
        try:
            ip = ipaddress.ip_address(endpoint_ip)
        except Exception:
            return True

        with self._lock:
            # Check all matching rules first
            for rule in self._rules:
                if ip in rule.network:
                    if self._counts.get(rule.network, 0) >= rule.max_connections:
                        return False
            # Increment all matching rules
            for rule in self._rules:
                if ip in rule.network:
                    self._counts[rule.network] = self._counts.get(rule.network, 0) + 1
            return True

    def release(self, endpoint_ip: str | None) -> None:
        if not self._rules or not endpoint_ip:
            return
        try:
            ip = ipaddress.ip_address(endpoint_ip)
        except Exception:
            return

        with self._lock:
            for rule in self._rules:
                if ip in rule.network:
                    current = self._counts.get(rule.network, 0)
                    if current > 0:
                        self._counts[rule.network] = current - 1
