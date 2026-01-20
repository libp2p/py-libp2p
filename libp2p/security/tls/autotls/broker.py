import base64
import json
import logging
import os
import re
import time
from typing import cast

import dns.rdtypes.ANY.TXT
import dns.rdtypes.IN.A
import dns.resolver
import multiaddr
import requests
import trio

from libp2p.crypto.keys import KeyType, PrivateKey, PublicKey
from libp2p.peer.id import ID

logger = logging.getLogger("libp2p.autotls.broker")
resolver = dns.resolver.Resolver(configure=False)
resolver.nameservers = ["1.1.1.1", "8.8.8.8"]
resolver.timeout = 2.0
resolver.lifetime = 4.0

BROKER_URL = "https://registration.libp2p.direct/v1/_acme-challenge"
PEER_ID_AUTH_SCHEME = "libp2p-PeerID="


class BrokerClient:
    libp2p_privkey: PrivateKey
    public_maddr: multiaddr.Multiaddr
    public_ip: str
    b36_peer_id: str

    state: str
    key_auth: str
    broker_peerid: ID

    def __init__(
        self,
        libp2p_privkey: PrivateKey,
        pub_addr: multiaddr.Multiaddr,
        key_auth: str,
        b36_peerid: str,
    ):
        self.libp2p_privkey = libp2p_privkey
        self.public_maddr = pub_addr
        self.key_auth = key_auth
        self.b36_peer_id = b36_peerid
        self.public_ip = self.public_maddr.value_for_protocol("ip4")

    async def http_peerid_auth(self):
        header = {"Authorization": self.get_challenge_header()}

        resp = await trio.to_thread.run_sync(
            lambda: requests.options(BROKER_URL, headers=header)
        )
        www = resp.headers.get("Www-Authenticate")
        if not www:
            raise Exception("Missing WWW-Authenticate")

        # Verify server and respond
        body = {"value": self.key_auth, "addresses": [str(self.public_maddr)]}
        header = {
            "User-Agent": "py-libp2p/autotls",
            "Authorization": "libp2p-PeerID " + self.verify_server(www),
        }

        # Run in the thread pool to avoid blocking event
        resp = await trio.to_thread.run_sync(
            lambda: requests.post(BROKER_URL, headers=header, data=json.dumps(body))
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Broker returned error: {resp.status_code} - {resp.text}"
            )

    async def wait_for_dns(self, timeout: float = 100.0, delay: float = 2.0):
        # TODO: better logs
        peer = self.b36_peer_id
        txt_name = f"_acme-challenge.{peer}.libp2p.direct"
        a_name = f"{self.public_ip.replace('.', '-')}.{peer}.libp2p.direct"

        def resolve_txt_blocking(name: str) -> list[str]:
            try:
                answers = resolver.resolve(name, "TXT")
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
                return []

            out: list[str] = []
            for rdata in answers:
                txt = cast(dns.rdtypes.ANY.TXT.TXT, rdata)
                for s in txt.strings:
                    out.append(s.decode())
            return out

        def resolve_a_blocking(name: str) -> list[str]:
            try:
                answers = resolver.resolve(name, "A")
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
                return []

            addrs: list[str] = []
            for rdata in answers:
                a = cast(dns.rdtypes.IN.A.A, rdata)
                addrs.append(a.address)
            return addrs

        start = time.monotonic()
        while True:
            txt = await trio.to_thread.run_sync(resolve_txt_blocking, txt_name)
            a = await trio.to_thread.run_sync(resolve_a_blocking, a_name)

            if txt and a:
                logger.info("[DNS] challenge, completed by AUTO-TLS broker")
                return

            if time.monotonic() - start > timeout:
                raise TimeoutError(
                    f"DNS propagation timed out: txt={bool(txt)}, a={bool(a)}"
                )

            logger.info("[DNS] challenge completion awaiting...")
            await trio.sleep(delay)
            delay = min(delay * 1.5, 10.0)

    def verify_server(self, header: str) -> str:
        if self.state != "challenge-server":
            raise Exception("Handshake order wrong")

        msg = self.decode_auth_header(header)
        server_pk_b64 = msg["public-key"]
        challenge_client = msg["challenge-client"]

        # TODO: need to also verify the signature sent by the server
        # sig_b64 = msg["sig"]  # Will be used for signature verification

        server_pk_pb = base64.urlsafe_b64decode(server_pk_b64)
        server_pk = self.pubkey_from_protobuf_bytes(server_pk_pb)
        self.broker_peerid = ID.from_pubkey(server_pk)

        response_payload = self.make_signature_payld(
            [
                ("challenge-client=", challenge_client),
                ("#hostname=", "registration.libp2p.direct6"),
                ("server-public-key=", server_pk_pb),
            ]
        )
        client_sig = self.libp2p_privkey.sign(response_payload)
        client_sig_b64 = base64.urlsafe_b64encode(client_sig).decode()
        self.state = "respond-to-server"

        return self.encode_auth_params(
            {
                "opaque": msg["opaque"],
                "sig": client_sig_b64,
            }
        )

    def decode_auth_header(self, header: str) -> dict:
        # strip scheme prefix
        if header.startswith("libp2p-PeerID "):
            header = header[len("libp2p-PeerID ") :]

        # match key="value" patterns safely
        pattern = r'(\w[\w-]*)="([^"]*)"'
        matches = re.findall(pattern, header)

        return {k: v for k, v in matches}

    def get_challenge_header(self) -> str:
        self.state = "challenge-server"

        pubkey_protobuf = self.libp2p_privkey.get_public_key().serialize()
        pubkey_b64 = base64.urlsafe_b64encode(pubkey_protobuf).decode()

        params = self.encode_auth_params(
            {"challenge-server": os.urandom(32).hex(), "public-key": pubkey_b64}
        )

        return f"libp2p-PeerID {params}"

    def encode_auth_params(self, params: dict) -> str:
        # JS does "key=value" pairs, comma-separated
        parts = []
        for k, v in params.items():
            parts.append(f'{k}="{v}"')
        return ", ".join(parts)

    def pubkey_from_protobuf_bytes(self, pk_bytes: bytes) -> PublicKey:
        # TODO: Restructure this
        pb = PublicKey.deserialize_from_protobuf(pk_bytes)

        # Now construct a proper PublicKey instance:
        key_type = KeyType(pb.key_type)

        if key_type == KeyType.Ed25519:
            from libp2p.crypto.ed25519 import Ed25519PublicKey

            return Ed25519PublicKey.from_bytes(pb.data)
        else:
            raise ValueError("Unsupported key type yet")

    def make_signature_payld(self, fields: list[tuple[str, bytes | str]]) -> bytes:
        out = bytearray()
        out.extend(PEER_ID_AUTH_SCHEME.encode())
        for k, v in fields:
            out.extend(k.encode())
            if isinstance(v, str):
                out.extend(v.encode())
            else:
                out.extend(v)
        return bytes(out)
