# py-libp2p [![Build Status](https://travis-ci.com/zixuanzh/py-libp2p.svg?branch=master)](https://travis-ci.com/zixuanzh/py-libp2p) [![codecov](https://codecov.io/gh/zixuanzh/py-libp2p/branch/master/graph/badge.svg)](https://codecov.io/gh/zixuanzh/py-libp2p) [![Gitter chat](https://badges.gitter.im/gitterHQ/gitter.png)](https://gitter.im/py-libp2p/Lobby)



<h1 align="center">
  <img width="250" align="center" src="https://github.com/zixuanzh/py-libp2p/blob/master/assets/py-libp2p-logo.png?raw=true" alt="py-libp2p hex logo" />
</h1>

## WARNING
py-libp2p is an experimental and work-in-progress repo under heavy development. We do not yet recommend using py-libp2p in production environments.

## Development

py-libp2p requires Python 3.6 and the best way to guarantee a clean Python 3.6 environment is with [`virtualenv`](https://virtualenv.pypa.io/en/stable/)

```sh
virtualenv -p python3.6 venv
. venv/bin/activate
pip3 install -r requirements.txt
```

## Testing

After installing our requirements (see above), you can:
```sh
cd tests
pytest
```
Note that tests/libp2p/test_libp2p.py contains an end-to-end messaging test between two libp2p hosts, which is the bulk of our proof of concept.

# Explanation of Basic Two Node Communication

## Core Concepts

_(non-normative, useful for team notes, not a reference)_

Several components of the libp2p stack take part when establishing a connection between two nodes:

1. **Host**: a node in the libp2p network.
2. **Connection**: the layer 3 connection between two nodes in a libp2p network.
3. **Transport**: the component that creates a _Connection_, e.g. TCP, UDP, QUIC, etc.
3. **Streams**: an abstraction on top of a _Connection_ representing parallel conversations about different matters, each of which is identified by a protocol ID. Multiple streams are layered on top of a _Connection_ via the _Multiplexer_.
4. **Multiplexer**: a component that is responsible for wrapping messages sent on a stream with an envelope that identifies the stream they pertain to, normally via an ID. The multiplexer on the other unwraps the message and routes it internally based on the stream identification.
5. **Secure channel**: optionally establishes a secure, encrypted, and authenticated channel over the _Connection_.
5. **Upgrader**: a component that takes a raw layer 3 connection returned by the _Transport_, and performs the security and multiplexing negotiation to set up a secure, multiplexed channel on top of which _Streams_ can be opened.

## Communication between two hosts X and Y

_(non-normative, useful for team notes, not a reference)_

**Initiate the connection**: A host is simply a node in the libp2p network that is able to communicate with other nodes in the network. In order for X and Y to communicate with one another, one of the hosts must initiate the connection.  Let's say that X is going to initiate the connection. X will first open a connection to Y. This connection is where all of the actual communication will take place. 

**Communication over one connection with multiple protocols**: X and Y can communicate over the same connection using different protocols and the multiplexer will appropriately route messages for a given protocol to a particular handler function for that protocol, which allows for each host to handle different protocols with separate functions. Furthermore, we can use multiple streams for a given protocol that allow for the same protocol and same underlying connection to be used for communication about separate topics between nodes X and Y. 

**Why use multiple streams?**: The purpose of using the same connection for multiple streams to communicate over is to avoid the overhead of having multiple connections between X and Y. In order for X and Y to differentiate between messages on different streams and different protocols, a multiplexer is used to encode the messages when a message will be sent and decode a message when a message is received. The multiplexer encodes the message by adding a header to the beginning of any message to be sent that contains the stream id (along with some other info). Then, the message is sent across the raw connection and the receiving host will use its multiplexer to decode the message, i.e. determine which stream id the message should be routed to.
