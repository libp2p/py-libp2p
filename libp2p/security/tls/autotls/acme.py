import base64
import hashlib
import json
import logging
from typing import Any

import base58
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.x509.oid import ExtensionOID
import httpx
import multibase
import requests
import trio

import libp2p
from libp2p.crypto.keys import PrivateKey
from libp2p.peer.id import ID
import libp2p.utils
import libp2p.utils.paths

logger = logging.getLogger("libp2p.autotls.acme")
ACME_DIRECTORY_URL = "https://acme-staging-v02.api.letsencrypt.org/directory"


def generate_rsa_key(bits: int = 2048) -> RSAPrivateKey:
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=bits,
        backend=default_backend(),
    )
    return key


def compute_b36_peer_id(peerid: ID) -> str:
    mh = base58.b58decode(str(peerid))
    cid_bytes = bytes([0x01, 0x72]) + mh
    b36_peer_bytes = multibase.encode("base36", cid_bytes)

    return b36_peer_bytes.decode()


class ACMEClient:
    libp2p_privkey: PrivateKey
    local_peer: ID
    b36_peerid: str
    cert_chain: list[x509.Certificate]

    # creds (certificate and account pubkey must me different)
    directory: Any
    acct_rsa_key: RSAPrivateKey
    cert_rsa_key: RSAPrivateKey
    jwk: dict[str, str]
    jwk_thumbprint: str
    csr_b64: str

    # URLS
    account_url: str
    order_url: str
    auth_url: str
    finalize_url: str
    chall_url: str
    cert_url: str

    # ACME
    token: str
    key_auth: str

    def __init__(
        self,
        libp2p_privkey: PrivateKey,
        local_peer: ID,
    ):
        self.libp2p_privkey = libp2p_privkey
        self.local_peer = local_peer
        self.b36_peerid = compute_b36_peer_id(self.local_peer)

        self.acct_rsa_key = generate_rsa_key(2048)
        self.cert_rsa_key = generate_rsa_key(2048)

        self.jwk = self.jwk_from_rsa_privkey()
        self.jwk_thumbprint = self.compute_jwk_thumbprint()

        csr_der = self.create_rsa_csr()
        self.csr_b64 = self.b64url_encode(csr_der)

    async def create_acme_acct(self):
        # Fetch directory - run in therad pool to avoid blocking event loop
        resp = await trio.to_thread.run_sync(
            lambda: requests.get(ACME_DIRECTORY_URL, timeout=10)
        )
        resp.raise_for_status()
        self.directory = resp.json()

        # Create JWS
        nonce = await self.get_nonce()
        new_account_url = self.directory["newAccount"]

        protected = {
            "alg": "RS256",
            "typ": "JWT",
            "nonce": nonce,
            "url": new_account_url,
            "jwk": self.jwk,
        }
        payload = {"termsofServiceAgreed": True}
        jws = self.create_jws(protected, payload)

        # POST to newAccout || Fetch the account URL - run in thread pool
        headers = {"Content-Type": "application/jose+json"}
        resp = await trio.to_thread.run_sync(
            lambda: requests.post(
                self.directory["newAccount"], json=jws, headers=headers, timeout=10
            )
        )

        if not (200 <= resp.status_code < 300):
            raise RuntimeError(
                f"ACME newAccount failed: {resp.status_code}: {resp.text}"
            )

        account_url = resp.headers.get("Location")
        self.account_url = account_url

    async def initiate_order(self):
        new_order_url = self.directory["newOrder"]
        nonce = await self.get_nonce()
        domain = f"*.{self.b36_peerid}.libp2p.direct"

        protected = {
            "alg": "RS256",
            "kid": self.account_url,
            "nonce": nonce,
            "url": new_order_url,
        }
        payload = {"identifiers": [{"type": "dns", "value": domain}]}

        jws = self.create_jws(protected, payload)
        resp = await trio.to_thread.run_sync(
            lambda: requests.post(
                new_order_url,
                json=jws,
                headers={"Content-Type": "application/jose+json"},
                timeout=10,
            )
        )
        resp.raise_for_status()

        self.order_url = resp.headers["Location"]
        self.auth_url = resp.json()["authorizations"][0]
        self.finalize_url = resp.json()["finalize"]

    async def get_dns01_challenge(self):
        nonce = await self.get_nonce()
        protected = {
            "alg": "RS256",
            "kid": self.account_url,
            "nonce": nonce,
            "url": self.auth_url,
        }
        jws = self.create_jws(protected, None)

        resp = await trio.to_thread.run_sync(
            lambda: requests.post(
                self.auth_url,
                json=jws,
                headers={"Content-Type": "application/jose+json"},
                timeout=10,
            )
        )
        auth = resp.json()

        # Find and store the DNS-01 challenge
        dns01 = None
        for ch in auth.get("challenges", []):
            if ch.get("type") == "dns-01":
                dns01 = ch
                break

        if dns01 is None:
            raise RuntimeError("dns-01 challenge not found")

        self.token = dns01["token"]
        self.chall_url = dns01["url"]

        raw_key_auth = f"{self.token}.{self.jwk_thumbprint}"
        self.key_auth = self.compute_dns01_keyauth(raw_key_auth)

        logger.info("Key-Auth fetched from ACME: %s", self.key_auth)

    async def notify_dns_ready(self, delay: int = 5):
        nonce = await self.get_nonce()
        replay_nonce, _ = await self._dns_poll(nonce)

        while True:
            replay_nonce, body = await self._dns_poll(replay_nonce)
            status = body.get("status")

            if status == "valid":
                logger.info("Notified ACME, about challenge completion")
                break

            if status == "invalid":
                raise RuntimeError(f"Challenge failed: {body}")

            await trio.sleep(delay)

    async def _dns_poll(self, nonce: str):
        payload = {}
        protected = {
            "alg": "RS256",
            "kid": self.account_url,
            "nonce": nonce,
            "url": self.chall_url,
        }

        jws = self.create_jws(protected, payload)
        header = {
            "Content-Type": "application/jose+json",
            "User-Agent": "py-libp2p/autotls",
        }

        client = httpx.AsyncClient(http2=False, timeout=10.0)
        resp = await client.post(self.chall_url, headers=header, json=jws)

        replay_nonce = resp.headers.get("Replay-Nonce")
        if not replay_nonce:
            raise RuntimeError("No Replay-Nonce in ACME poll response")

        return replay_nonce, resp.json()

    async def fetch_cert_url(self):
        payload = {"csr": self.csr_b64}
        nonce = await self.get_nonce()
        protected = {
            "alg": "RS256",
            "kid": self.account_url,
            "nonce": nonce,
            "url": self.finalize_url,
        }

        jws = self.create_jws(protected, payload)
        async with httpx.AsyncClient(http2=False, timeout=10.0) as client:
            resp = await client.post(
                self.finalize_url,
                headers={"Content-Type": "application/jose+json"},
                json=jws,
            )

            # POLL ORDER
            while True:
                await trio.sleep(2)

                nonce = await self.get_nonce()
                protected = {
                    "alg": "RS256",
                    "kid": self.account_url,
                    "nonce": nonce,
                    "url": self.order_url,
                }
                jws = self.create_jws(protected, None)

                resp = await client.post(
                    self.order_url,
                    headers={"Content-Type": "application/jose+json"},
                    json=jws,
                )
                order = resp.json()

                if order["status"] == "valid":
                    self.cert_url = order["certificate"]
                    return

        raise RuntimeError("ACME order never reached valid state")

    async def fetch_certificate(self):
        nonce = await self.get_nonce()
        protected = {
            "alg": "RS256",
            "kid": self.account_url,
            "nonce": nonce,
            "url": self.cert_url,
        }

        jws = self.create_jws(protected, None)
        async with httpx.AsyncClient(http2=False, timeout=10.0) as client:
            resp = await client.post(
                self.cert_url,
                headers={"Content-Type": "application/jose+json"},
                json=jws,
            )
            pem_chain = resp.text

            # Write PEM chain to file
            libp2p.utils.paths.AUTOTLS_CERT_PATH.write_text(pem_chain)

            # Read PEM chain back from file
            pem_bytes = libp2p.utils.paths.AUTOTLS_CERT_PATH.read_bytes()
            self.cert_chain = x509.load_pem_x509_certificates(pem_bytes)

            san = (
                self.cert_chain[0]
                .extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
                .value
            )

            dns_names = san.get_values_for_type(x509.DNSName)
            logger.info(
                "ACME-TLS certificate cached, DNS: %s, b36_pid: %s",
                dns_names,
                self.b36_peerid,
            )

    def create_jws(self, protected: dict, payload: dict | None) -> dict:
        protected_b64 = self.b64url_encode(
            json.dumps(protected, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )

        if payload is None:
            # ACME POST-as-GET requires empty string payload
            payload_b64 = ""
            signing_input = f"{protected_b64}.{payload_b64}".encode("ascii")
        else:
            payload_b64 = self.b64url_encode(
                json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
                    "utf-8"
                )
            )
            signing_input = f"{protected_b64}.{payload_b64}".encode("ascii")

        signature = self.acct_rsa_key.sign(
            signing_input, padding.PKCS1v15(), hashes.SHA256()
        )
        signature_b64 = self.b64url_encode(signature)

        return {
            "protected": protected_b64,
            "payload": payload_b64,
            "signature": signature_b64,
        }

    def create_rsa_csr(self) -> bytes:
        domain = f"*.{self.b36_peerid}.libp2p.direct"

        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(x509.Name([]))  # empty subject is allowed
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName(domain),
                    ]
                ),
                critical=False,
            )
            .sign(self.cert_rsa_key, hashes.SHA256())
        )

        return csr.public_bytes(serialization.Encoding.DER)

    def jwk_from_rsa_privkey(self):
        pub = self.acct_rsa_key.public_key()
        numbers = pub.public_numbers()

        def int_to_b64u(n: int) -> str:
            length = (n.bit_length() + 7) // 8
            return self.b64url_encode(n.to_bytes(length, "big"))

        return {"kty": "RSA", "n": int_to_b64u(numbers.n), "e": int_to_b64u(numbers.e)}

    def b64url_encode(self, data: bytes) -> str:
        """Base64url encode without padding, returning str."""
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    async def get_nonce(self):
        new_nonce_url = self.directory["newNonce"]

        nonce_resp = await trio.to_thread.run_sync(
            lambda: requests.head(new_nonce_url, timeout=10)
        )

        if "Replay-Nonce" in nonce_resp.headers:
            nonce = nonce_resp.headers["Replay-Nonce"]
        else:
            nonce_resp_get = await trio.to_thread.run_sync(
                lambda: requests.get(new_nonce_url, timeout=10)
            )
            nonce = nonce_resp_get.headers.get("Replay-Nonce")

        if not nonce:
            raise RuntimeError("Failed to obtain ACME nonce from newNonce endpoint")

        return nonce

    def compute_jwk_thumbprint(self) -> str:
        ordered = {"e": self.jwk["e"], "kty": self.jwk["kty"], "n": self.jwk["n"]}
        jwk_json = json.dumps(ordered, separators=(",", ":"), sort_keys=True)
        digest = hashlib.sha256(jwk_json.encode("utf-8")).digest()

        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    def compute_dns01_keyauth(self, key_auth: str) -> str:
        digest = hashlib.sha256(key_auth.encode("utf-8")).digest()
        txt = base64.urlsafe_b64encode(digest).decode("utf-8")
        txt = txt.rstrip("=")
        return txt
