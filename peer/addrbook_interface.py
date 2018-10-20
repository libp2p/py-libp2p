from abc import ABC, abstractmethod

class IAddrBook(ABC):

	def __init__(self, context):
        self.context = context

	@abstractmethod
	def add_addr(self, peerID, addr, ttl):
		"""
		Calls add_addrs(peerID, [addr], ttl)
		:param peerID: the peer to add address for
		:param addr: multiaddress of the peer
		:param ttl: time-to-live for the address (after this time, address is no longer valid)
		"""
		pass

	@abstractmethod
	def add_addrs(self, peerID, addrs []ma.Multiaddr, ttl time.Duration):
		"""
		Adds addresses for a given peer all with the same time-to-live. If one of the 
		addresses already exists for the peer and has a longer TTL, no operation should take place.
		If one of the addresses exists with a shorter TTL, extend the TTL to equal param ttl.
		:param peerID: the peer to add address for
		:param addr: multiaddresses of the peer
		:param ttl: time-to-live for the address (after this time, address is no longer valid
		"""
		pass

	@abstractmethod
	def addrs(self, peerID):
		"""
		:param peerID: peer to get addresses of
		:return: all known (and valid) addresses for the given peer
		"""
		pass

	@abstractmethod
	def clear_addrs(self, peerID):
		"""
		Removes all previously stored addresses
		:param peerID: peer to remove addresses of
		"""
		pass

	@abstractmethod
	def peers_with_addrs(self):
		"""
		:return: all of the peer IDs stored with addresses
        """
		pass