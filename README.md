# py-libp2p

<h1 align="center">
  <a href="https://libp2p.io/"><img width="250" src="https://github.com/libp2p/py-libp2p/blob/main/assets/py-libp2p-logo.png?raw=true" alt="py-libp2p hex logo" /></a>
</h1>

<h3 align="center">The Python implementation of the libp2p networking stack.</h3>

[![Join the chat at https://gitter.im/py-libp2p/Lobby](https://badges.gitter.im/py-libp2p/Lobby.png)](https://gitter.im/py-libp2p/Lobby)
[![Build Status](https://circleci.com/gh/libp2p/py-libp2p.svg?style=shield)](https://circleci.com/gh/libp2p/py-libp2p)
[![PyPI version](https://badge.fury.io/py/libp2p.svg)](https://badge.fury.io/py/libp2p)
[![Python versions](https://img.shields.io/pypi/pyversions/libp2p.svg)](https://pypi.python.org/pypi/libp2p)
[![Docs build](https://readthedocs.org/projects/py-libp2p/badge/?version=latest)](http://py-libp2p.readthedocs.io/en/latest/?badge=latest)
[![Freenode](https://img.shields.io/badge/freenode-%23libp2p-yellow.svg)](https://webchat.freenode.net/?channels=%23libp2p)
[![Matrix](https://img.shields.io/badge/matrix-%23libp2p%3Apermaweb.io-blue.svg)](https://riot.permaweb.io/#/room/#libp2p:permaweb.io)
[![Discord](https://img.shields.io/discord/475789330380488707?color=blueviolet&label=discord)](https://discord.gg/66KBrm2)

> ⚠️ **Warning:** py-libp2p is an experimental and work-in-progress repo under development. We do not yet recommend using py-libp2p in production environments.

Read more in the [documentation on ReadTheDocs](https://py-libp2p.readthedocs.io/). [View the release notes](https://py-libp2p.readthedocs.io/en/latest/release_notes.html).

## Maintainers

Currently maintained by [@pacrob](https://github.com/pacrob) and [@dhuseby](https://github.com/dhuseby), looking for assistance!

## Feature Breakdown

py-libp2p aims for conformity with [the standard libp2p modules](https://libp2p.io/implementations/). Below is a breakdown of the modules we have developed, are developing, and may develop in the future.

> Legend: :green_apple: Done   :lemon: In Progress   :tomato: Missing   :chestnut: Not planned

| libp2p Node  |    Status     |
| ------------ | :-----------: |
| **`libp2p`** | :green_apple: |

| Core Protocols |    Status     |
| -------------- | :-----------: |
| **`Ping`**     | :green_apple: |
| **`Identify`** | :green_apple: |

| Transport Protocols |    Status     |
| ------------------- | :-----------: |
| **`TCP`**           | :green_apple: |
| **`QUIC`**          |    :lemon:    |
| **`UDP`**           |   :tomato:    |
| **`WebSockets`**    |  :chestnut:   |
| **`UTP`**           |  :chestnut:   |
| **`WebRTC`**        |  :chestnut:   |
| **`SCTP`**          |  :chestnut:   |
| **`Tor`**           |  :chestnut:   |
| **`i2p`**           |  :chestnut:   |
| **`cjdns`**         |  :chestnut:   |
| **`Bluetooth LE`**  |  :chestnut:   |
| **`Audio TP`**      |  :chestnut:   |
| **`Zerotier`**      |  :chestnut:   |

| Stream Muxers    |    Status     |
| ---------------- | :-----------: |
| **`multiplex`**  | :green_apple: |
| **`yamux`**      |   :tomato:    |
| **`benchmarks`** |  :chestnut:   |
| **`muxado`**     |  :chestnut:   |
| **`spdystream`** |  :chestnut:   |
| **`spdy`**       |  :chestnut:   |
| **`http2`**      |  :chestnut:   |
| **`QUIC`**       |  :chestnut:   |

| Protocol Muxers   |    Status     |
| ----------------- | :-----------: |
| **`multiselect`** | :green_apple: |

| Switch (Swarm)     |    Status     |
| ------------------ | :-----------: |
| **`Switch`**       | :green_apple: |
| **`Dialer stack`** | :green_apple: |

| Peer Discovery       |   Status   |
| -------------------- | :--------: |
| **`bootstrap list`** |  :tomato:  |
| **`Kademlia DHT`**   | :chestnut: |
| **`mDNS`**           | :chestnut: |
| **`PEX`**            | :chestnut: |
| **`DNS`**            | :chestnut: |

| Content Routing    |    Status     |
| ------------------ | :-----------: |
| **`Kademlia DHT`** |  :chestnut:   |
| **`floodsub`**     | :green_apple: |
| **`gossipsub`**    | :green_apple: |
| **`PHT`**          |  :chestnut:   |

| Peer Routing       |    Status     |
| ------------------ | :-----------: |
| **`Kademlia DHT`** |  :chestnut:   |
| **`floodsub`**     | :green_apple: |
| **`gossipsub`**    | :green_apple: |
| **`PHT`**          |  :chestnut:   |

| NAT Traversal            |   Status   |
| ------------------------ | :--------: |
| **`nat-pmp`**            | :chestnut: |
| **`upnp`**               | :chestnut: |
| **`ext addr discovery`** | :chestnut: |
| **`STUN-like`**          | :chestnut: |
| **`line-switch relay`**  | :chestnut: |
| **`pkt-switch relay`**   | :chestnut: |

| Exchange         |   Status   |
| ---------------- | :--------: |
| **`HTTP`**       | :chestnut: |
| **`Bitswap`**    | :chestnut: |
| **`Bittorrent`** | :chestnut: |

| Consensus      |   Status   |
| -------------- | :--------: |
| **`Paxos`**    | :chestnut: |
| **`Raft`**     | :chestnut: |
| **`PBTF`**     | :chestnut: |
| **`Nakamoto`** | :chestnut: |

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

**Initiate the connection**: A host is simply a node in the libp2p network that is able to communicate with other nodes in the network. In order for X and Y to communicate with one another, one of the hosts must initiate the connection.  Let's say that X is going to initiate the connection. X will first open a connection to Y. This connection is where all of the actual communication will take place.

**Communication over one connection with multiple protocols**: X and Y can communicate over the same connection using different protocols and the multiplexer will appropriately route messages for a given protocol to a particular handler function for that protocol, which allows for each host to handle different protocols with separate functions. Furthermore, we can use multiple streams for a given protocol that allow for the same protocol and same underlying connection to be used for communication about separate topics between nodes X and Y.

**Why use multiple streams?**: The purpose of using the same connection for multiple streams to communicate over is to avoid the overhead of having multiple connections between X and Y. In order for X and Y to differentiate between messages on different streams and different protocols, a multiplexer is used to encode the messages when a message will be sent and decode a message when a message is received. The multiplexer encodes the message by adding a header to the beginning of any message to be sent that contains the stream id (along with some other info). Then, the message is sent across the raw connection and the receiving host will use its multiplexer to decode the message, i.e. determine which stream id the message should be routed to.
