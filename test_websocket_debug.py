#!/usr/bin/env python3
"""
Debug script to test basic WebSocket functionality without libp2p hosts
"""
import asyncio
import trio
from multiaddr import Multiaddr
from libp2p.transport.websocket.transport import WebsocketTransport
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.crypto.secp256k1 import create_new_key_pair  
from libp2p.security.insecure.transport import InsecureTransport, PLAINTEXT_PROTOCOL_ID
from libp2p.stream_muxer.yamux import Yamux
from libp2p.custom_types import TProtocol

async def test_basic_websocket_connection():
    """Test basic WebSocket dial and listen without hosts"""
    print("Starting basic WebSocket connection test...")
    
    # Create upgrader
    key_pair = create_new_key_pair()
    upgrader = TransportUpgrader(
        secure_transports_by_protocol={
            TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
        },
        muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
    )
    
    # Create transport
    transport = WebsocketTransport(upgrader)
    print("Created WebSocket transport")
    
    # Test listener creation
    async def simple_handler(conn):
        print(f"Handler called with connection: {conn}")
        await trio.sleep(0.1)
        await conn.close()
    
    listener = transport.create_listener(simple_handler)
    print("Created listener")
    
    # Test listening with proper nursery
    listen_addr = Multiaddr("/ip4/127.0.0.1/tcp/0/ws")
    print(f"Starting to listen on {listen_addr}")
    
    try:
        async with trio.open_nursery() as nursery:
            print("Created nursery")
            await listener.listen(listen_addr, nursery)
            print("Listener started successfully")
            
            # Get the actual listen address
            addrs = listener.get_addrs()
            print(f"Listening on: {addrs}")
            
            if addrs:
                actual_addr = addrs[0]
                print(f"Trying to dial {actual_addr}")
                
                # Test dialing
                try:
                    conn = await transport.dial(actual_addr)
                    print(f"Dial successful, got connection: {conn}")
                    await conn.close()
                    print("Connection closed successfully")
                except Exception as e:
                    print(f"Dial failed: {e}")
                    import traceback
                    traceback.print_exc()
            
            print("Closing listener...")
            await listener.close()
            print("Listener closed")
        
    except Exception as e:
        print(f"Listen failed: {e}")
        import traceback
        traceback.print_exc()
    
    print("Test completed")

if __name__ == "__main__":
    trio.run(test_basic_websocket_connection)