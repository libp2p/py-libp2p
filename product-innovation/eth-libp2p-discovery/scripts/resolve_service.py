import asyncio
import os
import json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from web3 import Web3

from p2p.constants import get_eth_config
from p2p.node import Libp2pNode
from p2p.dht import DHTNode
from p2p.service_resolver import ServiceResolver

DEPLOY_JSON = "./deploy_output.json"
if os.path.exists(DEPLOY_JSON):
    with open(DEPLOY_JSON, 'r') as f:
        deploy_data = json.load(f)
        CONTRACT_ADDRESS = deploy_data["contract_address"]
        SERVICE_ABI = deploy_data["abi"]["abi"]
else:
    print(f"Missing {DEPLOY_JSON}")
    exit(1)

async def main():
    eth_config = get_eth_config()
    service_id_str = eth_config["default_service_id"]
    pubkey_file = f"keys/{service_id_str.replace(':', '_').replace('/', '_')}_pubkey.hex"
    
    if not os.path.exists(pubkey_file):
        print(f"Missing: {pubkey_file}")
        print("Run publish_service.py first")
        exit(1)
    
    with open(pubkey_file, 'r') as f:
        owner_pubkey_hex = f.read().strip()
    
    owner_public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(owner_pubkey_hex))
    
    w3 = Web3(Web3.HTTPProvider(eth_config["rpc_url"]))
    service_id = Web3.keccak(text=service_id_str)
    contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=SERVICE_ABI)
    
    print(f"Resolving: {service_id_str}")

    node = Libp2pNode()
    await node.start()
    print(f"Resolver ID: {node.peer_id.pretty()}")

    dht = DHTNode(node.host)
    await dht.start()

    resolver = ServiceResolver(dht=dht, owner_public_key=owner_public_key)

    pointer = contract.functions.getServicePointer(service_id).call()
    if len(pointer) == 0:
        print("No pointer on-chain")
        return
    
    print(f"Pointer: {bytes(pointer).hex()}")

    peer = await resolver.resolve(bytes(pointer))
    if not peer:
        print("Not found/invalid")
        return

    print("Resolved!")
    print(f"ID: {peer.peer_id.pretty()}")
    for i, addr in enumerate(peer.addrs, 1):
        print(f"{i}. {addr}")

if __name__ == "__main__":
    asyncio.run(main())
