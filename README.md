# py-libp2p

<h1 align="center">
  <img width="250" align="center" src="https://github.com/zixuanzh/py-libp2p/blob/master/assets/py-libp2p-logo.png?raw=true" alt="py-libp2p hex logo" />
</h1>

## Development

py-libp2p requires Python 3.6 and the best way to guarantee a clean Python 3.6 environment is with [`virtualenv`](https://virtualenv.pypa.io/en/stable/)

```sh
virtualenv -p python3.6 venv
. venv/bin/activate
pip install -r requirements.txt
```

## Testing

After installing our requirements (see above), you can:
```sh
cd tests
pytest
```

# Explanation of Basic Two Node Communication

## Core Concepts

The libp2p library is focused on four main concepts: 
(1) **Host**: a node in the libp2p network
(2) **Connection**: the connection between two nodes in a libp2p network over which all communication between those two nodes takes place
(3) **Streams**: an abstraction on top of a connection that is used to represent communication about a particular topic over a given connection. There can be many streams over a single connection.
(4) **Multiplexer**: a module that is responsible for encoding messages to be sent across a connection such that the message contains information about the sender stream so that the receiving host's multiplexer knows which stream the message should be routed to.

## Communication between two hosts X and Y
**Initiate the connection**: A host is simply a node in the libp2p network that is able to communicate with other nodes in the network. In order for X and Y to communicate with one another, one of the hosts must initiate the connection.  Let's say that X is going to initiate the connection. X will first open a connection to Y. This connection is where all of the actual communication will take place. 

**Communication over one connection with multiple protocols**: X and Y can communicate over the same connection using different protocols and the multiplexer will appropriately route messages for a given protocol to a particular handler function for that protocol, which allows for each host to handle different protocols with separate functions. Furthermore, we can use multiple streams for a given protocol that allow for the same protocol and same underlying connection to be used for communication about separate topics between nodes X and Y. 

**Why use multiple streams?**: The purpose of using the same connection for multiple streams to communicate over is to avoid the overhead of having multiple connections between X and Y. In order for X and Y to differentiate between messages on different streams and different protocols, a multiplexer is used to encode the messages when a message will be sent and decode a message when a message is received. The multiplexer encodes the message by adding a header to the beginning of any message to be sent that contains the stream id (along with some other info). Then, the message is sent across the raw connection and the receiving host will use its multiplexer to decode the message, i.e. determine which stream id the message should be routed to.
