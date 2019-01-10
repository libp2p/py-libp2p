# PeerStore

The PeerStore contains a mapping of peer IDs to PeerData objects. Each PeerData object represents a peer, and each PeerData contains a collection of protocols, addresses, and a mapping of metadata. PeerStore implements the IPeerStore (peer protocols), IAddrBook (address book), and IPeerMetadata (peer metadata) interfaces, which allows the peer store to effectively function as a dictionary for peer ID to protocol, address, and metadata. 

Note: PeerInfo represents a read-only summary of a PeerData object. Only the attributes assigned in PeerInfo are readable by references to PeerInfo objects.