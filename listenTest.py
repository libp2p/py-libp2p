#!/usr/bin/env python3
import asyncio
import logging
import secrets
import sys

try:
    import trio
    from multiaddr import Multiaddr
    from libp2p import new_host
    from libp2p.crypto.secp256k1 import create_new_key_pair
    from libp2p.transport.webrtc.private_to_private import WebRTCTransport
    from libp2p.transport.webrtc.multiaddr_protocols import register_webrtc_protocols
except ImportError as e:
    print(f"Import error: {e}")
    exit(1)

logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class WebRTCListenerTest:
    def __init__(self, port: int = 9090):
        self.port = port
        self.host = None
        self.transport = None
        self.protocol = "/webrtc-pvp-test/1.0.0"
    
    async def create_host(self):
        try:
            register_webrtc_protocols()
            logger.info("WebRTC protocols registered")
            secret = secrets.token_bytes(32)
            key_pair = create_new_key_pair(secret)
            self.host = new_host(key_pair=key_pair)
            logger.info(f"Host created: {self.host.get_id()}")
            return True
        except Exception as e:
            logger.error(f"Host creation failed: {e}", exc_info=True)
            return False
    
    async def setup_webrtc_transport(self):
        try:
            self.transport = WebRTCTransport()
            self.transport.set_host(self.host)
            await self.transport.start()
            logger.info("WebRTC transport started")
            return True
        except Exception as e:
            logger.error(f"WebRTC transport setup failed: {e}", exc_info=True)
            return False
    
    async def handle_stream(self, stream):
        try:
            peer_id = getattr(getattr(stream, "muxed_conn", None), "peer_id", getattr(stream, "peer_id", "unknown"))
            data = await asyncio.wait_for(stream.read(), timeout=30.0)
            if data:
                message = data.decode('utf-8', errors='ignore')
                response = f"WebRTC Listener Echo: {message}"
                await stream.write(response.encode('utf-8'))
        except asyncio.TimeoutError:
            logger.info(f"Timeout for {peer_id}")
        except Exception as e:
            logger.error(f"Stream error: {e}")
        finally:
            try:
                await stream.close()
            except:
                pass
    
    async def register_protocol(self):
        try:
            self.host.set_stream_handler(self.protocol, self.handle_stream)
            logger.info(f"Protocol registered: {self.protocol}")
            return True
        except Exception as e:
            logger.error(f"Protocol registration failed: {e}")
            return False
    
    async def create_listener(self):
        try:
            listener = self.transport.create_listener(self.handle_stream)
            async with trio.open_nursery() as nursery:
                dummy_addr = Multiaddr("/ip4/0.0.0.0/tcp/0")
                success = await listener.listen(dummy_addr, nursery)
                if success:
                    logger.info("WebRTC listener started")
                    logger.info(f"Addresses: {listener.get_addrs()}")
                    return listener, nursery
                return None, None
        except Exception as e:
            logger.error(f"Listener creation failed: {e}", exc_info=True)
            return None, None
    
    async def start_listener(self):
        if not await self.create_host():
            return False
        if not await self.setup_webrtc_transport():
            return False
        if not await self.register_protocol():
            return False
        try:
            tcp_addr = Multiaddr(f"/ip4/127.0.0.1/tcp/{self.port}")
            async with self.host.run(listen_addrs=[tcp_addr]):
                print("=" * 60)
                print("WebRTC Listener Started Successfully")
                print("=" * 60)
                print(f"Peer ID: {self.host.get_id()}")
                print(f"Protocol: {self.protocol}")
                print(f"Address: {tcp_addr}")
                print("=" * 60)
                await trio.sleep_forever()
        except KeyboardInterrupt:
            logger.info("Listener stopped by user")
        except Exception as e:
            logger.error(f"Listener failed: {e}", exc_info=True)
            return False
        return True


async def main():
    port = 9090
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            sys.exit(1)
    test = WebRTCListenerTest(port=port)
    try:
        success = await test.start_listener()
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        trio.run(main)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Test failed: {e}")
        sys.exit(1)
