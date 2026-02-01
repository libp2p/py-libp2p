import trio
import os
import json
import signal
from libp2p.crypto.ed25519 import Ed25519PublicKey
from web3 import Web3
from multiaddr import Multiaddr

from p2p.constants import get_eth_config, DEPLOY_JSON, KEYS_DIR
from p2p.node import Libp2pNode
from p2p.dht import create_dht
from p2p.service_resolver import ServiceResolver
from p2p.record import derive_dht_key
from p2p.validator import ServiceValidator
from p2p.logging_config import setup_logging
from libp2p.tools.async_service import background_trio_service
from libp2p.tools.utils import info_from_p2p_addr
from libp2p.kad_dht.kad_dht import DHTMode

log = setup_logging("resolver")

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

async def main():
    try:
        CONTRACT_ADDRESS, SERVICE_ABI = load_contract()
    except FileNotFoundError:
        return
    
    eth_config = get_eth_config()
    service_ids_raw = eth_config.default_service_id.split(",") if eth_config.default_service_id else []
    service_ids = [sid.strip() for sid in service_ids_raw if sid.strip()]
    
    if not service_ids:
        log.error("No service IDs found in SERVICE_ID_STR")
        return

    w3 = Web3(Web3.HTTPProvider(eth_config.rpc_url))
    contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=SERVICE_ABI)

    node = Libp2pNode()
    host = node.create_host()
    listen_addrs = node.get_listen_addrs()

    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)
        log.info(f"Resolver ID: {node.peer_id.pretty()}")

        dht = create_dht(host, DHTMode.CLIENT)
        dht.register_validator("service", ServiceValidator())

        async with background_trio_service(dht):
            log.info("DHT started (CLIENT mode)")

            for service_id_str in service_ids:
                log.info("-" * 40)
                log.info(f"Resolving Service: {service_id_str}")
                
                pubkey_file = get_service_key_path(service_id_str, "pubkey.hex")
                addr_file = get_service_key_path(service_id_str, "publisher_addr.txt")
                
                if not os.path.exists(pubkey_file) or not os.path.exists(addr_file):
                    log.warning(f"Metadata missing for {service_id_str}. Skipping...")
                    continue
                
                with open(pubkey_file, 'r') as f:
                    owner_pubkey_hex = f.read().strip()
                
                with open(addr_file, 'r') as f:
                    bootstrap_addrs = [line.strip() for line in f if line.strip()]
                
                owner_public_key = Ed25519PublicKey.from_bytes(bytes.fromhex(owner_pubkey_hex))
                
                for addr_str in bootstrap_addrs:
                    try:
                        peer_info = info_from_p2p_addr(Multiaddr(addr_str))
                        host.get_peerstore().add_addrs(peer_info.peer_id, peer_info.addrs, 3600)
                        await host.connect(peer_info)
                        log.info(f"Connected to potential provider: {peer_info.peer_id.pretty()}")
                    except Exception as e:
                        log.debug(f"Connection attempt failed: {e}")

                for peer_id in host.get_peerstore().peer_ids():
                    await dht.routing_table.add_peer(peer_id)

                resolver = ServiceResolver(dht=dht, owner_public_key=owner_public_key)
                service_id_hash = Web3.keccak(text=service_id_str)
                
                pointer = contract.functions.getServicePointer(service_id_hash).call()
                if len(pointer) == 0:
                    log.error(f"[{service_id_str}] No pointer on-chain")
                    continue
                
                dht_key_base = derive_dht_key(service_id_hash)
                providers = await dht.find_providers(dht_key_base)
                
                if not providers:
                    log.error(f"[{service_id_str}] No providers found in DHT")
                    continue

                log.info(f"[{service_id_str}] Found {len(providers)} providers")
                
                resolved_count = 0
                for provider_info in providers:
                    await dht.routing_table.add_peer(provider_info.peer_id)
                    dht_key_provider = f"{dht_key_base}/{provider_info.peer_id.to_base58()}"
                    peer = await resolver.resolve(dht_key_provider)
                    
                    if peer:
                        resolved_count += 1
                        log.info(f"[{service_id_str}] Provider {resolved_count}: {peer.peer_id.pretty()}")
                        for addr in peer.addrs:
                            log.info(f"  → {addr}")
                
                if resolved_count == 0:
                    log.error(f"[{service_id_str}] Failed to resolve records from providers")

            log.info("-" * 40)
            log.info("Resolution tasks complete.")
            return

if __name__ == "__main__":
    import sys
    try:
        trio.run(main)
    except (KeyboardInterrupt, ExceptionGroup, BaseExceptionGroup):
        sys.exit(0)
