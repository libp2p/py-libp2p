import os

from Crypto.Cipher import Salsa20

from libp2p.abc import IRawConnection
from libp2p.network.connection.raw_connection import RawConnection


class PskConn(RawConnection):
    _psk: bytes
    _conn: RawConnection | IRawConnection

    def __init__(self, conn: RawConnection | IRawConnection, psk: str) -> None:
        self._psk = bytes.fromhex(psk)
        self._conn = conn

        self.read_cipher: Salsa20.Salsa20Cipher | None = None
        self.write_cipher: Salsa20.Salsa20Cipher | None = None

    async def write(self, data: bytes) -> None:
        """
        Encrpyts and writes data to the stream.
        On the first call, generates a 24-byte nonce and sends it first.
        """
        if self.write_cipher is None:
            nonce = os.urandom(8)
            await self._conn.write(nonce)
            self.write_cipher = Salsa20.new(key=self._psk, nonce=nonce)

        assert self.write_cipher is not None
        ciphertext = self.write_cipher.encrypt(data)

        await self._conn.write(ciphertext)

    async def read(self, n: int | None = None) -> bytes:
        """
        Reads and decrypts data. On the first call, it reads a 8-byte
        nonce to initialize the decryption stream
        """
        if self.read_cipher is None:
            nonce = await self._conn.read(8)
            if len(nonce) != 8:
                raise ValueError("short nonce from stream")

            self.read_cipher = Salsa20.new(key=self._psk, nonce=nonce)

        data = await self._conn.read(n)
        if not data:
            return b""

        plaintext = self.read_cipher.decrypt(data)
        return plaintext

    async def close(self) -> None:
        await self._conn.close()

    def get_remote_address(self) -> tuple[str, int] | None:
        return self._conn.get_remote_address()
