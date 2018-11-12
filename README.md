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
# Architecture

## User Story
Person A wants to send messages back and forth with person B. Each person must run their own libp2p node, which implies running a host for each person.

## Openning a Connection

Host A now wants to open a stream to B in order to send messages to B along that stream. A must first open a stream to B. 

A opens a stream as follows: A chooses a protocol P for the stream and creates a raw connection RC to B by dialing B (if a connection to B does not yet exist). Host B responds and then host A and host B perform a security handshake. Then, we enter the negotation phase:

### Negotiation Phase

The negotiation phase consists of host A and host B agreeing on both the multistream module and multiplexer to use.

#### Multistream Negotiation
Host A suggests a multistream module to use by sending a message to host B that contains the following (example): '/multistream/1.0.0'. Host B responds with either (1) the same message, indicating agreement (2) a NO message, indicating that Host A should propose a different multistream module. The multistream negotiations only end once the two hosts agree on the same multistream. 

#### Multiplexer Negotiation
After agreeing on the same multistream module, the two hosts perform the multiplexer negotiation. Host A suggests a multiplexer module to use by sending a message to host B that contains the following (example): '/mplex/1.0.0'. Host B responds with either (1) the same message, indicating agreement (2) a NO message, indicating that Host A should propose a different multiplexer module. The multiplexer negotiations only end once the two hosts agree on the same multistream. After PoC, we can discuss adding in features such as sending an 'ls' message from host A to host B, which would return a response from B with all supported multistream or multiplexer modules, respectively.

#### PoC
Skip negotiation phase, assume both multiplexer and multistream will use the same modules.

### Post-Negotiation Phase

#### Host A 

#### Upgrade Connection 
For host A, negotiation phase ends when host A has received the second agreement message from host B. For host B, negotiation phase ends when host B sends the second agreement to host A. At this time, on each given host where the negotiation phase has ended, the host "upgrades" (i.e. wrap) the raw connection RC to a muxed connection object (smux.conn) MC. A muxed connection object is simply a wrapper around a raw connection RC. 

#### Open Stream 
At this point, host A will open a stream (using the openStream function) with parameter stream id ID. This is done by creating a new stream S with id ID using raw connection RC, which allows for reading and writing. After creating stream S, stream id ID is mapped to stream S in the multiplexer module MMA and stream S is returned all the way back to host A. Then, using host A's multistream module MSA, an initial message IM is sent along stream S to host B containing the stream id ID and protocol P. At this point, Host B still needs to respond to host A with an agreeing message in order for the stream to be usable by both parties (<<Can the stream be used before this point, although host B would not process the messages? Asking because the code seemed to specify the stream S is returned by openStream before multiStream selection ends>>). MSA will handle host B's response, and if host B agrees with host A on  protocol P and stream id ID, the multistream module's procedure ends and we can now read/write to S from host A.

#### Host B

#### Set StreamHandler
For a host B to receive messages from another host A: B must set a stream handler H for protocol P. Stream handler H is a function that takes as input a stream. So, B receives a dial message from A to open a stream and this is handled by listener L (which listens for incoming connections), and a new raw connection is created. At this time, the negotiation phase will go through its entire negotation procedure. After the negotiation phase ends, the raw connection RC will be upgraded to a muxed connection MC. Then, host B will use its multistream module MSB to wait for a message from host A specifying the protocol P for the stream and the stream id ID. When B's multistream module MSB receives this message from A with protocol P and stream id ID, MSB will choose to accept the stream. If host B chooses to accept the stream, then host B's multiplexer module MMB will map stream id ID to stream S. Next, MSB will send a response to host A and that message will contain the same protocol P, indicating host B's agreement with host A. At this time, host B will call the stream handler associated with protocol P by looking up the handler H in Listener L. Listener L stores a mapping of protocols to stream handlers, so L has a KV pair for P -> H. When listener L sees a stream S opened for protocol P, L will call H and pass in S as an argument. At this point, the stream S can be referenced by handler H, which was set on host B, and so B can read/write messages along stream S.

### Potential Future Changes

Right now, the negotiation phase is done following the request-response paradigm, which is subject to timeouts. An alternative approach is to use a stateful message paradigm, i.e. where a host A sends a message to host B, host B processes the messages, and then host B sends a default "ok" response. Host B then sends a message to host A, host A processes the message, and then host A sends a default "ok" response. In this case, we are not subject to timeouts, but we are subject to storing state. The pros and cons here need to be evaluated.

## Listener accepting Connection

An upgraded listener UL holds a raw listener (using the built-in server object) that is used to accept incoming connections. When UL on host B accepts an incoming connection RC from host A, UL will "upgrade" connection RC in a muxed connection object (smux.conn) MC. Then, for all time after, any time the host B receives a message sent to this muxed connection MC, the multiplexer for this connection M will be responsible for relaying the message to the appropriate stream, based of the stream id specified in the message header.

## Testing

After installing our requirements (see above), you can:
```sh
cd tests
pytest
```
