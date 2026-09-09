libp2p.host package
===================

Subpackages
-----------

.. toctree::
   :maxdepth: 4

   libp2p.host.autonat

Submodules
----------

libp2p.host.basic\_host module
------------------------------

.. automodule:: libp2p.host.basic_host
   :members:
   :undoc-members:
   :show-inheritance:

libp2p.host.defaults module
---------------------------

.. automodule:: libp2p.host.defaults
   :members:
   :undoc-members:
   :show-inheritance:

libp2p.host.exceptions module
-----------------------------

.. automodule:: libp2p.host.exceptions
   :members:
   :undoc-members:
   :show-inheritance:

libp2p.host.observed\_addr\_manager module
-------------------------------------------

.. seealso::

   Conceptual overview (inferred Identify observations vs ``announce_addrs``):
   :doc:`advertising_addresses`.

Automatic NAT address discovery. Remote peers report the address they see
us on via the Identify protocol; once enough *distinct observer groups*
(``ACTIVATION_THRESHOLD``, currently ``4``) report the same external
address, it is treated as confirmed and appended by
:meth:`libp2p.host.basic_host.BasicHost.get_addrs` so peers learn the
host's real public address (fixes issue #1250 for NAT/EC2 deployments).

Interaction with ``announce_addrs`` / ``addrs_factory``: when
``announce_addrs`` is passed to :class:`~libp2p.host.basic_host.BasicHost`
it is treated as an explicit static ``AddrsFactory`` (mirroring go-libp2p's
``applyAddrsFactory``) and wins over observed addresses: observations are
still **recorded** (for :meth:`~libp2p.host.basic_host.BasicHost.get_nat_type`
and future AutoNAT consumers) but are **not** advertised via ``get_addrs``.
A callable ``addrs_factory`` receives the live candidate list (transport
addresses plus confirmed observed addresses) and returns whatever should be
advertised — use it to compose listen + observed + extras. Passing both
``announce_addrs`` and ``addrs_factory`` raises ``ValueError``.

To stop recording Identify observations entirely (privacy or to avoid the
``ObservedAddrManager`` footprint), set
``disable_identify_address_discovery=True`` (parity with go-libp2p's
``DisableIdentifyAddressDiscovery``). In that mode ``get_nat_type()``
returns ``(UNKNOWN, UNKNOWN)``. The Identify protocol itself still runs
(peer metadata is still exchanged); only consumption of Identify
``observed_addr`` for local address discovery is skipped.

.. automodule:: libp2p.host.observed_addr_manager
   :members:
   :undoc-members:
   :show-inheritance:

libp2p.host.ping module
-----------------------

.. automodule:: libp2p.host.ping
   :members:
   :undoc-members:
   :show-inheritance:

libp2p.host.routed\_host module
-------------------------------

.. automodule:: libp2p.host.routed_host
   :members:
   :undoc-members:
   :show-inheritance:

Module contents
---------------

.. automodule:: libp2p.host
   :members:
   :undoc-members:
   :show-inheritance:
