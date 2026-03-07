# py-libp2p

<h1 align="center">
  <a href="https://libp2p.io/"><img width="250" src="https://github.com/libp2p/py-libp2p/blob/main/assets/py-libp2p-logo.png?raw=true" alt="py-libp2p hex logo" /></a>
</h1>

<h3 align="center">The Python implementation of the libp2p networking stack.</h3>

[![Discord](https://img.shields.io/discord/1204447718093750272?color=blueviolet&label=discord)](https://discord.gg/hQJnbd85N6)
[![PyPI version](https://badge.fury.io/py/libp2p.svg)](https://badge.fury.io/py/libp2p)
[![Python versions](https://img.shields.io/pypi/pyversions/libp2p.svg)](https://pypi.python.org/pypi/libp2p)
[![Build Status](https://img.shields.io/github/actions/workflow/status/libp2p/py-libp2p/tox.yml?branch=main&label=build%20status)](https://github.com/libp2p/py-libp2p/actions/workflows/tox.yml)
[![Docs build](https://readthedocs.org/projects/py-libp2p/badge/?version=latest)](http://py-libp2p.readthedocs.io/en/latest/?badge=latest)

> py-libp2p has moved beyond its experimental roots and is steadily progressing toward production readiness. The core features are stable, and we’re focused on refining performance, expanding protocol support, and ensuring smooth interop with other libp2p implementations. We welcome contributions and real-world usage feedback to help us reach full production maturity.

Read more in the [documentation on ReadTheDocs](https://py-libp2p.readthedocs.io/). [View the release notes](https://py-libp2p.readthedocs.io/en/latest/release_notes.html).

## Maintainers

Currently maintained by [@pacrob](https://github.com/pacrob), [@seetadev](https://github.com/seetadev) and [@dhuseby](https://github.com/dhuseby). Please reach out to us for collaboration or active feedback. If you have questions, feel free to open a new [discussion](https://github.com/libp2p/py-libp2p/discussions). We are also available on the libp2p Discord — join us at #py-libp2p [sub-channel](https://discord.gg/d92MEugb).

## Feature Breakdown

py-libp2p aims for conformity with [the standard libp2p modules](https://libp2p.io/implementations/). Below is a breakdown of the modules we have developed, are developing, and may develop in the future.

> Legend: ✅: Done  🛠️: In Progress/Usable  🌱 Prototype/Unstable  ❌: Missing

______________________________________________________________________

### Transports

| **Transport**                          | **Status** |                                     **Source**                                      |
| -------------------------------------- | :--------: | :---------------------------------------------------------------------------------: |
| **`libp2p-tcp`**                       |     ✅     | [source](https://github.com/libp2p/py-libp2p/blob/main/libp2p/transport/tcp/tcp.py) |
| **`libp2p-quic`**                      |     ✅     |    [source](https://github.com/libp2p/py-libp2p/tree/main/libp2p/transport/quic)    |
| **`libp2p-websocket`**                 |     ✅     | [source](https://github.com/libp2p/py-libp2p/tree/main/libp2p/transport/websocket)  |
| **`libp2p-webrtc-browser-to-server`**  |     🌱     |                                                                                     |
| **`libp2p-webrtc-private-to-private`** |     🌱     |                                                                                     |

______________________________________________________________________

### NAT Traversal

| **NAT Traversal**             | **Status** |                                   **Source**                                    |
| ----------------------------- | :--------: | :-----------------------------------------------------------------------------: |
| **`libp2p-circuit-relay-v2`** |     ✅     | [source](https://github.com/libp2p/py-libp2p/tree/main/libp2p/relay/circuit_v2) |
| **`libp2p-autonat`**          |     ✅     |   [source](https://github.com/libp2p/py-libp2p/tree/main/libp2p/host/autonat)   |
| **`libp2p-hole-punching`**    |     ✅     | [source](https://github.com/libp2p/py-libp2p/tree/main/libp2p/relay/circuit_v2) |

______________________________________________________________________

### Secure Communication

| **Secure Communication** | **Status** |                                  **Source**                                   |
| ------------------------ | :--------: | :---------------------------------------------------------------------------: |
| **`libp2p-noise`**       |     ✅     | [source](https://github.com/libp2p/py-libp2p/tree/main/libp2p/security/noise) |
| **`libp2p-tls`**         |     ✅     |                                                                               |

______________________________________________________________________

### Discovery

| **Discovery**        | **Status** |                                      **Source**                                      |
| -------------------- | :--------: | :----------------------------------------------------------------------------------: |
| **`bootstrap`**      |     ✅     |  [source](https://github.com/libp2p/py-libp2p/tree/main/libp2p/discovery/bootstrap)  |
| **`random-walk`**    |     ✅     | [source](https://github.com/libp2p/py-libp2p/tree/main/libp2p/discovery/random_walk) |
| **`mdns-discovery`** |     ✅     |    [source](https://github.com/libp2p/py-libp2p/tree/main/libp2p/discovery/mdns)     |
| **`rendezvous`**     |     ✅     | [source](https://github.com/libp2p/py-libp2p/tree/main/libp2p/discovery/rendezvous)  |

______________________________________________________________________

### Peer Routing

| **Peer Routing**     | **Status** |                               **Source**                               |
| -------------------- | :--------: | :--------------------------------------------------------------------: |
| **`libp2p-kad-dht`** |     ✅     | [source](https://github.com/libp2p/py-libp2p/tree/main/libp2p/kad_dht) |

______________________________________________________________________

### Publish/Subscribe

| **Publish/Subscribe**  | **Status** |                                     **Source**                                     |
| ---------------------- | :--------: | :--------------------------------------------------------------------------------: |
| **`libp2p-floodsub`**  |     ✅     | [source](https://github.com/libp2p/py-libp2p/blob/main/libp2p/pubsub/floodsub.py)  |
| **`libp2p-gossipsub`** |     ✅     | [source](https://github.com/libp2p/py-libp2p/blob/main/libp2p/pubsub/gossipsub.py) |

______________________________________________________________________

### Stream Muxers

| **Stream Muxers**  | **Status** |                                    **Source**                                     |
| ------------------ | :--------: | :-------------------------------------------------------------------------------: |
| **`libp2p-yamux`** |     ✅     | [source](https://github.com/libp2p/py-libp2p/tree/main/libp2p/stream_muxer/yamux) |
| **`libp2p-mplex`** |     ✅     | [source](https://github.com/libp2p/py-libp2p/tree/main/libp2p/stream_muxer/mplex) |

______________________________________________________________________

### Storage

| **Storage**         | **Status** |
| ------------------- | :--------: |
| **`libp2p-record`** |     ✅     |

______________________________________________________________________

### General Purpose Utilities & Datatypes

| **Utility/Datatype**  | **Status** |                                          **Source**                                          |
| --------------------- | :--------: | :------------------------------------------------------------------------------------------: |
| **`libp2p-ping`**     |     ✅     |         [source](https://github.com/libp2p/py-libp2p/blob/main/libp2p/host/ping.py)          |
| **`libp2p-peer`**     |     ✅     |             [source](https://github.com/libp2p/py-libp2p/tree/main/libp2p/peer)              |
| **`libp2p-identify`** |     ✅     | [source](https://github.com/libp2p/py-libp2p/blob/main/libp2p/identity/identify/identify.py) |

______________________________________________________________________

## Explanation of Basic Two Node Communication

### Core Concepts

_(non-normative, useful for team notes, not a reference)_

Several components of the libp2p stack take part when establishing a connection between two nodes:

1. **Host**: a node in the libp2p network.
1. **Connection**: the layer 3 connection between two nodes in a libp2p network.
1. **Transport**: the component that creates a _Connection_, e.g. TCP, UDP, QUIC, etc.
1. **Streams**: an abstraction on top of a _Connection_ representing parallel conversations about different matters, each of which is identified by a protocol ID. Multiple streams are layered on top of a _Connection_ via the _Multiplexer_.
1. **Multiplexer**: a component that is responsible for wrapping messages sent on a stream with an envelope that identifies the stream they pertain to, normally via an ID. The multiplexer on the other unwraps the message and routes it internally based on the stream identification.
1. **Secure channel**: optionally establishes a secure, encrypted, and authenticated channel over the _Connection_.
1. **Upgrader**: a component that takes a raw layer 3 connection returned by the _Transport_, and performs the security and multiplexing negotiation to set up a secure, multiplexed channel on top of which _Streams_ can be opened.

### Communication between two hosts X and Y

_(non-normative, useful for team notes, not a reference)_

**Initiate the connection**: A host is simply a node in the libp2p network that is able to communicate with other nodes in the network. In order for X and Y to communicate with one another, one of the hosts must initiate the connection. Let's say that X is going to initiate the connection. X will first open a connection to Y. This connection is where all of the actual communication will take place.

**Communication over one connection with multiple protocols**: X and Y can communicate over the same connection using different protocols and the multiplexer will appropriately route messages for a given protocol to a particular handler function for that protocol, which allows for each host to handle different protocols with separate functions. Furthermore, we can use multiple streams for a given protocol that allow for the same protocol and same underlying connection to be used for communication about separate topics between nodes X and Y.

**Why use multiple streams?**: The purpose of using the same connection for multiple streams to communicate over is to avoid the overhead of having multiple connections between X and Y. In order for X and Y to differentiate between messages on different streams and different protocols, a multiplexer is used to encode the messages when a message will be sent and decode a message when a message is received. The multiplexer encodes the message by adding a header to the beginning of any message to be sent that contains the stream id (along with some other info). Then, the message is sent across the raw connection and the receiving host will use its multiplexer to decode the message, i.e. determine which stream id the message should be routed to.

### Support

<a href="https://filecoin.drips.network/app/projects/github/libp2p/py-libp2p" target="_blank"><img src="https://filecoin.drips.network/api/embed/project/https%3A%2F%2Fgithub.com%2Flibp2p%2Fpy-libp2p/support.png?background=light&style=drips&text=project&stat=support" alt="Support py-libp2p on drips.network" height="32"></a>
