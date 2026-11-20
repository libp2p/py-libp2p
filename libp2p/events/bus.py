"""
INotifee-style event bus for libp2p.

Modules emit typed event objects whenever something happens — a Kad-DHT
lookup completes, a Bitswap block arrives, mDNS discovers a peer, a pubsub
message is published — and any number of listeners can subscribe to be
notified. The Prometheus metrics exporter is one such listener; logging,
tracing and user code can register additional ones.

This mirrors the existing INotifee fan-out in ``libp2p/network/swarm.py``:
every listener is notified of every event, and a failing listener can never
affect the emitter or the other listeners (each listener's exceptions are
isolated and logged).

Design notes
------------
- **Synchronous, non-blocking fan-out.** ``emit`` invokes each listener
  inline on the caller's path (like go-libp2p's ``event.Bus``). Listeners
  must be fast — prometheus counter increments are — and must not perform
  blocking I/O. This keeps protocol hot paths free of queues and backpressure.
- **Thread-safe.** ``register_listener`` / ``remove_listener`` / ``emit``
  may be called from any thread, which matters for discovery modules whose
  zeroconf callbacks run on a non-trio thread.
"""

from abc import ABC, abstractmethod
import logging
import threading
import traceback
from typing import Any

import trio

logger = logging.getLogger(__name__)


class IEventListener(ABC):
    """
    A listener that wants to be notified of module events.

    Analogous to ``INotifee`` in the network layer: an object registered
    with the :class:`EventBus` that receives every emitted event. Unlike
    INotifee there is no fixed callback surface — the listener receives
    typed event objects and filters by type.
    """

    @abstractmethod
    def handle_event(self, event: Any) -> None:
        """
        Handle a single emitted event.

        Implementations MUST be fast and non-blocking. Any exception raised
        here is caught by the bus and logged — it never propagates to the
        emitter or to other listeners.
        """


class EventBus:
    """
    Fan-out event bus with INotifee-style listener registration.

    Emitters call :meth:`emit` with a typed event object; every registered
    listener's :meth:`IEventListener.handle_event` is invoked, with
    exceptions isolated per listener.
    """

    def __init__(self) -> None:
        self._listeners: list[IEventListener] = []
        self._lock = threading.Lock()

    def register_listener(self, listener: IEventListener) -> None:
        """
        Subscribe ``listener`` to all events emitted on this bus.

        Registering the same listener twice is a no-op.
        """
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_listener(self, listener: IEventListener) -> None:
        """Unsubscribe ``listener`` so it stops receiving events."""
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    @property
    def listeners(self) -> list[IEventListener]:
        """Return a snapshot of the currently registered listeners."""
        with self._lock:
            return list(self._listeners)

    def emit(self, event: Any) -> None:
        """
        Fan out ``event`` to every registered listener.

        Each listener runs inline, wrapped in try/except so a raising
        listener never propagates into the emitter or blocks other
        listeners (mirrors ``Swarm._notify`` semantics).
        """
        for listener in self.listeners:
            try:
                listener.handle_event(event)
            except Exception:
                logger.exception(
                    "EventBus listener %s raised while handling %s",
                    type(listener).__name__,
                    type(event).__name__,
                )


class ChannelBridgeListener(IEventListener):
    """
    Bridge that forwards bus events into a trio memory send channel.

    Backward-compatibility shim: the pre-event-bus metrics pipeline flowed
    events from a ``trio.open_memory_channel`` send end attached to every
    stream into a single consumer (``Metrics.start_prometheus_server``).
    This listener lets that consumer keep working unchanged by forwarding
    every bus event into its receive channel.

    The forward is best-effort: if the channel is full or closed the event
    is dropped (metrics are loss-tolerant). Because trio channels are not
    thread-safe, events emitted from a non-trio thread (e.g. zeroconf
    discovery callbacks) that reach this bridge are dropped and logged at
    debug level.
    """

    def __init__(self, send_channel: trio.MemorySendChannel[Any]) -> None:
        self._send_channel = send_channel

    def handle_event(self, event: Any) -> None:
        try:
            self._send_channel.send_nowait(event)
        except trio.WouldBlock:
            pass  # consumer is slow — drop (metrics are loss-tolerant)
        except trio.ClosedResourceError:
            pass
        except RuntimeError:
            # Trio channel used from a non-trio thread (e.g. zeroconf
            # callback): cannot forward — drop.
            logger.debug("Dropping event %s: bridge used off the trio thread", event)
        except Exception:
            logger.debug(
                "Dropping event %s on bridge: %s", event, traceback.format_exc()
            )
