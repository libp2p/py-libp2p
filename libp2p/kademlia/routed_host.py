from libp2p.host.basic_host import BasicHost

class RoutedHost(BasicHost):
    def __init__(self, _network, _kad_network):
        super(RoutedHost, self).__init__(_network)
        self.kad_network = _kad_network

    def get_kad_network(self):
        return self.kad_network

    def routed_listen(self, port, interface='0.0.0.0'):
        return self.kad_network.listen(port, interface)

    def routed_get(self, key):
        return self.kad_network.get(key)

    def routed_set(self, key, value):
        return self.kad_network.set(key, value)

    def routed_set_digest(self, dkey, value):
        return self.kad_network.set_digest(dkey, value)
