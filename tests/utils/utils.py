from unittest.mock import MagicMock

def create_mock_connections() -> dict:
    connections = {}

    for i in range(1, 31):
        peer_id = f"peer-{i}"
        mock_conn = MagicMock(name=f"INetConn-{i}")
        connections[peer_id] = mock_conn

    return connections