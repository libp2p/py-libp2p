from abc import ABC, abstractmethod
import asyncio

"""
Communicator helper class that ensures both the client
and multistream module will follow the same protocol,
which is necessary for them to work
"""
class MultiselectCommunicator(IMultiselectCommunicator):

    @abstractmethod
    async def write(msg_str):
    	"""
    	Write message to stream
    	:param msg_str: message to write
    	"""
    	pass

    @abstractmethod
    async def read_stream_until_eof():
    	"""
    	Reads message on stream until EOF
    	"""
    	pass
