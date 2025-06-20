Circuit Relay v2 Example
========================

This example demonstrates how to use Circuit Relay v2 in py-libp2p. It includes three components:

1. A relay node that provides relay services
2. A destination node that accepts relayed connections
3. A source node that connects to the destination through the relay

Prerequisites
-------------

First, ensure you have py-libp2p installed:

.. code-block:: console

    $ python -m pip install libp2p
    Collecting libp2p
    ...
    Successfully installed libp2p-x.x.x

Relay Node
----------

Create a file named ``relay_node.py`` with the following content:

.. code-block:: python

    import trio
    import logging
    import multiaddr
    import traceback

    from libp2p import new_host
    from libp2p.relay.circuit_v2.protocol import CircuitV2Protocol
    from libp2p.relay.circuit_v2.transport import CircuitV2Transport
    from libp2p.relay.circuit_v2.config import RelayConfig
    from libp2p.tools.async_service import background_trio_service

    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger("relay_node")

    async def run_relay():
        listen_addr = multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/9000")
        host = new_host()

        config = RelayConfig(
            enable_hop=True,  # Act as a relay
            enable_stop=True,  # Accept relayed connections
            enable_client=False,  # Don't use other relays
            max_circuit_duration=3600,  # 1 hour
            max_circuit_bytes=1024 * 1024 * 10,  # 10MB
        )

        # Initialize the relay protocol with allow_hop=True to act as a relay
        protocol = CircuitV2Protocol(host, limits=config.limits, allow_hop=True)
        print(f"Created relay protocol with hop enabled: {protocol.allow_hop}")

        # Start the protocol service
        async with host.run(listen_addrs=[listen_addr]):
            peer_id = host.get_id()
            print("\n" + "="*50)
            print(f"Relay node started with ID: {peer_id}")
            print(f"Relay node multiaddr: /ip4/127.0.0.1/tcp/9000/p2p/{peer_id}")
            print("="*50 + "\n")
            print(f"Listening on: {host.get_addrs()}")

            try:
                async with background_trio_service(protocol):
                    print("Protocol service started")

                    transport = CircuitV2Transport(host, protocol, config)
                    print("Relay service started successfully")
                    print(f"Relay limits: {protocol.limits}")

                    while True:
                        await trio.sleep(10)
                        print("Relay node still running...")
                        print(f"Active connections: {len(host.get_network().connections)}")
            except Exception as e:
                print(f"Error in relay service: {e}")
                traceback.print_exc()

    if __name__ == "__main__":
        try:
            trio.run(run_relay)
        except Exception as e:
            print(f"Error running relay: {e}")
            traceback.print_exc()

Destination Node
----------------

Create a file named ``destination_node.py`` with the following content:

.. code-block:: python

    import trio
    import logging
    import multiaddr
    import traceback
    import sys

    from libp2p import new_host
    from libp2p.relay.circuit_v2.protocol import CircuitV2Protocol
    from libp2p.relay.circuit_v2.transport import CircuitV2Transport
    from libp2p.relay.circuit_v2.config import RelayConfig
    from libp2p.peer.peerinfo import info_from_p2p_addr
    from libp2p.tools.async_service import background_trio_service

    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger("destination_node")

    async def handle_echo_stream(stream):
        """Handle incoming stream by echoing received data."""
        try:
            print(f"New echo stream from: {stream.get_protocol()}")
            while True:
                data = await stream.read(1024)
                if not data:
                    print("Stream closed by remote")
                    break

                message = data.decode('utf-8')
                print(f"Received: {message}")

                response = f"Echo: {message}".encode('utf-8')
                await stream.write(response)
                print(f"Sent response: Echo: {message}")
        except Exception as e:
            print(f"Error handling stream: {e}")
            traceback.print_exc()
        finally:
            await stream.close()
            print("Stream closed")

    async def run_destination(relay_peer_id=None):
        """
        Run a simple destination node that accepts connections.
        This is a simplified version that doesn't use the relay functionality.
        """
        listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/9001")
        host = new_host()

        # Configure as a relay receiver (stop)
        config = RelayConfig(
            enable_stop=True,  # Accept relayed connections
            enable_client=True,  # Use relays for outbound connections
            max_circuit_duration=3600,  # 1 hour
            max_circuit_bytes=1024 * 1024 * 10,  # 10MB
        )

        # Initialize the relay protocol
        protocol = CircuitV2Protocol(host, limits=config.limits, allow_hop=False)

        async with host.run(listen_addrs=[listen_addr]):
            # Print host information
            dest_peer_id = host.get_id()
            print("\n" + "="*50)
            print(f"Destination node started with ID: {dest_peer_id}")
            print(f"Use this ID in the source node: {dest_peer_id}")
            print("="*50 + "\n")
            print(f"Listening on: {host.get_addrs()}")

            # Set stream handler for the echo protocol
            host.set_stream_handler("/echo/1.0.0", handle_echo_stream)
            print("Registered echo protocol handler")

            # Start the protocol service in the background
            async with background_trio_service(protocol):
                print("Protocol service started")

                # Create and register the transport
                transport = CircuitV2Transport(host, protocol, config)
                print("Transport created")

                # Create a listener for relayed connections
                listener = transport.create_listener(handle_echo_stream)
                print("Created relay listener")

                # Start listening for relayed connections
                async with trio.open_nursery() as nursery:
                    await listener.listen("/p2p-circuit", nursery)
                    print("Destination node ready to accept relayed connections")

                    if not relay_peer_id:
                        print("No relay peer ID provided. Please enter the relay's peer ID:")
                        print("Waiting for relay peer ID input...")
                        while True:
                            if sys.stdin.isatty():  # Only try to read from stdin if it's a terminal
                                try:
                                    relay_peer_id = input("Enter relay peer ID: ").strip()
                                    if relay_peer_id:
                                        break
                                except EOFError:
                                    await trio.sleep(5)
                            else:
                                print("No terminal detected. Waiting for relay peer ID as command line argument.")
                                await trio.sleep(10)
                                continue

                    # Connect to the relay node with the provided relay peer ID
                    relay_addr_str = f"/ip4/127.0.0.1/tcp/9000/p2p/{relay_peer_id}"
                    print(f"Connecting to relay at {relay_addr_str}")

                    try:
                        # Convert string address to multiaddr, then to peer info
                        relay_maddr = multiaddr.Multiaddr(relay_addr_str)
                        relay_peer_info = info_from_p2p_addr(relay_maddr)
                        await host.connect(relay_peer_info)
                        print("Connected to relay successfully")

                        # Add the relay to the transport's discovery
                        transport.discovery._add_relay(relay_peer_info.peer_id)
                        print(f"Added relay {relay_peer_info.peer_id} to discovery")

                        # Keep the node running
                        while True:
                            await trio.sleep(10)
                            print("Destination node still running...")
                    except Exception as e:
                        print(f"Failed to connect to relay: {e}")
                        traceback.print_exc()

    if __name__ == "__main__":
        print("Starting destination node...")
        relay_id = None
        if len(sys.argv) > 1:
            relay_id = sys.argv[1]
            print(f"Using provided relay ID: {relay_id}")
        trio.run(run_destination, relay_id)

Source Node
-----------

Create a file named ``source_node.py`` with the following content:

.. code-block:: python

    import trio
    import logging
    import multiaddr
    import traceback
    import sys

    from libp2p import new_host
    from libp2p.peer.peerinfo import PeerInfo
    from libp2p.peer.id import ID
    from libp2p.relay.circuit_v2.protocol import CircuitV2Protocol
    from libp2p.relay.circuit_v2.transport import CircuitV2Transport
    from libp2p.relay.circuit_v2.config import RelayConfig
    from libp2p.peer.peerinfo import info_from_p2p_addr
    from libp2p.tools.async_service import background_trio_service
    from libp2p.relay.circuit_v2.discovery import RelayInfo

    # Configure logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger("source_node")

    async def run_source(relay_peer_id=None, destination_peer_id=None):
        # Create a libp2p host
        listen_addr = multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/9002")
        host = new_host()

        # Configure as a relay client
        config = RelayConfig(
            enable_client=True,  # Use relays for outbound connections
            max_circuit_duration=3600,  # 1 hour
            max_circuit_bytes=1024 * 1024 * 10,  # 10MB
        )

        # Initialize the relay protocol
        protocol = CircuitV2Protocol(host, limits=config.limits, allow_hop=False)

        # Start the protocol service
        async with host.run(listen_addrs=[listen_addr]):
            # Print host information
            print(f"Source node started with ID: {host.get_id()}")
            print(f"Listening on: {host.get_addrs()}")

            # Start the protocol service in the background
            async with background_trio_service(protocol):
                print("Protocol service started")

                # Create and register the transport
                transport = CircuitV2Transport(host, protocol, config)

                # Get relay peer ID if not provided
                if not relay_peer_id:
                    print("No relay peer ID provided. Please enter the relay's peer ID:")
                    while True:
                        if sys.stdin.isatty():  # Only try to read from stdin if it's a terminal
                            try:
                                relay_peer_id = input("Enter relay peer ID: ").strip()
                                if relay_peer_id:
                                    break
                            except EOFError:
                                await trio.sleep(5)
                        else:
                            print("No terminal detected. Waiting for relay peer ID as command line argument.")
                            await trio.sleep(10)
                            continue

                # Connect to the relay node with the provided relay peer ID
                relay_addr_str = f"/ip4/127.0.0.1/tcp/9000/p2p/{relay_peer_id}"
                print(f"Connecting to relay at {relay_addr_str}")

                try:
                    # Convert string address to multiaddr, then to peer info
                    relay_maddr = multiaddr.Multiaddr(relay_addr_str)
                    relay_peer_info = info_from_p2p_addr(relay_maddr)
                    await host.connect(relay_peer_info)
                    print("Connected to relay successfully")

                    # Manually add the relay to the discovery service
                    relay_id = relay_peer_info.peer_id
                    now = trio.current_time()

                    # Create relay info and add it to discovery
                    relay_info = RelayInfo(
                        peer_id=relay_id,
                        discovered_at=now,
                        last_seen=now
                    )
                    transport.discovery._discovered_relays[relay_id] = relay_info
                    print(f"Added relay {relay_id} to discovery")

                    # Start relay discovery in the background
                    async with background_trio_service(transport.discovery):
                        print("Relay discovery started")

                        # Wait for relay discovery
                        await trio.sleep(5)
                        print("Relay discovery completed")

                        # Get destination peer ID if not provided
                        if not destination_peer_id:
                            print("No destination peer ID provided. Please enter the destination's peer ID:")
                            while True:
                                if sys.stdin.isatty():  # Only try to read from stdin if it's a terminal
                                    try:
                                        destination_peer_id = input("Enter destination peer ID: ").strip()
                                        if destination_peer_id:
                                            break
                                    except EOFError:
                                        await trio.sleep(5)
                                else:
                                    print("No terminal detected. Waiting for destination peer ID as command line argument.")
                                    await trio.sleep(10)
                                    continue

                        print(f"Attempting to connect to {destination_peer_id} via relay")

                        # Check if we have any discovered relays
                        discovered_relays = list(transport.discovery._discovered_relays.keys())
                        print(f"Discovered relays: {discovered_relays}")

                        try:
                            # Create a circuit relay multiaddr for the destination
                            dest_id = ID.from_base58(destination_peer_id)

                            # Create a circuit multiaddr that includes the relay
                            # Format: /ip4/127.0.0.1/tcp/9000/p2p/RELAY_ID/p2p-circuit/p2p/DEST_ID
                            circuit_addr = multiaddr.Multiaddr(f"{relay_addr_str}/p2p-circuit/p2p/{destination_peer_id}")
                            print(f"Created circuit address: {circuit_addr}")

                            # Dial using the circuit address
                            connection = await transport.dial(circuit_addr)
                            print("Connection established through relay!")

                            # Open a stream using the echo protocol
                            stream = await connection.new_stream("/echo/1.0.0")

                            # Send messages periodically
                            for i in range(5):
                                message = f"Hello from source, message {i+1}"
                                print(f"Sending: {message}")

                                await stream.write(message.encode('utf-8'))
                                response = await stream.read(1024)

                                print(f"Received: {response.decode('utf-8')}")
                                await trio.sleep(1)

                            # Close the stream
                            await stream.close()
                            print("Stream closed")
                        except Exception as e:
                            print(f"Error connecting through relay: {e}")
                            print("Detailed error:")
                            traceback.print_exc()

                        # Keep the node running for a while
                        await trio.sleep(30)
                        print("Source node shutting down")

                except Exception as e:
                    print(f"Error: {e}")
                    traceback.print_exc()

    if __name__ == "__main__":
        relay_id = None
        dest_id = None

        # Parse command line arguments if provided
        if len(sys.argv) > 1:
            relay_id = sys.argv[1]
            print(f"Using provided relay ID: {relay_id}")

        if len(sys.argv) > 2:
            dest_id = sys.argv[2]
            print(f"Using provided destination ID: {dest_id}")

        trio.run(run_source, relay_id, dest_id)

Running the Example
-------------------

1. First, start the relay node:

   .. code-block:: console

       $ python relay_node.py
       Created relay protocol with hop enabled: True

       ==================================================
       Relay node started with ID: QmaUigQJ9nJERa6GaZuyfaiX91QjYwoQJ46JS3k7ys7SLx
       Relay node multiaddr: /ip4/127.0.0.1/tcp/9000/p2p/QmaUigQJ9nJERa6GaZuyfaiX91QjYwoQJ46JS3k7ys7SLx
       ==================================================

       Listening on: [<Multiaddr /ip4/0.0.0.0/tcp/9000/p2p/QmaUigQJ9nJERa6GaZuyfaiX91QjYwoQJ46JS3k7ys7SLx>]
       Protocol service started
       Relay service started successfully
       Relay limits: RelayLimits(duration=3600, data=10485760, max_circuit_conns=8, max_reservations=4)

   Note the relay node\'s peer ID (in this example: `QmaUigQJ9nJERa6GaZuyfaiX91QjYwoQJ46JS3k7ys7SLx`). You\'ll need this for the other nodes.

2. Next, start the destination node:

   .. code-block:: console

       $ python destination_node.py
       Starting destination node...

       ==================================================
       Destination node started with ID: QmPBr38KeQG2ibyL4fxq6yJWpfoVNCqJMHBdNyn1Qe4h5s
       Use this ID in the source node: QmPBr38KeQG2ibyL4fxq6yJWpfoVNCqJMHBdNyn1Qe4h5s
       ==================================================

       Listening on: [<Multiaddr /ip4/0.0.0.0/tcp/9001/p2p/QmPBr38KeQG2ibyL4fxq6yJWpfoVNCqJMHBdNyn1Qe4h5s>]
       Registered echo protocol handler
       Protocol service started
       Transport created
       Created relay listener
       Destination node ready to accept relayed connections
       No relay peer ID provided. Please enter the relay\'s peer ID:
       Waiting for relay peer ID input...
       Enter relay peer ID: QmaUigQJ9nJERa6GaZuyfaiX91QjYwoQJ46JS3k7ys7SLx
       Connecting to relay at /ip4/127.0.0.1/tcp/9000/p2p/QmaUigQJ9nJERa6GaZuyfaiX91QjYwoQJ46JS3k7ys7SLx
       Connected to relay successfully
       Added relay QmaUigQJ9nJERa6GaZuyfaiX91QjYwoQJ46JS3k7ys7SLx to discovery
       Destination node still running...

   Note the destination node's peer ID (in this example: `QmPBr38KeQG2ibyL4fxq6yJWpfoVNCqJMHBdNyn1Qe4h5s`). You'll need this for the source node.

3. Finally, start the source node:

   .. code-block:: console

       $ python source_node.py
       Source node started with ID: QmPyM56cgmFoHTgvMgGfDWRdVRQznmxCDDDg2dJ8ygVXj3
       Listening on: [<Multiaddr /ip4/0.0.0.0/tcp/9002/p2p/QmPyM56cgmFoHTgvMgGfDWRdVRQznmxCDDDg2dJ8ygVXj3>]
       Protocol service started
       No relay peer ID provided. Please enter the relay\'s peer ID:
       Enter relay peer ID: QmaUigQJ9nJERa6GaZuyfaiX91QjYwoQJ46JS3k7ys7SLx
       Connecting to relay at /ip4/127.0.0.1/tcp/9000/p2p/QmaUigQJ9nJERa6GaZuyfaiX91QjYwoQJ46JS3k7ys7SLx
       Connected to relay successfully
       Added relay QmaUigQJ9nJERa6GaZuyfaiX91QjYwoQJ46JS3k7ys7SLx to discovery
       Relay discovery started
       Relay discovery completed
       No destination peer ID provided. Please enter the destination\'s peer ID:
       Enter destination peer ID: QmPBr38KeQG2ibyL4fxq6yJWpfoVNCqJMHBdNyn1Qe4h5s
       Attempting to connect to QmPBr38KeQG2ibyL4fxq6yJWpfoVNCqJMHBdNyn1Qe4h5s via relay
       Discovered relays: [<libp2p.peer.id.ID (QmaUigQJ9nJERa6GaZuyfaiX91QjYwoQJ46JS3k7ys7SLx)>]
       Created circuit address: /ip4/127.0.0.1/tcp/9000/p2p/QmaUigQJ9nJERa6GaZuyfaiX91QjYwoQJ46JS3k7ys7SLx/p2p-circuit/p2p/QmPBr38KeQG2ibyL4fxq6yJWpfoVNCqJMHBdNyn1Qe4h5s

   At this point, the source node will establish a connection through the relay to the destination node and start sending messages.

4. Alternatively, you can provide the peer IDs as command-line arguments:

   .. code-block:: console

       # For the destination node (provide relay ID)
       $ python destination_node.py QmaUigQJ9nJERa6GaZuyfaiX91QjYwoQJ46JS3k7ys7SLx

       # For the source node (provide both relay and destination IDs)
       $ python source_node.py QmaUigQJ9nJERa6GaZuyfaiX91QjYwoQJ46JS3k7ys7SLx QmPBr38KeQG2ibyL4fxq6yJWpfoVNCqJMHBdNyn1Qe4h5s

This example demonstrates how to use Circuit Relay v2 to establish connections between peers that cannot connect directly. The peer IDs are dynamically generated for each node, and the relay facilitates communication between the source and destination nodes.
