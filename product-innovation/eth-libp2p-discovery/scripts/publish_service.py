import asyncio
import os
import json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization as crypto_serialization
from cryptography.hazmat.primitives.serialization import NoEncryption
from web3 import Web3

from p2p.constants import get_eth_config
from p2p.node import Libp2pNode
from p2p.dht import DHTNode
from p2p.service_publisher import ServicePublisher
from p2p.record import derive_dht_key

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
    w3 = Web3(Web3.HTTPProvider(eth_config["rpc_url"]))
    if not w3.is_connected():
        print("RPC connection failed")
        exit(1)
    
    account = w3.eth.account.from_key(eth_config["private_key"])
    service_id_str = eth_config["default_service_id"]
    service_id = Web3.keccak(text=service_id_str)
    
    contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=SERVICE_ABI)
    
    print(f"Account: {account.address}")
    print(f"Service: {service_id_str} -> {service_id.hex()}")

    node = Libp2pNode()
    await node.start()
    print("Peer ID:", node.peer_id.pretty())
    print("Addrs:", [str(a) for a in node.peer_info.addrs])

    dht = DHTNode(node.host)
    await dht.start()

    dht_key = derive_dht_key(service_id)
    print(f"DHT Key: {dht_key.hex()}")

    latest_block = w3.eth.get_block('latest')
    base_fee = latest_block.get('baseFeePerGas', None)
    if base_fee is None:
        base_fee = w3.to_wei(20, 'gwei')
    max_priority_fee = w3.to_wei(2, 'gwei')
    max_fee_per_gas = base_fee + max_priority_fee

    if contract.functions.getServiceOwner(service_id).call() != account.address:
        print("Registering...")
        tx = contract.functions.registerService(service_id).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gas': 200000,
            'maxFeePerGas': max_fee_per_gas,
            'maxPriorityFeePerGas': max_priority_fee,
            'type': 2
        })
        signed_tx = w3.eth.account.sign_transaction(tx, eth_config["private_key"])
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        print(f"Registered: {tx_hash.hex()}")

    current_pointer = contract.functions.getServicePointer(service_id).call()
    if len(current_pointer) == 0 or bytes(current_pointer) != dht_key:
        print("Setting pointer...")
        tx = contract.functions.setServicePointer(service_id, dht_key).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gas': 200000,
            'maxFeePerGas': max_fee_per_gas,
            'maxPriorityFeePerGas': max_priority_fee,
            'type': 2
        })
        signed_tx = w3.eth.account.sign_transaction(tx, eth_config["private_key"])
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        print(f"Pointer set: {tx_hash.hex()}")
    else:
        print("Pointer OK")

    key_file = f"keys/{service_id_str.replace(':', '_').replace('/', '_')}_owner_key.json"
    os.makedirs("keys", exist_ok=True)
    
    if os.path.exists(key_file):
        with open(key_file, 'r') as f:
            key_data = json.load(f)
            owner_private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key_data["private_key_hex"]))
    else:
        owner_private_key = Ed25519PrivateKey.generate()
        key_bytes = owner_private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption()
        )
        key_data = {
            "private_key_hex": key_bytes.hex(),
            "service_id": service_id_str
        }
        with open(key_file, 'w') as f:
            json.dump(key_data, f)

    owner_public_key = owner_private_key.public_key()
    pubkey_hex = owner_public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    ).hex()
    
    pubkey_file = f"keys/{service_id_str.replace(':', '_').replace('/', '_')}_pubkey.hex"
    with open(pubkey_file, 'w') as f:
        f.write(pubkey_hex)
    print(f"PubKey: {pubkey_file}")

    publisher = ServicePublisher(dht=dht, service_id=service_id, private_key=owner_private_key)
    await publisher.start_auto_publish(node.peer_id, list(node.peer_info.addrs), dht_key)

    print("Published! Ctrl+C to stop")
    try:
        await asyncio.Event().wait()
    finally:
        await publisher.stop()
        await dht.stop()
        await node.stop()

if __name__ == "__main__":
    asyncio.run(main())
