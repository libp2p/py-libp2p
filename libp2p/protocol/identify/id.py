from binascii import unhexlify

from libp2p.host.host_interface import (
    IHost,
)

from libp2p.stream_muxer.mplex.utils import (
    encode_uvarint,
)

from libp2p.network.stream.net_stream_interface import (
    INetStream,
)

from .pb import (
    crypto_pb2,
    identify_pb2,
)


PROTOCOL_ID = "/ipfs/id/1.0.0"


class IdentifyService:

    host: IHost

    def __init__(self, host: IHost) -> None:
        self.host = host

    async def request_handler(self, stream: INetStream) -> None:
        protocols = tuple(self.host.get_network().multiselect.handlers.keys())
        observed_addr = unhexlify(stream.mplex_conn.secured_conn.get_conn().remote_addr.to_bytes())
        self_maddrs = tuple(
            unhexlify(maddr.to_bytes())
            for maddr in self.host.get_addrs()
        )
        # FIXME: should get it from KeyBook, but it doesn't exist for now.
        pubkey = self.host.privkey.publickey()
        pubkey_bytes = pubkey.exportKey("DER")
        pubkey_pb = crypto_pb2.PublicKey(
            Data=pubkey_bytes,
            Type=crypto_pb2.RSA,
        )
        print(f"!@# IdentifyService.request_handler: protocols={protocols}")
        print(f"!@# IdentifyService.request_handler: observed_addr={observed_addr}")
        print(f"!@# IdentifyService.request_handler: self_maddrs={self_maddrs}")
        print(f"!@# IdentifyService.request_handler: pubkey={pubkey_bytes}")
        d = identify_pb2.Identify(
            protocolVersion="ipfs/0.1.0",
            agentVersion="py-libp2p/0.0.1",
            publicKey=pubkey_pb.SerializeToString(),
            listenAddrs=self_maddrs,
            observedAddr=observed_addr,
            protocols=protocols,
        )
        msg_bytes = d.SerializeToString()
        len_varint = encode_uvarint(len(msg_bytes))

        await stream.write(len_varint + msg_bytes)
