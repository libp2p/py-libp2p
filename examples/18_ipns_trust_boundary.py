"""
Example 18: IPNS Trust Boundary Demo

Demonstrates that IPNS records are cryptographically authenticated and tied to the publisher's Peer ID.
We simulate an "Attacker" trying to forge an IPNS record for a legitimate "Publisher" by signing a 
malicious record with their own key, but attaching it to the Publisher's IPNS routing key.
"""

import logging
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from py_ipfs_lite.ipns import create_ipns_record, validate_ipns_record
from libp2p.records.pb.ipns_pb2 import IpnsEntry

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("demo")

def main():
    logger.info("--- IPNS Trust Boundary Demo ---")
    
    # 1. Setup Publisher
    publisher_keypair = create_new_key_pair()
    publisher_id = ID.from_pubkey(publisher_keypair.public_key)
    logger.info(f"\n[Publisher] Identity generated: {publisher_id.to_base58()}")
    
    # Publisher creates authentic record
    authentic_val = "/ipfs/bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
    logger.info(f"[Publisher] Creating authentic record targeting: {authentic_val}")
    authentic_record_bytes = create_ipns_record(publisher_keypair.private_key, authentic_val, sequence=1)
    
    # Validate authentic record
    logger.info("[Consumer] Validating authentic record against Publisher's Peer ID...")
    try:
        validate_ipns_record(authentic_record_bytes, publisher_id)
        logger.info("✅ [Consumer] Authentic record accepted!")
    except Exception as e:
        logger.error(f"❌ [Consumer] Authentic record rejected: {e}")

    # 2. Setup Attacker
    attacker_keypair = create_new_key_pair()
    attacker_id = ID.from_pubkey(attacker_keypair.public_key)
    logger.info(f"\n[Attacker] Identity generated: {attacker_id.to_base58()}")
    
    malicious_val = "/ipfs/bafybeihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku"
    logger.info(f"[Attacker] Attempting to forge record targeting malicious payload: {malicious_val}")
    logger.info(f"[Attacker] Strategy: Sign malicious payload with attacker key, but inject it into DHT under publisher's routing key.")
    
    # Attacker tries to forge the record. 
    # They sign it with their OWN private key (since they don't have the publisher's).
    forged_record_bytes = create_ipns_record(attacker_keypair.private_key, malicious_val, sequence=2)
    
    # Attacker might try to be sneaky and replace the embedded pubKey with the publisher's pubKey
    # to make it look like it came from the publisher.
    sneaky_entry = IpnsEntry()
    sneaky_entry.ParseFromString(forged_record_bytes)
    sneaky_entry.pubKey = publisher_keypair.public_key.serialize()
    sneaky_forged_bytes = sneaky_entry.SerializeToString()
    
    # Validate forged record 1 (Attacker's pubkey embedded)
    logger.info("\n[Consumer] Receiving forged record 1 (Attacker's pubkey embedded)...")
    try:
        validate_ipns_record(forged_record_bytes, publisher_id)
        logger.error("❌ [Consumer] FATAL: Forged record accepted! (This would be bug 3.3)")
    except Exception as e:
        logger.info(f"✅ [Consumer] Forged record correctly rejected: {e}")

    # Validate forged record 2 (Publisher's pubkey embedded, but signed by attacker)
    logger.info("\n[Consumer] Receiving forged record 2 (Publisher's pubkey embedded, invalid signature)...")
    try:
        validate_ipns_record(sneaky_forged_bytes, publisher_id)
        logger.error("❌ [Consumer] FATAL: Forged record accepted!")
    except Exception as e:
        logger.info(f"✅ [Consumer] Forged record correctly rejected: {e}")

if __name__ == "__main__":
    main()
