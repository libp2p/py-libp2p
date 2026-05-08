Introduction
============

What is py-libp2p?
------------------

py-libp2p is the Python implementation of the libp2p networking stack, a
modular peer-to-peer networking framework. It provides a foundation for building
decentralized applications and protocols in Python, enabling developers to
create resilient, secure, and efficient peer-to-peer networks.

The libp2p Ecosystem
--------------------

libp2p is a collection of networking protocols and specifications that form the
foundation of many decentralized systems. py-libp2p is part of this broader
ecosystem, which includes implementations in various languages:

* `js-libp2p <https://github.com/libp2p/js-libp2p>`_ - JavaScript implementation
* `go-libp2p <https://github.com/libp2p/go-libp2p>`_ - Go implementation
* `rust-libp2p <https://github.com/libp2p/rust-libp2p>`_ - Rust implementation

While each implementation has its strengths, py-libp2p offers familiar tools and
workflows for Python developers and researchers.

Why Choose py-libp2p?
---------------------

py-libp2p is particularly well-suited for:

* **Protocol Research and Development**: Python's simplicity and readability make it ideal for experimenting with new protocols and network topologies.
* **Rapid Prototyping**: Quickly build and test peer-to-peer applications with Python's extensive ecosystem.
* **Educational Purposes**: The Python implementation is often more approachable for learning libp2p concepts.
* **Integration with Python Projects**: Seamlessly integrate libp2p functionality into existing Python applications.

Current Capabilities
--------------------

py-libp2p currently supports these core libp2p features:

* **Transports**: TCP, QUIC, and WebSocket
* **Protocols**: Gossipsub, FloodSub, Identify, Identify Push, Ping, Bitswap,
  and Kademlia DHT
* **Security**: Noise, TLS, SECIO, and private network support
* **Connection Management**: Stream multiplexing with Yamux and mplex, plus
  resource management for connections and streams
* **Discovery**: Bootstrap, mDNS, random-walk, and rendezvous discovery
* **NAT traversal**: AutoNAT, Circuit Relay v2, and DCUtR support

Features in Development
-----------------------

Several areas continue to evolve, including protocol interoperability, transport
coverage, Filecoin-focused compatibility work, and production-hardening for
larger deployments.

Use Cases
---------

py-libp2p can be used to build various decentralized applications:

* Distributed file storage systems
* Decentralized social networks
* IoT device networks
* Blockchain and cryptocurrency networks
* Research and academic projects
* Private peer-to-peer messaging systems

Getting Started
---------------

Ready to start building with py-libp2p? Check out our :doc:`getting_started`
guide to begin your journey. For more detailed information about specific
features and APIs, explore our :doc:`examples` and
:doc:`API documentation <libp2p>`.

Contributing
------------

We welcome contributions from developers of all experience levels! Whether you're fixing bugs, adding features, or improving documentation, your help is valuable. See our :doc:`contributing` guide for details on how to get involved.

Further Reading
---------------

* `libp2p main site <https://libp2p.io/>`_
* `Tutorial: Introduction to libp2p <https://proto.school/introduction-to-libp2p>`_
* `libp2p Specification <https://github.com/libp2p/specs>`_
* `libp2p Documentation <https://docs.libp2p.io/>`_
