Advertising dialable addresses
==============================

Other peers need a multiaddr they can actually dial. py-libp2p combines **listen**
addresses with several ways to surface a **publicly reachable** address:

**1. Inferred from Identify (NAT / cloud)** — Remote peers report what they see
when they connect, via :mod:`libp2p.identity.identify`. The host’s
:class:`~libp2p.host.observed_addr_manager.ObservedAddrManager` collects those
reports; after enough distinct observer groups agree on the same external
address, it is included in :meth:`libp2p.host.basic_host.BasicHost.get_addrs`.
Background and API details: :doc:`libp2p.host` (section
``libp2p.host.observed_addr_manager``).

**2. Explicit ``announce_addrs``** — If you already know the dialable address
(fixed public IP, ngrok, load balancer, etc.), pass ``announce_addrs`` when
constructing :class:`~libp2p.host.basic_host.BasicHost`. That list is advertised
instead of augmenting with observed addresses (observations may still be recorded
for :meth:`~libp2p.host.basic_host.BasicHost.get_nat_type` and related logic).

**3. Callable ``addrs_factory``** — For go-libp2p ``AddrsFactory`` parity, pass a
callable that receives the live candidate list (transport addresses plus
confirmed observed addresses when discovery is enabled) and returns the
addresses to advertise. Use this to compose listen + observed + extras rather
than choosing only a static list. ``announce_addrs`` and ``addrs_factory`` are
mutually exclusive.

**4. ``disable_identify_address_discovery``** — When you know your public
addresses upfront and do not want Identify-driven **address** discovery
(privacy or to skip ``ObservedAddrManager`` work), set this to ``True``.
Observations are not recorded; ``get_nat_type()`` returns unknown. Identify
itself still runs for peer metadata; only ``observed_addr`` consumption for
local discovery is disabled. Pair with ``announce_addrs`` or
``addrs_factory`` as go-libp2p recommends with
``DisableIdentifyAddressDiscovery``.

For step-by-step usage, comparison of these approaches, and a full example
script, see :doc:`examples.announce_addrs` (source:
``examples/announce_addrs/announce_addrs.py`` in the repository).
