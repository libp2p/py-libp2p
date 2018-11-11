class TransportUpgrader(object):

	def __init__(self, secOpt, muxerOpt):
		self.sec = secOpt
		self.muxer = muxerOpt

	def upgrade_listener(self, transport, listeners):
		"""
		upgrade multiaddr listeners to libp2p-transport listeners

		"""
		pass
		
	def upgrade_security(self):
		pass

	def upgrade_muxer(self):
		pass