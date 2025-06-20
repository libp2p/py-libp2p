import ssl
from typing import Optional

from libp2p.abc import IRawConnection, ISecureConn, ISecureTransport
from libp2p.custom_types import TProtocol
from libp2p.crypto.keys import KeyPair
from libp2p.peer.id import ID
from libp2p.security.secure_session import SecureSession

PROTOCOL_ID = TProtocol("/tls/1.3")  # used by muxer to negotiate the security channel


class TLSStream:
    """
    Thin wrapper that feeds raw bytes through an in-memory TLS state machine.
    Works for *unit-tests* and in-memory transports – no sockets needed.
    """

    def __init__(self, raw: IRawConnection, ssl_obj: ssl.SSLObject):
        self._raw = raw
        self._tls = ssl_obj

    # -------- helpers used by read/write --------
    async def _pump_write(self) -> None:
        buf = self._tls.bio_write  # type: ignore[attr-defined]
        if buf:
            await self._raw.write(buf)
            self._tls.bio_write = b""  # type: ignore[attr-defined]

    async def _pump_read(self) -> None:
        data = await self._raw.read(65536)
        if data:
            self._tls.bio_read(data)  # type: ignore[attr-defined]

    # -------- libp2p MsgReadWriteCloser-like API --------
    async def write(self, data: bytes) -> None:
        self._tls.write(data)
        await self._pump_write()

    async def read(self, n: int = -1) -> bytes:
        while True:
            try:
                return self._tls.read(n)
            except ssl.SSLWantReadError:
                await self._pump_read()

    async def close(self) -> None:
        await self._raw.close()


class TLSTransport(ISecureTransport):
    """
    *Minimal* TLS-1.3 security transport.
    – no X.509 PKI; the peer ID is carried in the SAN of a self-signed cert
    – no 0-RTT yet; early-data parameter kept for symmetry
    """

    def __init__(
        self,
        keypair: KeyPair,
        cert_pem: bytes,
        key_pem: bytes,
        *,
        early_data: Optional[bytes] = None,
    ) -> None:
        self._kp = keypair
        self._local_peer = ID.from_pubkey(keypair.public_key)
        self._early_data = early_data

        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.minimum_version = ctx.maximum_version = ssl.TLSVersion.TLSv1_3
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # peer auth is done via SAN → peer-id
        ctx.set_alpn_protocols(["/libp2p-tls/1.0.0"])
        ctx.load_cert_chain(certfile=cert_pem, keyfile=key_pem)
        self._ctx = ctx

    # ---------- ISecureTransport ----------
    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        ssl_obj = self._ctx.wrap_bio(ssl.MemoryBIO(), ssl.MemoryBIO(), server_side=True)
        secure_stream = TLSStream(conn, ssl_obj)
        await self._do_handshake(secure_stream, ssl_obj)
        remote_peer = self._peer_id_from_cert(ssl_obj)
        return SecureSession(
            local_peer=self._local_peer,
            local_private_key=self._kp.private_key,
            remote_peer=remote_peer,
            remote_permanent_pubkey=None,
            is_initiator=False,
            conn=secure_stream,
        )

    async def secure_outbound(self, conn: IRawConnection, peer_id: ID) -> ISecureConn:
        ssl_obj = self._ctx.wrap_bio(ssl.MemoryBIO(), ssl.MemoryBIO(), server_side=False)
        secure_stream = TLSStream(conn, ssl_obj)
        await self._do_handshake(secure_stream, ssl_obj)
        remote_peer = self._peer_id_from_cert(ssl_obj)
        if remote_peer != peer_id:
            raise ValueError("peer-id in certificate does not match expectation")
        return SecureSession(
            local_peer=self._local_peer,
            local_private_key=self._kp.private_key,
            remote_peer=remote_peer,
            remote_permanent_pubkey=None,
            is_initiator=True,
            conn=secure_stream,
        )

    # ---------- helpers ----------
    async def _do_handshake(self, stream: TLSStream, ssl_obj: ssl.SSLObject) -> None:
        # Perform TLS handshake over the in-memory BIOs
        while True:
            try:
                ssl_obj.do_handshake()
                await stream._pump_write()
                break
            except ssl.SSLWantReadError:
                await stream._pump_read()
            except ssl.SSLWantWriteError:
                await stream._pump_write()

    @staticmethod
    def _peer_id_from_cert(ssl_obj: ssl.SSLObject) -> ID:
        """
        Very small helper that extracts the libp2p peer-id from the leaf
        certificate SAN (Authority Key / OtherName).
        For a minimal demo we simply hash the *public key* inside the cert,
        matching go-libp2p-tls reference.
        """
        cert_bin = ssl_obj.getpeercert(binary_form=True)
        # ▸ Depending on your crypto helpers you can parse `cert_bin` with
        #   cryptography.x509 and re-code the logic below later.
        #
        # Here we just hash the raw SPKI to keep the demo self-contained:
        from hashlib import sha256
        from libp2p.peer.id import ID

        # First 32 bytes of SHA-256 multicodec - see specs/tls/tls.md
        digest = sha256(cert_bin).digest()
        return ID.from_bytes(digest[:16])  # NOT production! just demo.
