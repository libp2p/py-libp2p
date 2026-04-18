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

Automatic NAT address discovery. Remote peers report the address they see
us on via the Identify protocol; once enough *distinct observer groups*
(``ACTIVATION_THRESHOLD``, currently ``4``) report the same external
address, it is treated as confirmed and appended by
:meth:`libp2p.host.basic_host.BasicHost.get_addrs` so peers learn the
host's real public address (fixes issue #1250 for NAT/EC2 deployments).

Interaction with ``announce_addrs``: when ``announce_addrs`` is passed to
:class:`~libp2p.host.basic_host.BasicHost` it is treated as an explicit
``AddrsFactory`` (mirroring go-libp2p's ``applyAddrsFactory``) and wins
over observed addresses: observations are still **recorded** (for
:meth:`~libp2p.host.basic_host.BasicHost.get_nat_type` and future
AutoNAT consumers) but are **not** advertised via ``get_addrs``.

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
