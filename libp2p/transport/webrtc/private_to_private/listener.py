import logging
from typing import Any, Callable
from multiaddr import Multiaddr
import trio
try:
    from libp2p.abc import IHost, IListener, ITransportManager
except Exception:
    class IHost:
        pass

    class IListener:
        pass

    class ITransportManager:
        pass
from libp2p.custom_types import THandler
from ..constants import WEBRTC_PROTOCOL

logger = logging.getLogger("libp2p.transport.webrtc.private_to_private.listener")


class WebRTCPeerListener(IListener):
    """
    WebRTC peer listener for private-to-private connections.
    
    This listener follows the JavaScript libp2p pattern:
    - Listens to transport events for circuit relay addresses
    - Generates WebRTC multiaddrs by encapsulating circuit addresses
    - Does not manage circuit relays directly (that's the transport's job)
    - Minimal responsibility focused only on address management
    """

    def __init__(self, transport: Any, handler: THandler, host: IHost) -> None:
        """Initialize WebRTC peer listener."""
        self.transport = transport
        self.handler = handler
        self.host = host
        self._is_listening = False
        self._nursery: trio.Nursery | None = None
        
        # Event handling for transport listening events
        self._transport_listening_handler: Callable[[Any], None] | None = None
        
        logger.info("WebRTC peer listener initialized")

    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> bool:
        """Start listening for incoming connections."""
        if self._is_listening:
            return True

        logger.info("Starting WebRTC peer listener")
        self._nursery = nursery

        try:
            # Register for transport listening events
            self._setup_transport_event_listener()
            
            self._is_listening = True
            logger.info("WebRTC peer listener started successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to start WebRTC peer listener: {e}")
            return False

    def _setup_transport_event_listener(self) -> None:
        """Set up listener for transport events."""
        logger.debug("Setting up transport event listener")
        
        def on_transport_listening(event_data: Any) -> None:
            """Handle transport listening events."""
            try:
                # When circuit relay transports start listening,
                # we can generate WebRTC addresses
                self._on_transport_listening(event_data)
            except Exception as e:
                logger.warning(f"Error handling transport listening event: {e}")
        
        self._transport_listening_handler = on_transport_listening
        

    def _on_transport_listening(self, event_data: Any) -> None:
        """Handle transport listening event - generate WebRTC addresses."""
        logger.debug("Transport listening event received")
        
        
    async def close(self) -> None:
        """Stop listening and close the listener."""
        if not self._is_listening:
            return

        logger.info("Closing WebRTC peer listener")
        
        try:
            # Unregister event listener
            self._transport_listening_handler = None
            
            self._is_listening = False
            logger.info("WebRTC peer listener closed successfully")

        except Exception as e:
            logger.error(f"Error during listener cleanup: {e}")

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        """
        Get listener addresses as WebRTC multiaddrs.
        
        find circuit addresses and encapsulate 
        them with '/webrtc' protocol.
        """
        if not self._is_listening:
            return tuple()

        try:
            addrs = []
            
            # Get transport manager from host
            if hasattr(self.host, 'get_transport_manager'):
                transport_manager = self.host.get_transport_manager()
            else:
                network = getattr(self.host, '_network', None)
                transport_manager = getattr(network, 'transport_manager', None)
            
            if transport_manager:
                # Get all listeners from transport manager
                listeners = transport_manager.get_listeners()
                
                for listener in listeners:
                    # Skip self to avoid recursion
                    if listener is self:
                        continue
                    
                    # Get addresses from each listener
                    listener_addrs = listener.get_addrs()
                    
                    for addr in listener_addrs:
                        # Check if this is a circuit address
                        if self._is_circuit_address(addr):
                            # Encapsulate with WebRTC protocol
                            webrtc_addr = addr.encapsulate(
                                Multiaddr(f"/{WEBRTC_PROTOCOL}")
                            )
                            addrs.append(webrtc_addr)
            
            # If no circuit addresses found, try to create generic WebRTC address
            if not addrs:
                peer_id = self.host.get_id()
                if peer_id:
                    # Create a generic WebRTC multiaddr
                    generic_addr = Multiaddr(f"/{WEBRTC_PROTOCOL}/p2p/{peer_id}")
                    addrs.append(generic_addr)

            logger.debug(f"Generated {len(addrs)} WebRTC listener addresses")
            return tuple(addrs)

        except Exception as e:
            logger.error(f"Error generating listener addresses: {e}")
            return tuple()

    def _is_circuit_address(self, addr: Multiaddr) -> bool:
        """Check if address is a circuit relay address."""
        try:
            protocols = {p.name for p in addr.protocols()}
            return 'p2p-circuit' in protocols
        except Exception:
            return False

    def is_listening(self) -> bool:
        """Check if listener is active."""
        return self._is_listening
    
    def _register_for_transport_events(self) -> None:
        """Register for transport manager events."""
        try:
            transport_manager = self._get_transport_manager()
            if transport_manager and hasattr(transport_manager, 'add_event_listener'):
                transport_manager.add_event_listener('transport:listening', 
                                                self._on_transport_listening)
        except Exception as e:
            logger.debug(f"Could not register for transport events: {e}")

    def _unregister_transport_events(self) -> None:
        """Unregister from transport manager events.""" 
        try:
            transport_manager = self._get_transport_manager()
            if transport_manager and hasattr(transport_manager, 'remove_event_listener'):
                transport_manager.remove_event_listener('transport:listening', 
                                                    self._on_transport_listening)
        except Exception as e:
            logger.debug(f"Could not unregister transport events: {e}")

    def _get_transport_manager(self) -> Any:
        """Get transport manager from host."""
        if hasattr(self.host, 'get_transport_manager'):
            return self.host.get_transport_manager()
        elif hasattr(self.host, '_network'):
            network = self.host._network  
            return getattr(network, 'transport_manager', None)
        return None
