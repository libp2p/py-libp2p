from abc import ABC

class Host(ABC):

	# default options constructor
	def __init__(self, context, network):
		self.context = context
		self.network = network

	@abstractmethod
	def id(self):
		"""
		:return: peer_id of host
		"""
		pass

	@abstractmethod
	def network(self):
		"""
		:return: network instance of host
		"""
		pass

	@abstractmethod
	def mux(self):
		"""
		:return: mux instance of host
		"""
		pass

	@abstractmethod
	def set_stream_handler(self, protocol_id, stream_handler):
		"""
		set stream handler for host
		:param protocol_id: protocol id used on stream
		:param stream_handler: a stream handler function
		:return: true if successful
		"""
		pass

	# protocol_id can be a list of protocol_ids
	# stream will decide which protocol_id to run on
	@abstractmethod
	def new_stream(self, context, peer_id, protocol_id):
		"""
		:param context: a context instance
		:param peer_id: peer_id that host is connecting
		:param proto_id: protocol id that stream runs on
		:return: true if successful
		"""
		pass