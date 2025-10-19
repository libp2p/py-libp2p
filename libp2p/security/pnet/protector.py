from libp2p.abc import IRawConnection
from libp2p.network.connection.raw_connection import RawConnection
from libp2p.security.pnet.psk_conn import PskConn


def new_protected_conn(conn: RawConnection | IRawConnection, psk: str) -> PskConn:
    if len(psk) != 64:
        raise ValueError("Expected 32-byte pre shared key (PSK)")

    return PskConn(conn, psk)
