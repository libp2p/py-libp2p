from abc import ABC

class Stream(ABC):

	def __init__(self, context, peer_id):
		self.context = context
		self.peer_id = peer_id

	@abstractmethod
	def protocol():
		"""
		:return: protocol id that stream runs on
		"""
		pass

	@abstractmethod
	def set_protocol(protocol_id):
		"""
		:param protocol_id: protocol id that stream runs on
		:return: true if successful
		"""
		pass

	@abstractmethod
	def read():
		"""
		read from stream
		:return: bytes of input
		"""
		pass

	@abstractmethod
	def write(bytes):
		"""
		write to stream
		:return: number of bytes written
		"""
		pass

	@abstractmethod
	def close():
		"""
		close stream
		:return: true if successful
		"""
		pass

