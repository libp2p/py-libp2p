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

    import asyncio
    import logging

    from libp2p import new_host
    from libp2p.relay.circuit_v2.protocol import CircuitV2Protocol
    from libp2p.relay.circuit_v2.transport import CircuitV2Transport
    from libp2p.relay.circuit_v2.config import RelayConfig

    # Configure logging
    logging.basicConfig(level=logging.DEBUG)

    async def run_relay():
        # Create a libp2p host
        host = await new_host(
            transport_opt=["/ip4/0.0.0.0/tcp/9000"],  # Listen on all interfaces, port 9000
        )

        # Print host information
        print(f"Relay node started with ID: {host.get_id()}")
        print(f"Listening on: {host.get_addrs()}")

        # Configure relay with hop enabled
        config = RelayConfig(
            enable_hop=True,  # Act as a relay
            enable_stop=True,  # Accept relayed connections
            enable_client=False,  # Don't use other relays
        )

        # Initialize the relay protocol
        protocol = CircuitV2Protocol(host, allow_hop=True)

        # Start the protocol service
        async with host.get_network().nursery:
            await host.get_network().nursery.start(protocol.run)

            # Create and register the transport
            transport = CircuitV2Transport(host, protocol, config)

            print("Relay service started successfully")

            # Keep the node running
            while True:
                await asyncio.sleep(10)
                print(f"Active relay connections: {len(protocol._active_relays)}")

    if __name__ == "__main__":
        asyncio.run(run_relay())

Destination Node
----------------

Create a file named ``destination_node.py`` with the following content:

.. code-block:: python

    import asyncio
    import logging

    from libp2p import new_host
    from libp2p.relay.circuit_v2.protocol import CircuitV2Protocol
    from libp2p.relay.circuit_v2.transport import CircuitV2Transport
    from libp2p.relay.circuit_v2.config import RelayConfig

    # Configure logging
    logging.basicConfig(level=logging.DEBUG)

    async def handle_echo_stream(stream):
        """Handle incoming stream by echoing received data."""
        try:
            while True:
                data = await stream.read(1024)
                if not data:
                    break

                message = data.decode('utf-8')
                print(f"Received: {message}")

                response = f"Echo: {message}".encode('utf-8')
                await stream.write(response)
        except Exception as e:
            print(f"Error handling stream: {e}")
        finally:
            await stream.close()

    async def run_destination():
        # Create a libp2p host
        host = await new_host(
            transport_opt=["/ip4/0.0.0.0/tcp/9001"],  # Listen on all interfaces, port 9001
        )

        # Print host information
        print(f"Destination node started with ID: {host.get_id()}")
        print(f"Listening on: {host.get_addrs()}")

        # Set stream handler for the echo protocol
        host.set_stream_handler("/echo/1.0.0", handle_echo_stream)

        # Configure as a relay receiver (stop)
        config = RelayConfig(
            enable_stop=True,  # Accept relayed connections
            enable_client=True,  # Use relays for outbound connections
        )

        # Initialize the relay protocol
        protocol = CircuitV2Protocol(host)

        # Start the protocol service
        async with host.get_network().nursery:
            await host.get_network().nursery.start(protocol.run)

            # Create and register the transport
            transport = CircuitV2Transport(host, protocol, config)

            # Create a listener for relayed connections
            listener = transport.create_listener(lambda stream: handle_echo_stream(stream))

            # Start listening
            await listener.listen(None, host.get_network().nursery)

            print("Destination node ready to accept relayed connections")

            # Connect to the relay node (replace with actual relay address)
            relay_addr = "/ip4/127.0.0.1/tcp/9000/p2p/RELAY_PEER_ID"  # Replace RELAY_PEER_ID
            print(f"Connecting to relay at {relay_addr}")

            try:
                await host.connect(relay_addr)
                print("Connected to relay successfully")
            except Exception as e:
                print(f"Failed to connect to relay: {e}")

            # Keep the node running
            while True:
                await asyncio.sleep(10)
                print("Destination node still running...")

    if __name__ == "__main__":
        asyncio.run(run_destination())

Source Node
-----------

Create a file named ``source_node.py`` with the following content:

.. code-block:: python

    import asyncio
    import logging

    from libp2p import new_host
    from libp2p.peer.peerinfo import PeerInfo
    from libp2p.peer.id import ID
    from libp2p.relay.circuit_v2.protocol import CircuitV2Protocol
    from libp2p.relay.circuit_v2.transport import CircuitV2Transport
    from libp2p.relay.circuit_v2.config import RelayConfig

    # Configure logging
    logging.basicConfig(level=logging.DEBUG)

    async def run_source():
        # Create a libp2p host
        host = await new_host(
            transport_opt=["/ip4/0.0.0.0/tcp/9002"],  # Listen on all interfaces, port 9002
        )

        # Print host information
        print(f"Source node started with ID: {host.get_id()}")
        print(f"Listening on: {host.get_addrs()}")

        # Configure as a relay client
        config = RelayConfig(
            enable_client=True,  # Use relays for outbound connections
        )

        # Initialize the relay protocol
        protocol = CircuitV2Protocol(host)

        # Start the protocol service
        async with host.get_network().nursery:
            await host.get_network().nursery.start(protocol.run)

            # Create and register the transport
            transport = CircuitV2Transport(host, protocol, config)

            # Connect to the relay node (replace with actual relay address)
            relay_addr = "/ip4/127.0.0.1/tcp/9000/p2p/RELAY_PEER_ID"  # Replace RELAY_PEER_ID
            print(f"Connecting to relay at {relay_addr}")

            try:
                await host.connect(relay_addr)
                print("Connected to relay successfully")

                # Start relay discovery
                await host.get_network().nursery.start(transport.discovery.run)

                # Wait for relay discovery
                await asyncio.sleep(5)

                # Connect to destination through relay
                destination_peer_id = "DESTINATION_PEER_ID"  # Replace with actual peer ID
                peer_info = PeerInfo(ID.from_base58(destination_peer_id), [])

                print(f"Attempting to connect to {destination_peer_id} via relay")

                # The transport will automatically select a relay
                connection = await transport.dial(peer_info)
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
                    await asyncio.sleep(1)

                # Close the stream
                await stream.close()
                print("Stream closed")

            except Exception as e:
                print(f"Error: {e}")

            # Keep the node running for a while
            await asyncio.sleep(30)
            print("Source node shutting down")

    if __name__ == "__main__":
        asyncio.run(run_source())

Running the Example
-------------------

1. First, start the relay node:

   .. code-block:: console

       $ python relay_node.py
       Relay node started with ID: QmRelay...
       Listening on: ['/ip4/127.0.0.1/tcp/9000', '/ip4/192.168.1.100/tcp/9000']
       Relay service started successfully

2. Update the ``destination_node.py`` and ``source_node.py`` files with the actual relay peer ID.

3. Start the destination node:

   .. code-block:: console

       $ python destination_node.py
       Destination node started with ID: QmDest...
       Listening on: ['/ip4/127.0.0.1/tcp/9001', '/ip4/192.168.1.100/tcp/9001']
       Connected to relay successfully
       Destination node ready to accept relayed connections

4. Update the ``source_node.py`` file with the destination peer ID.

5. Start the source node:

   .. code-block:: console

       $ python source_node.py
       Source node started with ID: QmSource...
       Listening on: ['/ip4/127.0.0.1/tcp/9002', '/ip4/192.168.1.100/tcp/9002']
       Connected to relay successfully
       Attempting to connect to QmDest... via relay
       Connection established through relay!
       Sending: Hello from source, message 1
       Received: Echo: Hello from source, message 1
       Sending: Hello from source, message 2
       Received: Echo: Hello from source, message 2

This example demonstrates the complete flow of using Circuit Relay v2 to establish connections between peers that cannot connect directly.
