from libp2p.routing.interfaces import IContentRouting


class KadmeliaContentRouter(IContentRouting):

    def provide(self, cid, announce=True):
        """
        Provide adds the given cid to the content routing system. If announce is True,
        it also announces it, otherwise it is just kept in the local
        accounting of which objects are being provided.
        """
        # the DHT finds the closest peers to `key` using the `FIND_NODE` RPC
        # then sends a `ADD_PROVIDER` RPC with its own `PeerInfo` to each of these peers.

    def find_provider_iter(self, cid, count):
        """
        Search for peers who are able to provide a given key
        returns an iterator of peer.PeerInfo
        """
