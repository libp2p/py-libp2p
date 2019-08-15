FILES_TO_LINT = libp2p tests examples setup.py

format:
	black $(FILES_TO_LINT)
	isort --recursive $(FILES_TO_LINT)

lintroll:
	mypy -p libp2p -p examples --config-file mypy.ini
	black --check $(FILES_TO_LINT)
	isort --recursive --check-only $(FILES_TO_LINT)
	flake8 $(FILES_TO_LINT)

protobufs:
	cd libp2p/crypto/pb && protoc --python_out=. --mypy_out=. crypto.proto
	cd libp2p/pubsub/pb && protoc --python_out=. --mypy_out=. rpc.proto
