from .peerstore_interface import IPeerStore
from .peerdata import PeerData

class PeerStore(IPeerStore):

    def __init__(self):
        IPeerStore.__init__(self)
        self.peer_map = {}

    def __create_or_get_peer(self, peer_id):
        """
        Returns the peer data for peer_id or creates a new
        peer data (and stores it in peer_map) if peer
        data for peer_id does not yet exist
        :param peer_id: peer ID
        :return: peer data
        """
        if peer_id in self.peer_map:
            return self.peer_map[peer_id]
        data = PeerData()
        self.peer_map[peer_id] = data
        return self.peer_map[peer_id]

    def peer_info(self, peer_id):
        if peer_id in self.peer_map:
            peer = self.peer_map[peer_id]
            return {
                "peer_id": peer_id,
                "addrs": peer.get_addrs()
            }
        return None

    def get_protocols(self, peer_id):
        if peer_id in self.peer_map:
            return self.peer_map[peer_id].get_protocols(), None
        return None, peer_id + " not found"

    def add_protocols(self, peer_id, protocols):
        peer = self.__create_or_get_peer(peer_id)
        peer.add_protocols(protocols)

    # TODO(@stuckinaboot): Implement
    def set_protocols(self, peer_id, protocols):
        pass

    def peers(self):
        return self.peer_map.keys()

    def get(self, peer_id, key):
        if peer_id in self.peer_map:
            val, error = self.peer_map[peer_id].get_metadata(key)
            return val, error
        return None, peer_id + " not found"

    def put(self, peer_id, key, val):
        # <<?>>
        # This can output an error, not sure what the possible errors are
        peer = self.__create_or_get_peer(peer_id)
        peer.put_metadata(key, val)

    def add_addr(self, peer_id, addr, ttl):
        self.add_addrs(self, peer_id, [addr])

    def add_addrs(self, peer_id, addrs, ttl):
        # Ignore ttl for now
        peer = self.__create_or_get_peer(peer_id)
        peer.add_addrs(addrs)

    def addrs(self, peer_id):
        if peer_id in self.peer_map:
            return self.peer_map[peer_id].get_addrs(), None
        return None, peer_id + " not found"

    def clear_addrs(self, peer_id):
        # Only clear addresses if the peer is in peer map
        if peer_id in self.peer_map:
            self.peer_map[peer_id].clear_addrs()

    def peers_with_addrs(self):
        # Add all peers with addrs at least 1 to output
        output = []

        for key in self.peer_map:
            if len(self.peer_map[key].get_addrs()) >= 1:
                output.append(key)
        return output
