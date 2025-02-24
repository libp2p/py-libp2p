import os
import socket
import redis
import multiaddr
import trio
from libp2p import new_host
from libp2p.peer.peerinfo import info_from_p2p_addr

async def run(port: int, role: str) -> None:
    # Create host
    host = new_host()
    
    # Set up the listen address
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")
    
    async with host.run(listen_addrs=[listen_addr]), trio.open_nursery() as nursery:
        if role == 'listener':
            # Get the container's actual IP address
            hostname = socket.gethostname()
            try:
                actual_ip = socket.gethostbyname(hostname)
                print(f"Container IP: {actual_ip}")
                
                # Create address with actual IP for advertising
                peer_id = host.get_id().pretty()
                advertise_addr = f"/ip4/{actual_ip}/tcp/{port}/p2p/{peer_id}"
                print(f"Listener started on {advertise_addr}")
                
                # Push address to Redis
                redis_host = os.environ.get('REDIS_HOST', 'redis')
                redis_port = int(os.environ.get('REDIS_PORT', 6379))
                print(f"Connecting to Redis at {redis_host}:{redis_port}")
                
                r = redis.Redis(host=redis_host, port=redis_port)
                r.delete('listener_addr')  # Clear any previous address
                r.rpush('listener_addr', advertise_addr)
                print("Address published to Redis")
                
                # Keep running
                await trio.sleep_forever()
            except Exception as e:
                print(f"Listener error: {e}")
                return
        else:  # dialer
            try:
                # Get listener address from Redis
                redis_host = os.environ.get('REDIS_HOST', 'redis')
                redis_port = int(os.environ.get('REDIS_PORT', 6379))
                print(f"Connecting to Redis at {redis_host}:{redis_port}")
                
                r = redis.Redis(host=redis_host, port=redis_port)
                
                # Try to get the listener address
                print("Waiting for listener address...")
                addr = r.blpop('listener_addr', timeout=30)
                if addr is None:
                    print("Timeout waiting for listener address")
                    return
                addr = addr[1].decode()
                
                # If we have an environment variable for the listener address, use that instead
                env_addr = os.environ.get('LISTENER_ADDR')
                if env_addr:
                    addr = env_addr
                    print(f"Using address from environment: {addr}")
                
                print(f"Dialer connecting to {addr}")
                
                # Connect to listener
                maddr = multiaddr.Multiaddr(addr)
                info = info_from_p2p_addr(maddr)
                await host.connect(info)
                
                print("Connection successful!")
                return
            except Exception as e:
                print(f"Dialer error: {e}")
                raise  # Re-raise to see full stack trace for debugging

def main() -> None:
    # Get configuration from environment variables
    role = os.environ.get('ROLE')
    if role not in ['listener', 'dialer']:
        print("Error: ROLE must be either 'listener' or 'dialer'")
        return
    
    # Use different ports for listener and dialer
    port = int(os.environ.get('LISTENER_PORT', 8000))
    if role == 'dialer':
        port = port + 1
    
    print(f"Starting {role} on port {port}")
    
    try:
        trio.run(run, port, role)
    except KeyboardInterrupt:
        print("Interrupted by user")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()