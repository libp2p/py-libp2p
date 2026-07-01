examples.multi\_transport package
=================================

Migration Guide
---------------
The `libp2p.transport.transport_registry` module has been removed, and `Swarm` no longer accepts the `transport=` keyword argument.

To migrate to the new `TransportManager` architecture:
- Pass a list of transports to `new_swarm` or `new_host` using the `transports=[...]` keyword argument.
- If `transports` is omitted, the swarm will automatically detect and create transports based on the provided `listen_addrs`.

Submodules
----------

examples.multi\_transport.client module
---------------------------------------

.. automodule:: examples.multi_transport.client
   :members:
   :show-inheritance:
   :undoc-members:

examples.multi\_transport.server module
---------------------------------------

.. automodule:: examples.multi_transport.server
   :members:
   :show-inheritance:
   :undoc-members:

Module contents
---------------

.. automodule:: examples.multi_transport
   :members:
   :show-inheritance:
   :undoc-members:
