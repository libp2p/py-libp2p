Advertising dialable addresses
==============================

Other peers need a multiaddr they can actually dial. py-libp2p combines **listen**
addresses with two ways to surface a **publicly reachable** address:

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

For step-by-step usage, comparison of the two approaches, and a full example
script, see :doc:`examples.announce_addrs` (source:
``examples/announce_addrs/announce_addrs.py`` in the repository).
