import asyncio
import websockets
import json

connected_peers = {}

async def signaling_handler(websocket, path):
    async for message in websocket:
        data = json.loads(message)

        if data["type"] == "register":
            peer_id = data["peer_id"]
            connected_peers[peer_id] = websocket
            print(f"Peer {peer_id} registered.")

        elif data["type"] == "offer":
            target = data["target"]
            if target in connected_peers:
                await connected_peers[target].send(json.dumps(data))

        elif data["type"] == "answer":
            target = data["target"]
            if target in connected_peers:
                await connected_peers[target].send(json.dumps(data))

async def start_signaling_server():
    server = await websockets.serve(signaling_handler, "localhost", 8765)
    print("Signaling server started on ws://localhost:8765")
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(start_signaling_server())
