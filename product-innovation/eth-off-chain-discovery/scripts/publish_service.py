import trio
import os
import json
import signal
from web3 import Web3
from typing import Any
from libp2p.kad_dht.kad_dht import KadDHT
from libp2p.crypto.ed25519 import Ed25519PrivateKey

from p2p.constants import get_eth_config, DEPLOY_JSON, KEYS_DIR, REPUBLISH_INTERVAL_SECONDS
from p2p.node import Libp2pNode
from p2p.dht import create_dht
from p2p.service_publisher import ServicePublisher
from p2p.record import derive_dht_key, derive_pointer_bytes, derive_owner_key
from p2p.validator import ServiceValidator
from p2p.logging_config import setup_logging
from libp2p.tools.async_service import background_trio_service
from libp2p.kad_dht.kad_dht import DHTMode

log = setup_logging("publisher")

async def republish_loop(publisher: ServicePublisher, node: Libp2pNode, dht_key_provider: str, dht_key_base: str):
    while True:
        try:
            log.info("Republishing record to DHT...")
            await publisher.publish_once(node.peer_id, list(node.peer_info.addrs), dht_key_provider)
            
            await publisher.dht.provide(dht_key_base)
            log.debug("Successfully re-published and announced")
        except Exception as e:
            log.error(f"Republish failed: {e}")
        
        await trio.sleep(REPUBLISH_INTERVAL_SECONDS)

def load_contract():
    if not os.path.exists(DEPLOY_JSON):
        log.error(f"Missing {DEPLOY_JSON}")
        raise FileNotFoundError(f"Deploy file not found: {DEPLOY_JSON}")
    
    with open(DEPLOY_JSON, 'r') as f:
        deploy_data = json.load(f)
    
    return deploy_data["contract_address"], deploy_data["abi"]["abi"]

def get_service_key_path(service_id_str: str, suffix: str) -> str:
    safe_name = service_id_str.replace(':', '_').replace('/', '_')
    return os.path.join(KEYS_DIR, f"{safe_name}_{suffix}")

async def publish_service_task(
    service_id_str: str,
    w3: Web3,
    contract: Any,
    account: Any,
    eth_config: Any,
    node: Libp2pNode,
    dht: KadDHT,
    owner_private_key: Ed25519PrivateKey,
    nursery: trio.Nursery
):
    service_id = Web3.keccak(text=service_id_str)
    log.info(f"Processing Service: {service_id_str} → {service_id.hex()}")

    dht_key_base = derive_dht_key(service_id)
    dht_key_provider = f"{dht_key_base}/{node.peer_id.to_base58()}"
    pointer_bytes = derive_pointer_bytes(service_id)

    try:
        base_fee = w3.eth.get_block('latest').get('baseFeePerGas', 0)
    except Exception:
        base_fee = w3.to_wei(20, 'gwei')
    
    max_priority_fee = w3.to_wei(1.5, 'gwei')
    max_fee_per_gas = int(base_fee * 1.25) + max_priority_fee

    owner_onchain = contract.functions.getServiceOwner(service_id).call()
    if owner_onchain != account.address:
        log.info(f"[{service_id_str}] Registering service on-chain...")
        try:
            tx = contract.functions.registerService(service_id).build_transaction({
                'from': account.address,
                'nonce': w3.eth.get_transaction_count(account.address),
                'gas': 200000,
                'maxFeePerGas': max_fee_per_gas,
                'maxPriorityFeePerGas': max_priority_fee,
                'type': 2
            })
            signed_tx = w3.eth.account.sign_transaction(tx, eth_config.private_key)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            log.info(f"[{service_id_str}] Tx sent: {tx_hash.hex()}")
            w3.eth.wait_for_transaction_receipt(tx_hash)
            log.info(f"[{service_id_str}] Service registered")
        except Exception as e:
            log.error(f"[{service_id_str}] Registration failed: {e}")
            return

    current_pointer = contract.functions.getServicePointer(service_id).call()
    if (not current_pointer) or (bytes(current_pointer) != pointer_bytes):
        log.info(f"[{service_id_str}] Setting pointer on-chain...")
        try:
            tx = contract.functions.setServicePointer(service_id, pointer_bytes).build_transaction({
                'from': account.address,
                'nonce': w3.eth.get_transaction_count(account.address),
                'gas': 200000,
                'maxFeePerGas': max_fee_per_gas,
                'maxPriorityFeePerGas': max_priority_fee,
                'type': 2
            })
            signed_tx = w3.eth.account.sign_transaction(tx, eth_config.private_key)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            log.info(f"[{service_id_str}] Tx sent: {tx_hash.hex()}")
            w3.eth.wait_for_transaction_receipt(tx_hash)
            log.info(f"[{service_id_str}] Pointer set")
        except Exception as e:
            log.error(f"[{service_id_str}] Setting pointer failed: {e}")
            return
    else:
        log.info(f"[{service_id_str}] Pointer already set")

    os.makedirs(KEYS_DIR, exist_ok=True)
    pubkey_file = get_service_key_path(service_id_str, "pubkey.hex")
    owner_public_key = owner_private_key.get_public_key()
    pubkey_hex = owner_public_key.to_bytes().hex()
    with open(pubkey_file, 'w') as f:
        f.write(pubkey_hex)
    
    all_addrs = node.host.get_addrs()
    peer_id_str = node.peer_id.to_base58()
    if all_addrs:
        addr_file = get_service_key_path(service_id_str, "publisher_addr.txt")
        with open(addr_file, 'w') as f:
            for addr in all_addrs:
                addr_str = str(addr)
                if f"/p2p/{peer_id_str}" not in addr_str:
                    addr_str = f"{addr_str}/p2p/{peer_id_str}"
                f.write(f"{addr_str}\n")

    publisher = ServicePublisher(dht=dht, service_id=service_id, private_key=owner_private_key)
    nursery.start_soon(republish_loop, publisher, node, dht_key_provider, dht_key_base)
    log.info(f"[{service_id_str}] Background re-publishing started")

async def main():
    try:
        CONTRACT_ADDRESS, SERVICE_ABI = load_contract()
    except FileNotFoundError:
        return
    
    eth_config = get_eth_config()
    w3 = Web3(Web3.HTTPProvider(eth_config.rpc_url))
    
    if not w3.is_connected():
        log.error("RPC connection failed")
        return

    account = w3.eth.account.from_key(eth_config.private_key)
    if eth_config.default_service_id:
        service_ids = [sid.strip() for sid in eth_config.default_service_id.split(",") if sid.strip()]
    else:
        service_ids = []
    
    contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=SERVICE_ABI)

    log.info(f"Account: {account.address}")
    log.info(f"Managing {len(service_ids)} services: {service_ids}")

    node = Libp2pNode(listen_addrs=eth_config.listen_addrs)
    host = node.create_host()
    listen_addrs = node.get_listen_addrs()

    owner_private_key = derive_owner_key(eth_config.private_key)

    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

        log.info(f"Peer ID: {node.peer_id.pretty()}")
        for addr in node.peer_info.addrs:
            log.info(f"Listening: {addr}")

        dht = create_dht(host, DHTMode.SERVER)
        dht.register_validator("service", ServiceValidator())

        async with background_trio_service(dht):
            log.info("DHT started (SERVER mode)")

            await trio.sleep(1)

            for sid in service_ids:
                await publish_service_task(
                    sid.strip(), w3, contract, account, eth_config, node, dht, owner_private_key, nursery
                )
            
            log.info(f"Ready! Re-publishing every {REPUBLISH_INTERVAL_SECONDS}s. Press Ctrl+C to shutdown")

            with trio.open_signal_receiver(signal.SIGINT, signal.SIGTERM) as signal_aiter:
                async for sig in signal_aiter:
                    log.warning(f"Received {signal.Signals(sig).name}, shutting down...")
                    nursery.cancel_scope.cancel()
                    break


if __name__ == "__main__":
    import sys
    try:
        trio.run(main)
    except (KeyboardInterrupt, ExceptionGroup, BaseExceptionGroup):
        sys.exit(0)
