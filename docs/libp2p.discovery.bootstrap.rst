libp2p.discovery.bootstrap package
==================================

The bootstrap discovery module connects to a list of bootstrap peer addresses
to join the network. It supports both IP and DNS multiaddrs.

Supported bootstrap address types
---------------------------------

- **IP:** ``/ip4/...``, ``/ip6/...`` (e.g. ``/ip4/127.0.0.1/tcp/4001/p2p/PEER_ID``)
- **DNS:** ``/dns/...``, ``/dns4/...`` (IPv4-only), ``/dns6/...`` (IPv6-only), ``/dnsaddr/...``

Example: using DNS bootstrap addresses
---------------------------------------

.. code-block:: python

    from multiaddr import Multiaddr
    from libp2p.peer.peerinfo import info_from_p2p_addr

    # dnsaddr (resolves to one or more multiaddrs)
    bootstrap_list = [
        "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    ]

    # Or use hostname with explicit transport (dns4 = IPv4, dns6 = IPv6)
    bootstrap_list = [
        "/dns4/bootstrap.example.com/tcp/4001/p2p/PEER_ID",
        "/dns6/bootstrap.example.com/tcp/4001/p2p/PEER_ID",
    ]

    for addr_str in bootstrap_list:
        peer_info = info_from_p2p_addr(Multiaddr(addr_str))
        await host.connect(peer_info)

If a DNS address fails to resolve or returns no results, the module logs a
warning and continues with the next bootstrap address.

Submodules
----------

Module contents
---------------

.. automodule:: libp2p.discovery.bootstrap
   :members:
   :undoc-members:
   :show-inheritance:
