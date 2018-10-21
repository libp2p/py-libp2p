from .peerdata_interface import IPeerData

class PeerData(IPeerData):

    def __init__(self):
        self.metadata = {}
        self.protocols = []
        self.addrs = []

    def get_protocols(self):
        return self.protocols

    def add_protocols(self, protocols):
        self.protocols.extend(protocols)

    def add_addrs(self, addrs):
        self.addrs.extend(addrs)

    def get_addrs(self):
        return self.addrs

    def clear_addrs(self):
        self.addrs = []

    def put_metadata(self, key, val):
        self.metadata[key] = val

    def get_metadata(self, key):
        if key in self.metadata:
            return self.metadata[key], None
        return None, "key not found"
