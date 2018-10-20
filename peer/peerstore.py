from .peerstore_interface import IPeerStore
import asyncio

class PeerStore(IPeerStore):

    def __init__(self, context):
        self.context = context
        self.peerMap = {}

	def peer_info(self, peerID):
		if peerID in self.peerMap:
			peer = self.peerMap[peerID]
			return {
				"peerID": peerID,
				"addrs": peer.get_addrs()
			}
		else:
			return None

	def get_protocols(self, peerID):
		if peerID in self.peerMap:
			return self.peerMap[peerId].get_protocols(), None
		else:
			return None, peerID + " not found"

	def add_protocols(self, peerID, protocols):
		peer = __create_or_get_peer(peerID)
		peer.add_protocols(protocols)

	def peers(self):
		return self.peerMap.keys()

	def get(self, peerID, key):
		if peerID in self.peerMap:
			val, error = self.peerMap[peerID].get_metadata(key)
			return val, error
		else:
			return None, peerID + " not found"

	def put(self, peerID, key, val):
		# <<?>>
		# This can output an error, not sure what the possible errors are
		peer = __create_or_get_peer(peerID)
		self.peerMap[peerID].put_metadata(key, val)

	def add_addr(self, peerID, addr, ttl):
		self.add_addrs(self, peerID, [addr])

	def add_addrs(self, peerID, addrs, ttl):
		# Ignore ttl for now
		peer = __create_or_get_peer(peerID)
		peer.add_addrs(addrs)

	def addrs(self, peerID):
		if peerID in self.peerMap:
			return self.peerMap[peerId].get_addrs(), None
		else:
			return None, peerID + " not found"
		pass

	def clear_addrs(self, peerID):
		# Only clear addresses if the peer is in peer map
		if peerID in self.peerMap:
			self.peerMap[peerID].clear_addrs()

	def peers_with_addrs(self):
		# Add all peers with addrs at least 1 to output
		output = []

		for key in self.peerMap:
			if len(self.peerMap[key].get_addrs()) >= 1:
				output.append(key)
		return output

	def __create_or_get_peer(self, peerID):
		"""
		Returns the peer data for peerID or creates a new
		peer data (and stores it in peerMap) if peer 
		data for peerID does not yet exist
		:param peerID: peer ID
		:return: peer data
		"""
		if peerId in self.peerMap:
			return self.peerMap[peerId]
		else:
			data = PeerData(self.context)
			self.peerMap[peerId] = data
			return self.peerMap[peerId]