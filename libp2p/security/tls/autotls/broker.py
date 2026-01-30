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
    """
    Client for interacting with the AutoTLS broker during DNS-01 challenges.

    Handles registration of the DNS challenge with the broker and monitors
    challenge state to coordinate ACME certificate issuance.
    """

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
        """
        Initialize the broker client for a given peer.

        Stores the peer's private key, public multiaddr, DNS-01 key authorization,
        and base36-encoded Peer ID. Extracts the public IPv4 address from the
        multiaddr for broker communication.

        :param libp2p_privkey: Private key of the local libp2p peer.
        :param pub_addr: Public multiaddr of the peer.
        :param key_auth: DNS-01 challenge key authorization.
        :param b36_peerid: Base36-encoded Peer ID of the peer.
        """
        self.libp2p_privkey = libp2p_privkey
        self.public_maddr = pub_addr
        self.key_auth = key_auth
        self.b36_peer_id = b36_peerid
        self.public_ip = self.public_maddr.value_for_protocol("ip4")  # type: ignore

    async def http_peerid_auth(self) -> None:
        """
        Authenticate with the AutoTLS broker using the peer's DNS-01 challenge.

        Sends an initial OPTIONS request to retrieve the server challenge, verifies
        the broker identity, and responds with the key authorization and public
        addresses. This step establishes the peer's identity with the broker before
        DNS propagation monitoring.

        Network operations are executed in a thread pool to avoid blocking the Trio
        event loop.

        :return: None
        :raises RuntimeError: if the broker returns a non-success response.
        :raises Exception: if the broker challenge headers are missing.
        """
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

    async def wait_for_dns(self, timeout: float = 100.0, delay: float = 2.0) -> None:
        """
        Poll DNS until the ACME TXT challenge is visible.

        Repeatedly resolves the TXT record for the peer's DNS-01 challenge and waits
        for it to propagate. Also prepares the expected A record name for reference.
        Resolution is performed in a blocking function wrapped by the async context.

        :param timeout: Maximum time in seconds to wait for DNS propagation.
        :param delay: Interval in seconds between polling attempts.
        :return: None
        :raises RuntimeError: if the TXT record does not appear within the timeout.
        """
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
        """
        Verify the broker server's challenge and prepare a signed response.

        Decodes the server's authentication header, extracts the public key, and
        derives the broker Peer ID. Signs a payload including the server challenge
        and host information, returning the encoded response for broker submission.


        :param header: Authentication header received from the broker.
        :return: Base64-encoded signature payload to include in broker requests.
        :raises Exception: if the handshake is invoked in the wrong order.
        """
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

    def decode_auth_header(self, header: str) -> dict[str, str]:
        """Parse a libp2p-PeerID auth header into a dictionary of key-value pairs."""
        # strip scheme prefix
        if header.startswith("libp2p-PeerID "):
            header = header[len("libp2p-PeerID ") :]

        # match key="value" patterns safely
        pattern = r'(\w[\w-]*)="([^"]*)"'
        matches = re.findall(pattern, header)

        return {k: v for k, v in matches}

    def get_challenge_header(self) -> str:
        """Generate a new client challenge header and mark state as challenge-server"""
        self.state = "challenge-server"

        pubkey_protobuf = self.libp2p_privkey.get_public_key().serialize()
        pubkey_b64 = base64.urlsafe_b64encode(pubkey_protobuf).decode()

        params = self.encode_auth_params(
            {"challenge-server": os.urandom(32).hex(), "public-key": pubkey_b64}
        )

        return f"libp2p-PeerID {params}"

    def encode_auth_params(self, params: dict[str, str]) -> str:
        """Serialize a dictionary of key-value pairs into a libp2p-auth header."""
        # JS does "key=value" pairs, comma-separated
        parts = []
        for k, v in params.items():
            parts.append(f'{k}="{v}"')
        return ", ".join(parts)

    def pubkey_from_protobuf_bytes(self, pk_bytes: bytes) -> PublicKey:
        """Deserialize protobuf bytes into a libp2p PublicKey object."""
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
        """Construct a byte payload from key-value fields for peer-authsigning."""
        out = bytearray()
        out.extend(PEER_ID_AUTH_SCHEME.encode())
        for k, v in fields:
            out.extend(k.encode())
            if isinstance(v, str):
                out.extend(v.encode())
            else:
                out.extend(v)
        return bytes(out)
