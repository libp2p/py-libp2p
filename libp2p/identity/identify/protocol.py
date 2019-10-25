import logging
from typing import Sequence

from multiaddr import Multiaddr

from libp2p.crypto.keys import PublicKey
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.typing import StreamHandlerFn, TProtocol

from .pb.identify_pb2 import Identify

ID = "/ipfs/id/1.0.0"
PROTOCOL_VERSION = "ipfs/0.1.0"
# TODO dynamically generate the agent version
AGENT_VERSION = "py-libp2p/alpha"
logger = logging.getLogger("libp2p.identity.identify")


def _multiaddr_to_bytes(maddr: Multiaddr) -> bytes:
    return maddr.to_bytes()


def identify_handler_for(
    public_key: PublicKey, laddrs: Sequence[Multiaddr], protocols: Sequence[TProtocol]
) -> StreamHandlerFn:
    async def handle_identify(stream: INetStream) -> None:
        logger.debug("received a request for % from %", ID, stream.mplex_conn.peer_id)

        protobuf = Identify(
            protocol_version=PROTOCOL_VERSION,
            agent_version=AGENT_VERSION,
            public_key=public_key.serialize(),
            listen_addrs=map(_multiaddr_to_bytes, laddrs),
            # TODO send observed address from ``stream``
            observed_addr=b"",
            protocols=protocols,
        )
        response = protobuf.SerializeToString()

        await stream.write(response)
        await stream.close()
        logger.debug(
            "succesfully handled request for % from %", ID, stream.mplex_conn.peer_id
        )

    return handle_identify
