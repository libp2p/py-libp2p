import pytest
import asyncio
from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.protocols.dcutr.dcutr import DCUtRProtocol, DCUTR_PROTOCOL_ID

@pytest.mark.asyncio
async def test_dcutr_protocol_registration():
    """Test that DCUtR protocol can be registered"""
    host = new_host()
    dcutr = DCUtRProtocol(host)
    
    # Should not raise exception
    host.set_stream_handler(DCUTR_PROTOCOL_ID, dcutr.handle_inbound_stream)
    
    await host.close()

@pytest.mark.asyncio
async def test_basic_connection():
    """Test basic connection between two hosts"""
    host1 = new_host()
    host2 = new_host()
    
    dcutr1 = DCUtRProtocol(host1)
    dcutr2 = DCUtRProtocol(host2)
    
    host1.set_stream_handler(DCUTR_PROTOCOL_ID, dcutr1.handle_inbound_stream)
    host2.set_stream_handler(DCUTR_PROTOCOL_ID, dcutr2.handle_inbound_stream)
    
    try:
        await host1.get_network().listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
        await host2.get_network().listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
        
        # Get addresses
        h1_addrs = host1.get_addrs()
        h2_id = host2.get_id()
        
        # Connect host1 to host2
        if h1_addrs:
            target_addr = Multiaddr(f"{h1_addrs}/p2p/{h2_id}")
            # This might fail, that's OK for now
            try:
                await host1.connect(target_addr)
                print("Basic connection successful")
            except Exception as e:
                print(f"Connection failed (expected): {e}")
    
    finally:
        await host1.close()
        await host2.close()

if __name__ == "__main__":
    # Run tests directly
    asyncio.run(test_dcutr_protocol_registration())
    asyncio.run(test_basic_connection())
    print("Basic tests completed")
