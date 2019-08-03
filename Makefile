FILES_TO_LINT = libp2p tests examples setup.py

format:
	black $(FILES_TO_LINT)
	isort --recursive $(FILES_TO_LINT)

lintroll:
	# NOTE: disabling `mypy` until we get typing sorted in this repo
	# mypy -p libp2p -p examples --config-file {toxinidir}/mypy.ini
	# TODO: add flake8
	black --check $(FILES_TO_LINT)
	isort --recursive --check-only $(FILES_TO_LINT)
	flake8 $(FILES_TO_LINT)

protobufs:
	cd libp2p/pubsub/pb && protoc --python_out=. rpc.proto
	cd libp2p/pubsub/pb && python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. rpc.proto
