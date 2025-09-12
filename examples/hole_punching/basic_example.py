import asyncio
import argparse
from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.protocols.dcutr.dcutr import DCUtRProtocol, DCUTR_PROTOCOL_ID

async def run_listener():
    """Run as listener peer"""
    print("Starting listener...")
    
    host = new_host()
    dcutr = DCUtRProtocol(host)
    
    # Register DCUtR handler
    host.set_stream_handler(DCUTR_PROTOCOL_ID, dcutr.handle_inbound_stream)
    
    # Listen on port
    await host.get_network().listen(Multiaddr("/ip4/127.0.0.1/tcp/4002"))
    
    print(f"Listener ID: {host.get_id()}")
    print(f"Addresses: {host.get_addrs()}")
    
    # Keep running
    await asyncio.sleep(60)
    await host.close()

async def run_dialer(target_id):
    """Run as dialer peer"""
    print("Starting dialer...")
    
    host = new_host()
    dcutr = DCUtRProtocol(host)
    
    host.set_stream_handler(DCUTR_PROTOCOL_ID, dcutr.handle_inbound_stream)
    
    await host.get_network().listen(Multiaddr("/ip4/127.0.0.1/tcp/4003"))
    
    print(f"Dialer ID: {host.get_id()}")
    
    try:
        # Connect to target
        target_addr = Multiaddr(f"/ip4/127.0.0.1/tcp/4002/p2p/{target_id}")
        await host.connect(target_addr)
        print("Connected!")
        
        # Try hole punch
        success = await dcutr.upgrade_connection(target_id)
        print(f"Hole punch result: {success}")
        
    except Exception as e:
        print(f"Error: {e}")
    
    await host.close()

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["listen", "dial"], required=True)
    parser.add_argument("--target", help="Target peer ID for dial mode")
    
    args = parser.parse_args()
    
    if args.mode == "listen":
        await run_listener()
    else:
        if not args.target:
            print("Need --target for dial mode")
            return
        await run_dialer(args.target)

if __name__ == "__main__":
    asyncio.run(main())
