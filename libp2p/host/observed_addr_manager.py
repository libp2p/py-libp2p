"""
Observed Address Manager for py-libp2p.

Tracks external addresses reported by remote peers via the Identify protocol.
When enough distinct peers confirm the same external address, it is added to
the host's advertised set — matching go-libp2p's ``p2p/host/observedaddrs``.
"""

from __future__ import annotations

from enum import Enum
import ipaddress
import logging
from typing import TYPE_CHECKING, cast

from multiaddr import Multiaddr
from multiaddr.protocols import (
    P_IP4,
    P_IP6,
    P_P2P_CIRCUIT,
    P_TCP,
    P_UDP,
    Protocol,
)

if TYPE_CHECKING:
    from libp2p.abc import INetConn

logger = logging.getLogger(__name__)

ACTIVATION_THRESHOLD = 4
MAX_EXTERNAL_ADDRS_PER_LOCAL = 3
_ADDR_CACHE_SIZE = 10

_THIN_WAIST_TRANSPORT_CODES = frozenset({P_TCP, P_UDP})
_THIN_WAIST_IP_CODES = frozenset({P_IP4, P_IP6})
_NAT64_PREFIX = ipaddress.IPv6Network("64:ff9b::/96")


class NATDeviceType(Enum):
    """NAT device type classification."""

    UNKNOWN = "unknown"
    ENDPOINT_INDEPENDENT = "endpoint_independent"
    ENDPOINT_DEPENDENT = "endpoint_dependent"


def extract_thin_waist(maddr: Multiaddr) -> tuple[Multiaddr, str] | None:
    """
    Split *maddr* into a thin-waist prefix and the remaining suffix.

    The thin waist is the IP + transport portion, e.g.
    ``/ip4/1.2.3.4/tcp/4001``.  Everything after (``/ws``, ``/p2p/Qm…``, …)
    is returned as the *rest* string.

    Returns ``None`` when the address does not contain a recognisable
    thin-waist prefix.
    """
    protos = cast(list[Protocol], maddr.protocols())

    # We need at least an IP and a transport protocol.
    if len(protos) < 2:
        return None
    if protos[0].code not in _THIN_WAIST_IP_CODES:
        return None
    if protos[1].code not in _THIN_WAIST_TRANSPORT_CODES:
        return None

    ip_code = protos[0].code
    transport_code = protos[1].code

    ip_val = maddr.value_for_protocol(ip_code)
    transport_val = maddr.value_for_protocol(transport_code)

    thin_waist = Multiaddr(
        f"/{protos[0].name}/{ip_val}/{protos[1].name}/{transport_val}"
    )

    # Build the rest string from protocols after the first two.
    rest_parts: list[str] = []
    for p in protos[2:]:
        val = maddr.value_for_protocol(p.code)
        if val:
            rest_parts.append(f"/{p.name}/{val}")
        else:
            rest_parts.append(f"/{p.name}")
    rest = "".join(rest_parts)

    return thin_waist, rest


def observer_group(remote_addr: tuple[str, int]) -> str:
    """
    Compute a grouping key from the observer's remote address.

    IPv4: full IP string.  IPv6: /56 prefix.  Multiple connections from the
    same group count as a single observer.
    """
    ip_str = remote_addr[0]
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return ip_str

    if isinstance(addr, ipaddress.IPv6Address):
        network = ipaddress.IPv6Network(f"{ip_str}/56", strict=False)
        return str(network.network_address)
    return ip_str


def is_valid_observation(observed: Multiaddr) -> bool:
    """Reject loopback, relay, NAT64, and non-thin-waist observations."""
    protos = observed.protocols()
    proto_codes = {p.code for p in protos}

    # Reject relay addresses.
    if P_P2P_CIRCUIT in proto_codes:
        return False

    # Reject loopback.
    if P_IP4 in proto_codes:
        ip_val = observed.value_for_protocol(P_IP4)
        if ip_val and ip_val.startswith("127."):
            return False
    if P_IP6 in proto_codes:
        ip_val = observed.value_for_protocol(P_IP6)
        if ip_val == "::1":
            return False
        # Reject NAT64 well-known prefix (64:ff9b::/96).
        if ip_val:
            try:
                addr = ipaddress.ip_address(ip_val)
                if isinstance(addr, ipaddress.IPv6Address) and addr in _NAT64_PREFIX:
                    return False
            except ValueError:
                pass

    # Must have a recognisable thin waist.
    result = extract_thin_waist(observed)
    if result is None:
        return False

    return True


class ObservedAddrManager:
    """Tracks externally observed addresses reported by remote peers."""

    def __init__(self) -> None:
        # local_tw_str -> external_tw_str -> observer group key -> count
        self._external_addrs: dict[str, dict[str, dict[str, int]]] = {}
        # id(conn) -> (local_tw_str, external_tw_str, observer_group_key)
        self._conn_observations: dict[int, tuple[str, str, str]] = {}
        # local_tw_str -> set of "rest" suffixes seen on listen addresses
        self._local_addr_rests: dict[str, set[str]] = {}
        # Cache: full_addr_str → Multiaddr object (avoids repeated construction)
        self._addr_cache: dict[str, Multiaddr] = {}

    def _cached_multiaddr(self, addr_str: str) -> Multiaddr:
        """Return a cached Multiaddr for the given string, constructing if needed."""
        ma = self._addr_cache.get(addr_str)
        if ma is not None:
            return ma
        ma = Multiaddr(addr_str)
        if len(self._addr_cache) >= _ADDR_CACHE_SIZE:
            # Evict the oldest entry (first inserted key in insertion-order dict).
            oldest = next(iter(self._addr_cache))
            del self._addr_cache[oldest]
        self._addr_cache[addr_str] = ma
        return ma

    def record_observation(
        self,
        conn: INetConn,
        observed_addr: Multiaddr,
        local_addrs: list[Multiaddr],
    ) -> None:
        """
        Record an observed address from a remote peer.

        Parameters
        ----------
        conn:
            The network connection the observation came from.
        observed_addr:
            The address the remote peer sees us as.
        local_addrs:
            Our current listen/transport addresses (without ``/p2p/…``).

        """
        if getattr(conn, "is_closed", False):
            return

        if not is_valid_observation(observed_addr):
            return

        obs_result = extract_thin_waist(observed_addr)
        if obs_result is None:
            return
        external_tw, _ = obs_result

        # Get remote address from connection for observer grouping.
        remote = _get_remote_addr(conn)
        if remote is None:
            return
        obs_group = observer_group(remote)

        # Match observed address to a local thin waist.
        local_tw_str = _match_local_thin_waist(external_tw, local_addrs)
        if local_tw_str is None:
            return

        external_tw_str = str(external_tw)
        conn_id = id(conn)

        # If this connection already had an observation, check if it changed.
        if conn_id in self._conn_observations:
            old_local, old_ext, old_obs = self._conn_observations[conn_id]
            if old_local == local_tw_str and old_ext == external_tw_str:
                return  # Same observation, nothing to do
            self._remove_observation(old_local, old_ext, old_obs)

        # Store the observation.
        if local_tw_str not in self._external_addrs:
            self._external_addrs[local_tw_str] = {}
        if external_tw_str not in self._external_addrs[local_tw_str]:
            self._external_addrs[local_tw_str][external_tw_str] = {}
        observers = self._external_addrs[local_tw_str][external_tw_str]
        observers[obs_group] = observers.get(obs_group, 0) + 1
        self._conn_observations[conn_id] = (
            local_tw_str,
            external_tw_str,
            obs_group,
        )

        # Update rest suffixes from local addresses for address inference.
        self._update_local_addr_rests(local_addrs)

    def remove_conn(self, conn: INetConn) -> None:
        """Clean up observations when a connection is closed."""
        conn_id = id(conn)
        if conn_id not in self._conn_observations:
            return
        local_tw, ext_tw, obs = self._conn_observations.pop(conn_id)
        self._remove_observation(local_tw, ext_tw, obs)

    def addrs(self, min_observers: int = ACTIVATION_THRESHOLD) -> list[Multiaddr]:
        """
        Return confirmed external addresses.

        An address is confirmed when at least *min_observers* distinct
        observer groups have reported it.  Returns up to
        ``MAX_EXTERNAL_ADDRS_PER_LOCAL`` addresses per local thin waist,
        sorted by observer count descending with lexicographic tiebreak.

        For each confirmed external thin waist, full addresses are generated by
        combining with rest suffixes seen on local listen addresses (address
        inference).
        """
        result: list[Multiaddr] = []
        for local_tw_str, ext_map in self._external_addrs.items():
            result.extend(
                self._get_top_external_addrs(local_tw_str, ext_map, min_observers)
            )
        return result

    def addrs_for(
        self, listen_addr: Multiaddr, min_observers: int = ACTIVATION_THRESHOLD
    ) -> list[Multiaddr]:
        """
        Return confirmed external addresses for a specific listen address.

        Equivalent to Go's ``AddrsFor``.  Returns one address per confirmed
        external thin waist, combining it with the rest suffix of the queried
        *listen_addr* (not all known rest suffixes).
        """
        tw_result = extract_thin_waist(listen_addr)
        if tw_result is None:
            return []
        local_tw, rest = tw_result
        local_tw_str = str(local_tw)
        ext_map = self._external_addrs.get(local_tw_str)
        if ext_map is None:
            return []

        candidates = self._select_candidates(ext_map, min_observers)
        result: list[Multiaddr] = []
        for ext_tw_str, _ in candidates:
            if rest:
                result.append(self._cached_multiaddr(ext_tw_str + rest))
            else:
                result.append(self._cached_multiaddr(ext_tw_str))
        return result

    @staticmethod
    def _select_candidates(
        ext_map: dict[str, dict[str, int]], min_observers: int
    ) -> list[tuple[str, int]]:
        """Filter, sort, and cap external address candidates."""
        candidates = [
            (ext_tw_str, len(observers))
            for ext_tw_str, observers in ext_map.items()
            if len(observers) >= min_observers
        ]
        candidates.sort(key=lambda x: (-x[1], x[0]))
        return candidates[:MAX_EXTERNAL_ADDRS_PER_LOCAL]

    def _get_top_external_addrs(
        self,
        local_tw_str: str,
        ext_map: dict[str, dict[str, int]],
        min_observers: int,
    ) -> list[Multiaddr]:
        """Return top external addresses for a single local thin waist."""
        candidates = self._select_candidates(ext_map, min_observers)

        result: list[Multiaddr] = []
        sorted_rests = sorted(self._local_addr_rests.get(local_tw_str, ()))
        seen: set[str] = set()
        for ext_tw_str, _ in candidates:
            if ext_tw_str not in seen:
                seen.add(ext_tw_str)
                result.append(self._cached_multiaddr(ext_tw_str))
            for rest in sorted_rests:
                if rest:
                    full = ext_tw_str + rest
                    if full not in seen:
                        seen.add(full)
                        result.append(self._cached_multiaddr(full))
        return result

    def get_nat_type(self) -> tuple[NATDeviceType, NATDeviceType]:
        """
        Return (tcp_nat_type, udp_nat_type) based on observation distribution.

        Matches Go's ``getNATType()`` algorithm.
        """
        # Gather per-protocol observation counts.
        # proto_key -> list of observer counts per external address
        tcp_counts: list[int] = []
        udp_counts: list[int] = []

        for _, ext_map in self._external_addrs.items():
            # Invariant: every ``ext_tw_str`` key in a single ``ext_map`` shares
            # the same transport (all ``/tcp/`` or all ``/udp/``), because the
            # outer key (``local_tw_str``) is derived from a single local
            # thin-waist in ``record_observation`` via ``_match_local_thin_waist``
            # and only matches external thin waists with the same IP family +
            # transport (see ``has_consistent_transport``). It is therefore
            # enough to classify the bucket once from the first key — this
            # matches go-libp2p's ``getNATType`` behaviour in
            # ``p2p/host/basic/basic_host.go``.
            first_key = next(iter(ext_map), "")
            is_tcp = "/tcp/" in first_key
            for ext_tw_str, observers in ext_map.items():
                # Defensive skip: if a future refactor ever allows a mixed
                # bucket, misclassifying as "other transport" is silently
                # wrong — drop the stray entry instead.
                if is_tcp and "/tcp/" not in ext_tw_str:
                    continue
                if not is_tcp and "/udp/" not in ext_tw_str:
                    continue
                count = len(observers)  # unique observer groups, not total connections
                if is_tcp:
                    tcp_counts.append(count)
                else:
                    udp_counts.append(count)

        return (
            self._classify_nat(tcp_counts),
            self._classify_nat(udp_counts),
        )

    @staticmethod
    def _classify_nat(counts: list[int]) -> NATDeviceType:
        """Classify NAT type from per-address observation counts."""
        if not counts:
            return NATDeviceType.UNKNOWN

        all_total = sum(counts)
        top = sorted(counts, reverse=True)[:MAX_EXTERNAL_ADDRS_PER_LOCAL]
        top_total = sum(top)

        # Need enough observations to make a determination.
        if all_total < 3 * MAX_EXTERNAL_ADDRS_PER_LOCAL:
            return NATDeviceType.UNKNOWN

        # If top addresses cover >= 50% of all observations → cone NAT.
        if top_total * 2 >= all_total:
            return NATDeviceType.ENDPOINT_INDEPENDENT
        return NATDeviceType.ENDPOINT_DEPENDENT

    def _remove_observation(self, local_tw: str, ext_tw: str, obs_group: str) -> None:
        ext_map = self._external_addrs.get(local_tw)
        if ext_map is None:
            return
        observers = ext_map.get(ext_tw)
        if observers is None:
            return
        if obs_group in observers:
            observers[obs_group] -= 1
            if observers[obs_group] <= 0:
                del observers[obs_group]
        if not observers:
            del ext_map[ext_tw]
            self._addr_cache.clear()  # cached addrs may reference removed ext_tw
        if not ext_map:
            del self._external_addrs[local_tw]

    def _update_local_addr_rests(self, local_addrs: list[Multiaddr]) -> None:
        """Extract rest suffixes from local addresses for later inference."""
        for addr in local_addrs:
            result = extract_thin_waist(addr)
            if result is None:
                continue
            tw, rest = result
            tw_str = str(tw)

            # Also store for wildcard-matched versions.
            # We match by port+transport, so store under the canonical
            # local_tw that would be used by _match_local_thin_waist.
            if tw_str not in self._local_addr_rests:
                self._local_addr_rests[tw_str] = set()
            if rest:
                self._local_addr_rests[tw_str].add(rest)


def has_consistent_transport(tw_a: Multiaddr, tw_b: Multiaddr) -> bool:
    """Check both thin waists use the same protocol codes (IP + transport)."""
    protos_a = cast(list[Protocol], tw_a.protocols())
    protos_b = cast(list[Protocol], tw_b.protocols())
    if len(protos_a) < 2 or len(protos_b) < 2:
        return False
    return protos_a[0].code == protos_b[0].code and protos_a[1].code == protos_b[1].code


def _get_remote_addr(conn: INetConn) -> tuple[str, int] | None:
    """Extract the remote (IP, port) from a connection."""
    muxed = getattr(conn, "muxed_conn", None)
    if muxed is None:
        return None
    get_remote = getattr(muxed, "get_remote_address", None)
    if get_remote is None:
        return None
    result = get_remote()
    if result is not None and isinstance(result, tuple) and len(result) == 2:
        return result
    return None


def _match_local_thin_waist(
    external_tw: Multiaddr, local_addrs: list[Multiaddr]
) -> str | None:
    """
    Find a local thin waist that matches the external observation.

    Handles wildcard IPs (``0.0.0.0`` / ``::``) by matching on port and
    transport protocol only.
    """
    ext_protos = cast(list[Protocol], external_tw.protocols())
    if len(ext_protos) < 2:
        return None
    ext_ip_code = ext_protos[0].code
    ext_transport_code = ext_protos[1].code
    ext_port = external_tw.value_for_protocol(ext_transport_code)

    for addr in local_addrs:
        result = extract_thin_waist(addr)
        if result is None:
            continue
        local_tw, _ = result
        local_protos = cast(list[Protocol], local_tw.protocols())
        if len(local_protos) < 2:
            continue
        local_ip_code = local_protos[0].code
        local_transport_code = local_protos[1].code

        # Transport must match.
        if local_transport_code != ext_transport_code:
            continue

        # Port must match.
        local_port = local_tw.value_for_protocol(local_transport_code)
        if local_port != ext_port:
            continue

        # IP family must be compatible.
        local_ip = local_tw.value_for_protocol(local_ip_code)
        is_wildcard = local_ip in ("0.0.0.0", "::")

        if is_wildcard:
            # Wildcard matches any IP of the same family.
            if ext_ip_code == local_ip_code:
                return str(local_tw)
        else:
            # Exact thin waist match (same IP family, same port).
            if local_ip_code == ext_ip_code:
                return str(local_tw)

    return None
