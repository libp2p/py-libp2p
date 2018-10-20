from abc import ABC, abstractmethod

class IPeerMetadata(ABC):

	def __init__(self, context):
        self.context = context

	@abstractmethod
	def get(self, peerID, key):
		"""
		:param peerID: peer ID to lookup key for
		:param key: key to look up
        :return: value at key for given peer, error
        """
		pass

	@abstractmethod
	def put(self, peerID, key, val):
		"""
		:param peerID: peer ID to lookup key for
		:param key: key to associate with peer
		:param val: value to associated with key
        :return: error
        """
		pass