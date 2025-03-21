.PHONY: build clean

# Build the interop test container
build:
	docker build -t py-libp2p-interop .
	docker inspect py-libp2p-interop --format='{{.Id}}' > image.json

# Clean built artifacts
clean:
	rm -f image.json
