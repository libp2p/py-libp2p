from .muxed_stream_interface import IMuxedStream

class MuxedStream(IMuxedStream):
	"""
	reference: https://github.com/libp2p/go-mplex/blob/master/stream.go
	"""
    def __init__(self, stream_id, stream_name):
        self.id = stream_id
        self.name = stream_name

    def read(self):
        pass

    def write(self):
        pass

    def close(self):
    	pass

    def reset(self):
        """
        closes both ends of the stream
        tells this remote side to hang up
        :return: error/exception
        """
        pass

    def set_deadline(self, ttl):
        """
        set deadline for muxed stream
        :return: a new stream
        """
        pass
