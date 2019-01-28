import asyncio
import pytest


async def handle_echo(reader, writer):
    data = await reader.read(100)
    writer.write(data)
    await writer.drain()
    writer.close()


@pytest.mark.asyncio
# TODO: this test should develop out into a fuller test between MPlex
# modules communicating with each other.
async def test_simple_echo():
    server_ip = '127.0.0.1'
    server_port = 8888
    await asyncio.start_server(handle_echo, server_ip, server_port)

    reader, writer = await asyncio.open_connection(server_ip, server_port)

    test_message = "hello world"
    writer.write(test_message.encode())
    response = (await reader.read()).decode()

    assert response == (test_message)
