from libp2p.routing.interfaces import IContentRouting


class KadmeliaContentRouter(IContentRouting):

    def provide(self, cid, announce=True):
        """
        Provide adds the given cid to the content routing system. If announce is True,
        it also announces it, otherwise it is just kept in the local
        accounting of which objects are being provided.
        """
        pass

    def find_provider_iter(self, cid, count):
        """
        Search for peers who are able to provide a given key
        returns an iterator of peer.PeerInfo
        """
        pass
