import trio
import os
import random
from libp2p.kad_dht.routing_table import RoutingTable
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
import multiaddr
import hashlib

class MockStream:
    async def write(self, data):
        pass
    async def read(self, n):
        # Return 0 length to simulate clean EOF or fail?
        # Actually to make _ping_peer succeed we need a proper protobuf response
        from libp2p.kad_dht.pb.kademlia_pb2 import Message
        msg = Message()
        msg.type = Message.PING
        msg_bytes = msg.SerializeToString()
        
        if n == 4:
            return len(msg_bytes).to_bytes(4, "big")
        return msg_bytes
        
    async def close(self):
        pass

# A mock Host to pass to the routing table
class MockPeerStore:
    def addrs(self, peer_id):
        return [multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/1234")]

class MockHost:
    def get_peerstore(self):
        return MockPeerStore()
    
    async def new_stream(self, *args, **kwargs):
        return MockStream()

def generate_random_peer_id():
    import multihash
    digest = hashlib.sha256(os.urandom(32)).digest()
    mh = multihash.encode(digest, "sha2-256")
    return ID(mh)

async def main():
    local_id = generate_random_peer_id()
    host = MockHost()
    rt = RoutingTable(local_id, host)
    
    added_count = 0
    for i in range(1000):
        peer_id = generate_random_peer_id()
        peer_info = PeerInfo(peer_id, [])
        success = await rt.add_peer(peer_info)
        if success:
            added_count += 1
            
    print(f"Total peers added successfully: {added_count}")
    print(f"Total buckets: {len(rt.buckets)}")
    
    total_peers = sum(b.size() for b in rt.buckets)
    print(f"Total peers in all buckets: {total_peers}")

if __name__ == "__main__":
    trio.run(main)
