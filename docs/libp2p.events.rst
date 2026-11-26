libp2p.events package
=====================

Network lifecycle and observability
-----------------------------------

The swarm invokes asynchronous :class:`libp2p.abc.INotifee` callbacks for
connections, streams, and listeners. Identify, pubsub, and the tag store
use these callbacks to maintain their network state.

The host's :class:`libp2p.events.bus.EventBus` delivers typed observability
events synchronously for modules such as Bitswap, discovery, Kad-DHT, and
GossipSub. The swarm publishes connection and stream open/close events from
the same methods that invoke the corresponding notifee callbacks. Transport
dial and inbound admission events report attempt outcomes. For example, an
inbound connection rejected by the swarm reports one failure outcome.

Call ``host.get_event_bus()`` to subscribe. Listeners run inline on the emitting
thread, so keep callbacks short and synchronize shared state. An exception
in one listener is logged independently of the other listeners.

For example, this listener queues observations for an application-owned
logging or tracing worker. If the worker falls behind, the listener drops
events once the queue is full.

.. code-block:: python

   from queue import Full, Queue

   from libp2p.events import IEventListener

   observations = Queue(maxsize=256)


   class QueueListener(IEventListener):
       def handle_event(self, event):
           try:
               observations.put_nowait(event)
           except Full:
               pass


   bus = host.get_event_bus()
   listener = QueueListener()
   bus.register_listener(listener)
   # The worker drains observations while the host runs.
   bus.remove_listener(listener)

To export Prometheus metrics, use ``Metrics().attach(host.get_event_bus())``
and ``Metrics.start_http_server()``. For applications using the legacy
``enable_metrics=True`` and ``start_prometheus_server(recv_channel)`` API, the
channel bridge uses best-effort delivery. It drops events when the channel is
full or closed, or when an emitter runs outside Trio. Use one Prometheus
consumption path per bus to count each event once.

Submodules
----------

libp2p.events.bus module
------------------------

.. automodule:: libp2p.events.bus
   :members:
   :show-inheritance:
   :undoc-members:

Module contents
---------------

.. automodule:: libp2p.events
   :members:
   :show-inheritance:
   :undoc-members:
