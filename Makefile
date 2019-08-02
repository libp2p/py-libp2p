lintroll:
	# NOTE: disabling `mypy` until we get typing sorted in this repo
	# mypy -p libp2p -p examples --config-file {toxinidir}/mypy.ini
	black --check  examples libp2p/__init__.py libp2p/host libp2p/kademlia libp2p/network libp2p/peer libp2p/protocol_muxer libp2p/pubsub/*.py libp2p/routing libp2p/security libp2p/stream_muxer libp2p/transport tests setup.py
