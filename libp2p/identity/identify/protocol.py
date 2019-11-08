import logging

from multiaddr import Multiaddr

from libp2p.host.host_interface import IHost
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.typing import StreamHandlerFn, TProtocol

from .pb.identify_pb2 import Identify

ID = TProtocol("/ipfs/id/1.0.0")
PROTOCOL_VERSION = "ipfs/0.1.0"
# TODO dynamically generate the agent version
AGENT_VERSION = "py-libp2p/alpha"
logger = logging.getLogger("libp2p.identity.identify")


def _multiaddr_to_bytes(maddr: Multiaddr) -> bytes:
    return maddr.to_bytes()


def _mk_identify_protobuf(host: IHost) -> Identify:
    public_key = host.get_public_key()
    laddrs = host.get_addrs()
    protocols = host.get_mux().get_protocols()

    return Identify(
        protocol_version=PROTOCOL_VERSION,
        agent_version=AGENT_VERSION,
        public_key=public_key.serialize(),
        listen_addrs=map(_multiaddr_to_bytes, laddrs),
        # TODO send observed address from ``stream``
        observed_addr=b"",
        protocols=protocols,
    )


def identify_handler_for(host: IHost) -> StreamHandlerFn:
    async def handle_identify(stream: INetStream) -> None:
        peer_id = stream.muxed_conn.peer_id
        logger.debug("received a request for %s from %s", ID, peer_id)

        protobuf = _mk_identify_protobuf(host)
        response = protobuf.SerializeToString()

        await stream.write(response)
        await stream.close()
        logger.debug("successfully handled request for %s from %s", ID, peer_id)

    return handle_identify
