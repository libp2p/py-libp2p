import pytest
import asyncio

from network.connection.raw_connection import RawConnection


async def handle_echo(reader, writer):
    data = await reader.read(100)
    message = data.decode()

    writer.write(data)
    await writer.drain()

    writer.close()

@pytest.mark.asyncio
async def test_echo():
    server_ip = '127.0.0.1'
    server_port = 8888
    await asyncio.start_server(handle_echo, server_ip, server_port)

    reader, writer = await asyncio.open_connection(server_ip, server_port)
    raw_connection = RawConnection(server_ip, server_port, reader, writer)
    
    test_message = "hello world"
    writer.write(test_message.encode())
    response = (await reader.read()).decode()
    
    assert response == (test_message)
