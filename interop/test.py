import os
import redis
import multiaddr
import trio
from libp2p import new_host
from libp2p.peer.peerinfo import info_from_p2p_addr

async def run(port: int, role: str) -> None:
    # Create host and start listening
    host = new_host()
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")
    
    async with host.run(listen_addrs=[listen_addr]), trio.open_nursery() as nursery:
        if role == 'listener':
            # Get the node's address
            addr = host.get_addrs()[0]
            print(f"Listener started on {addr}")
            
            # Push address to Redis
            r = redis.Redis(host=os.environ['REDIS_HOST'])
            r.rpush('listener_addr', str(addr))
            
            # Keep running
            await trio.sleep_forever()
        else:
            try:
                # Get listener address from Redis
                r = redis.Redis(host=os.environ['REDIS_HOST'])
                addr = r.blpop('listener_addr', timeout=30)
                if addr is None:
                    print("Timeout waiting for listener address")
                    return
                addr = addr[1].decode()
                
                print(f"Dialer connecting to {addr}")
                
                # Connect to listener
                maddr = multiaddr.Multiaddr(addr)
                info = info_from_p2p_addr(maddr)
                await host.connect(info)
                
                print("Connection successful!")
                return
            except Exception as e:
                print(f"Dialer error: {e}")
                return

def main() -> None:
    role = os.environ['ROLE']
    # Use different ports for listener and dialer
    port = 8000 if role == 'listener' else 8001
    
    try:
        trio.run(run, port, role)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()