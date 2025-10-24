# UPnP Example

This example demonstrates how to use the integrated UPnP behaviour to automatically create a port mapping on your local network's gateway (e.g., your home router).

This allows peers from the public internet to directly dial your node, which is a crucial step for NAT traversal.

## Usage

First, ensure you have installed the necessary dependencies from the root of the repository:

```sh
pip install -e .
```

Then, run the script in a terminal:

```sh
python examples/upnp/upnp_demo.py
```

The script will start a libp2p host and immediately try to discover a UPnP-enabled gateway on the network.

- If it **succeeds**, it will print the new external address that has been mapped.
- If it **fails** (e.g., your router doesn't have UPnP enabled or you're behind a double NAT), it will print a descriptive error message.
