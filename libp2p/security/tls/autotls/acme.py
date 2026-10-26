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
    """
    Generate a new RSA private key.

    :param bits: RSA key size in bits.
    :return: Generated RSA private key.
    """
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=bits,
        backend=default_backend(),
    )
    return key


def compute_b36_peer_id(peerid: ID) -> str:
    """
    Compute the base36-encoded Peer ID representation used by AutoTLS.

    The Peer ID multihash is wrapped in a CIDv1 (dag-pb) prefix and then encoded
    using multibase base36. This format is required by the AutoTLS broker and
    ACME DNS challenge flow.

    :param peerid: Peer ID to encode.
    :return: Base36-encoded CID representation of the Peer ID.
    """
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

    """
    ACME client responsible for provisioning TLS certificates for a libp2p peer.

    Manages account registration, DNS-01 challenge flow, and certificate issuance
    using keys derived from the peer's identity.
    """

    def __init__(
        self,
        libp2p_privkey: PrivateKey,
        local_peer: ID,
    ):
        """
        Initialize an ACME client bound to a libp2p peer identity.

        Derives the base36 Peer ID, generates distinct RSA keys for the ACME account
        and certificate, and prepares JWK and CSR material required for the ACME flow.

        :param libp2p_privkey: Private key of the local libp2p peer.
        :param local_peer: Peer ID of the local host.
        """
        self.libp2p_privkey = libp2p_privkey
        self.local_peer = local_peer
        self.b36_peerid = compute_b36_peer_id(self.local_peer)

        self.acct_rsa_key = generate_rsa_key(2048)
        self.cert_rsa_key = generate_rsa_key(2048)

        self.jwk = self.jwk_from_rsa_privkey()
        self.jwk_thumbprint = self.compute_jwk_thumbprint()

        csr_der = self.create_csr()
        self.csr_b64 = self.b64url_encode(csr_der)

    async def create_acme_acct(self) -> None:
        """
        Create or fetch an ACME account for this client.

        Fetches the ACME directory, constructs and signs a newAccount JWS using the
        account RSA key, and registers the account with the ACME server. The resulting
        account URL is stored for use in subsequent ACME requests.

        Network operations are executed in a thread pool to avoid blocking the Trio
        event loop.

        :return: None
        :raises RuntimeError: if account creation fails with a non-success response.
        :raises ValueError: if the ACME server does not return an account URL.
        """
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

        if account_url is None:
            raise ValueError("Could not fetch account url from response")

        self.account_url = account_url

    async def initiate_order(self) -> None:
        """
        Create a new ACME certificate order for the peer's DNS name.

        Submits a newOrder request for a wildcard domain derived from the peer's
        base36 Peer ID and stores the returned order, authorization, and finalize
        URLs for subsequent challenge and certificate finalization steps.

        Network operations are executed in a thread pool to avoid blocking the Trio
        event loop.

        :return: None
        :raises KeyError: if the ACME directory or response is missing required fields.
        :raises requests.HTTPError: if the ACME server returns a non-success response.
        """
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

    async def get_dns01_challenge(self) -> None:
        """
        Fetch and prepare the DNS-01 challenge for the current ACME order.

        Queries the authorization URL, extracts the DNS-01 challenge, and computes
        the key authorization value required for DNS record provisioning. Challenge
        metadata is stored for use by the AutoTLS broker and order finalization.

        :return: None
        :raises RuntimeError: if no DNS-01 challenge is present in the authorization.
        """
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

    async def notify_dns_ready(self, delay: int = 5) -> None:
        """
        Notify the ACME server that the DNS-01 challenge record is ready.

        Polls the challenge URL until the ACME server validates the DNS record or
        reports failure. The method blocks until the challenge reaches a terminal
        state.

        :param delay: Polling interval in seconds between challenge status checks.
        :return: None
        :raises RuntimeError: if the ACME server marks the challenge as invalid.
        """
        nonce = await self.get_nonce()
        (replay_nonce, _) = await self._dns_poll(nonce)

        while True:
            (replay_nonce, body) = await self._dns_poll(replay_nonce)
            status = body.get("status")

            if status == "valid":
                logger.info("Notified ACME, about challenge completion")
                break

            if status == "invalid":
                raise RuntimeError(f"Challenge failed: {body}")

            await trio.sleep(delay)

    async def _dns_poll(self, nonce: str) -> (str, Any):  # type: ignore
        """
        Poll the ACME DNS-01 challenge endpoint.

        Sends a signed POST-as-GET request to the challenge URL and returns the
        updated replay nonce along with the decoded response body. This helper is
        used to repeatedly check challenge status during DNS propagation.

        :param nonce: Replay nonce to include in the ACME request.
        :return: Tuple of (next replay nonce, response body).
        :raises RuntimeError: if the ACME response does not include a Replay-Nonce.
        """
        payload: dict[str, str] = {}
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

        return (replay_nonce, resp.json())

    async def fetch_cert_url(self) -> None:
        """
        Finalize the ACME order and retrieve the certificate download URL.

        Submits the CSR to the ACME server, then repeatedly polls the order endpoint
        until the order reaches a valid state. On success, the certificate URL is
        extracted and stored for subsequent certificate retrieval.

        :return: None
        :raises RuntimeError: if the ACME order never transitions to a valid state.
        """
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

    async def fetch_certificate(self) -> None:
        """
        Download and persist the issued ACME certificate.

        Fetches the certificate chain from the ACME server, writes the PEM-encoded
        certificate and private key to disk, and loads the parsed certificate chain
        into memory for immediate use.

        :return: None
        """
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

            # Write private key to file (needed for SSL context)
            key_pem = self.cert_rsa_key.private_bytes(
                # key_pem = self.cert_rsa_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode()
            libp2p.utils.paths.AUTOTLS_KEY_PATH.write_text(key_pem)

            # Read PEM chain back from file
            pem_bytes = libp2p.utils.paths.AUTOTLS_CERT_PATH.read_bytes()
            self.cert_chain = x509.load_pem_x509_certificates(pem_bytes)

            san = (
                self.cert_chain[0]
                .extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
                .value
            )

            dns_names = san.get_values_for_type(x509.DNSName)  # type: ignore
            logger.info(
                "ACME-TLS certificate cached, DNS: %s, b36_pid: %s",
                dns_names,
                self.b36_peerid,
            )

    def create_jws(
        self,
        protected: dict[str, Any],
        payload: dict[str, Any] | None,
    ) -> dict[str, str]:
        """
        Create a JSON Web Signature (JWS) object for ACME requests.

        Encodes and signs the protected header and payload using the ACME account
        RSA key. When payload is None, an empty payload is used to satisfy ACME
        POST-as-GET semantics.

        :param protected: JWS protected header fields.
        :param payload: JWS payload, or None for POST-as-GET requests.
        :return: Dictionary containing base64url-encoded protected header, payload,
            and signature.
        """
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

    def create_csr(self) -> bytes:
        """
        Create a certificate signing request for the peer's DNS name.

        Builds and signs a CSR containing a wildcard DNS Subject Alternative Name
        derived from the peer's base36 Peer ID. The CSR is signed using the
        certificate RSA key and returned in DER format.

        :return: DER-encoded certificate signing request.
        """
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

    def jwk_from_rsa_privkey(self) -> dict[str, str]:
        """
        Construct a JSON Web Key (JWK) from the ACME account RSA key.

        Extracts the public modulus and exponent from the account key and encodes
        them in base64url form as required by ACME JWS headers.

        :return: Dictionary representing the RSA JWK.
        """
        pub = self.acct_rsa_key.public_key()
        numbers = pub.public_numbers()

        def int_to_b64u(n: int) -> str:
            length = (n.bit_length() + 7) // 8
            return self.b64url_encode(n.to_bytes(length, "big"))

        return {"kty": "RSA", "n": int_to_b64u(numbers.n), "e": int_to_b64u(numbers.e)}

    def b64url_encode(self, data: bytes) -> str:
        """Base64url encode without padding, returning str."""
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    async def get_nonce(self) -> str:
        """
        Fetch a fresh replay nonce from the ACME server.

        :return: Replay nonce value.
        :raises RuntimeError: if a nonce cannot be obtained from the ACME server.
        """
        new_nonce_url = self.directory["newNonce"]

        nonce_resp = await trio.to_thread.run_sync(
            lambda: requests.head(new_nonce_url, timeout=10)
        )

        nonce: str | None = None
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
        """
        Compute the JWK thumbprint for the ACME account key.

        Generates the SHA-256 digest of the canonical JSON representation of the
        account JWK and encodes it in base64url format. This thumbprint is used in
        DNS-01 key authorization.

        :return: Base64url-encoded JWK thumbprint.
        """
        ordered = {"e": self.jwk["e"], "kty": self.jwk["kty"], "n": self.jwk["n"]}
        jwk_json = json.dumps(ordered, separators=(",", ":"), sort_keys=True)
        digest = hashlib.sha256(jwk_json.encode("utf-8")).digest()

        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    def compute_dns01_keyauth(self, key_auth: str) -> str:
        """
        Compute the DNS-01 challenge key authorization record.

        Hashes the key authorization string with SHA-256 and encodes it in
        base64url format, suitable for inclusion in a DNS TXT record.

        :param key_auth: Key authorization string for the challenge.
        :return: Base64url-encoded DNS TXT record value.
        """
        digest = hashlib.sha256(key_auth.encode("utf-8")).digest()
        txt = base64.urlsafe_b64encode(digest).decode("utf-8")
        txt = txt.rstrip("=")
        return txt
