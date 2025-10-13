import argparse
import logging
import time
from typing import Dict, List, Optional

import trio

from libp2p import new_host
from libp2p.crypto.rsa import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.record.exceptions import ErrInvalidRecordType
from libp2p.record.record import Record
from libp2p.record.validator import NamespacedValidator, Validator
from libp2p.record.validators.pubkey import PublicKeyValidator
from libp2p.utils.address_validation import (
    find_free_port,
    get_available_interfaces,
    get_optimal_binding_address,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("record-demo")

class CustomValidator(Validator):
    """Custom validator for records in the /custom/ namespace."""

    def validate(self, rec: Record) -> None:
        """Validate that the record's value starts with 'CUSTOM_' prefix."""
        ns, _ = rec.key_str.split("/", 2)[1:3]
        if ns != "custom":
            raise ErrInvalidRecordType("namespace not 'custom'")

        try:
            value_str = rec.value_str
            if not value_str.startswith("CUSTOM_"):
                raise ErrInvalidRecordType("value does not start with 'CUSTOM_'")
        except UnicodeDecodeError:
            raise ErrInvalidRecordType("value is not valid UTF-8")

    def select(self, key: str, values: List[Record]) -> Record:
        """Select the record with the most recent time_received."""
        if not values:
            raise ValueError("can't select from no values")

        latest_index = 0
        latest_time = float(values[0].time_received or "0")

        for i, rec in enumerate(values[1:], 1):
            try:
                current_time = float(rec.time_received or "0")
                if current_time > latest_time:
                    latest_index = i
                    latest_time = current_time
            except ValueError:
                continue

        return values[latest_index]

class SimpleRecordStore:
    """Simple in-memory store for Records."""

    def __init__(self):
        self.store: Dict[bytes, Record] = {}

    def put(self, record: Record) -> bool:
        """Store a record."""
        try:
            self.store[record.key] = record
            logger.info(f"Stored record with key: {record.key_str}")
            return True
        except Exception as e:
            logger.error(f"Failed to store record with key {record.key_str}: {str(e)}")
            return False

    def get(self, key: bytes) -> Optional[Record]:
        """Retrieve a record by key."""
        record = self.store.get(key)
        if record:
            logger.info(f"Retrieved record with key: {record.key_str}")
            return record
        logger.warning(f"No record found for key: {key.hex()}")
        return None

def register_custom_validator(registry: dict) -> dict:
    """Register a custom validator for the /custom/ namespace."""
    registry["/custom/"] = CustomValidator()
    logger.info("Registered custom validator for /custom/ namespace")
    return registry

def validate_and_select(
        validator: NamespacedValidator,
        new_record: Record,
        existing_record: Optional[Record] = None
    ) -> Optional[Record]:
    """Validate a record and select the best if an existing record exists."""
    try:
        validator.validate(new_record)
        logger.debug(f"Validated record with key: {new_record.key_str}")

        if existing_record:
            candidates = [new_record, existing_record]
            return validator.select(new_record.key_str, candidates)
        return new_record
    except Exception as e:
        logger.error(f"Record validation failed for key {new_record.key_str}: {str(e)}")
        return None

async def create_and_validate_records(
        host,
        key_pair,
        namespace: str,
        custom_value: str | None,
        store: SimpleRecordStore,
        validator: NamespacedValidator
      ):
    """Create, validate, store, and retrieve Records."""
    # Create a public key record
    peer_id = ID.from_pubkey(key_pair.get_public_key())
    pk_key = f"/{namespace}/{peer_id.to_string()}".encode('utf-8')
    pk_value = key_pair.get_public_key().serialize()

    record1 = Record(
        key=pk_key,
        value=pk_value,
        time_received=str(time.time())
    )
    logger.info(f"Created public key record with key: {record1.key_str}")

    try:
        # Validate and select before storing public key record
        existing_record = store.get(pk_key)
        selected_record = validate_and_select(validator, record1, existing_record)
        if selected_record and store.put(selected_record):
            logger.info("Public key record stored successfully")

        # Retrieve and validate the public key record
        retrieved_record = store.get(pk_key)
        if retrieved_record:
            try:
                validator.validate(retrieved_record)
                logger.info("Retrieved public key record validation successful")

                # Demonstrate serialization/deserialization
                serialized = retrieved_record.marshal()
                deserialized = Record.unmarshal(serialized)
                if retrieved_record == deserialized:
                    logger.info("Serialization/deserialization successful")
                else:
                    logger.error("Serialization/deserialization failed")

                # Display record details
                logger.info("Public key record details:")
                logger.info(f"  Key: {retrieved_record.key_str}")
                logger.info(f"  Value: {retrieved_record.value.hex()}")
                logger.info(f"  Time Received: {retrieved_record.time_received}")
            except Exception as e:
                logger.error(f"Retrieved public key record validation failed: {str(e)}")

        # Demonstrate custom validator with custom namespace
        custom_key = "/custom/test-key".encode('utf-8')
        custom_value_to_use = custom_value or "CUSTOM_test-value"
        record2 = Record(
            key=custom_key,
            value=custom_value_to_use.encode('utf-8'),
            time_received=str(time.time())
        )
        logger.info(f"Created custom record with key: {record2.key_str}")

        # Validate and select before storing custom record
        existing_record = store.get(custom_key)
        selected_record = validate_and_select(validator, record2, existing_record)
        if selected_record and store.put(selected_record):
            logger.info("Custom record stored successfully")

        # Demonstrate conflict resolution by storing an older custom record
        record3 = Record(
            key=custom_key,
            value="CUSTOM_older-value".encode('utf-8'),
            time_received=str(time.time() - 3600)  # 1 hour older
        )
        existing_record = store.get(custom_key)
        selected_record = validate_and_select(validator, record3, existing_record)
        if selected_record and store.put(selected_record):
            logger.info("Older custom record stored, validator selected the best")

        # Retrieve and validate the custom record
        retrieved_custom = store.get(custom_key)
        if retrieved_custom:
            try:
                validator.validate(retrieved_custom)
                logger.info("Retrieved custom record validation successful")

                # Display custom record details
                logger.info("Custom record details:")
                logger.info(f"  Key: {retrieved_custom.key_str}")
                logger.info(f"  Value: {retrieved_custom.value_str}")
                logger.info(f"  Time Received: {retrieved_custom.time_received}")
            except Exception as e:
                logger.error(f"Retrieved custom record validation failed: {str(e)}")

        # Demonstrate invalid record handling
        invalid_record = Record(
            key=custom_key,
            value="INVALID_value".encode('utf-8'),
            time_received=str(time.time())
        )
        existing_record = store.get(custom_key)
        selected_record = validate_and_select(
            validator,
            invalid_record,
            existing_record
        )
        if not selected_record:
            logger.info("Invalid custom record correctly rejected by validator")
        elif store.put(selected_record):
            logger.info("Selected record stored after invalid record attempt")

    except Exception as e:
        logger.error(f"Public key record processing failed: {str(e)}")

async def run(port: int | None, namespace: str, custom_value: str | None) -> None:
    """Run the record demo."""
    if port is None or port == 0:
        port = find_free_port()
        logger.info(f"Using random available port: {port}")

    listen_addrs = get_available_interfaces(port)

    # Generate key pair and create host
    key_pair = create_new_key_pair()
    host = new_host(key_pair=key_pair)

    # Initialize validator registry and store
    registry = {"/pk/": PublicKeyValidator()}
    registry = register_custom_validator(registry)
    namespaced_validator = NamespacedValidator(registry)
    store = SimpleRecordStore()

    logger.info(f"Node started with peer ID: {host.get_id()}")

    async with host.run(listen_addrs=listen_addrs):
        # Get all available addresses with peer ID
        all_addrs = host.get_addrs()
        logger.info("Listener ready, listening on:")
        for addr in all_addrs:
            logger.info(f"{addr}")

        # Use optimal address for client command
        optimal_addr = get_optimal_binding_address(port)
        optimal_addr_with_peer = f"{optimal_addr}/p2p/{host.get_id().to_string()}"
        logger.info(
            f"\nRun another instance with:\n\n"
            f"python record_demo.py -p <ANOTHER_PORT> -d {optimal_addr_with_peer}\n"
        )

        try:
            # Run the record creation, storage, and retrieval demo
            await create_and_validate_records(
                host,
                key_pair,
                namespace,
                custom_value,
                store,
                namespaced_validator
            )

            # Keep the node running until interrupted
            await trio.Event().wait()

        except Exception as e:
            logger.error(f"Error in record demo: {str(e)}")

def main() -> None:
    description = """
    This program demonstrates the usage of the Record, Validator, and PublicKeyValidator
    modules, including registering a custom validator and storing records.
    It validates records before storing and uses select to resolve conflicts.
    Run with 'python record_demo.py -p <PORT> -n <NAMESPACE> [-v] [-c <CUSTOM_VALUE>]'.
    """

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        help="Port to listen on",
        default=None,
    )
    parser.add_argument(
        "-n",
        "--namespace",
        type=str,
        help="Namespace for the public key record",
        default="pk",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "-c",
        "--custom-value",
        type=str,
        help="Custom value for /custom/ namespace (must start with 'CUSTOM_')",
        default=None,
    )
    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help="Address of peer to connect to",
        default=None,
    )

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    logger.info("Running record demo...")
    logger.info(f"Using namespace for public key: {args.namespace}")
    if args.custom_value:
        logger.info(f"Using custom value: {args.custom_value}")

    try:
        trio.run(run, *(args.port, args.namespace, args.custom_value))
    except KeyboardInterrupt:
        logger.info("Application terminated by user")
    finally:
        logger.info("Application shutdown complete")

if __name__ == "__main__":
    main()
