import tempfile

import pytest

from py_ipfs_lite.config import Config
from py_ipfs_lite.peer import Peer


@pytest.fixture
def memory_config():
    return Config(blockstore_type="memory", reprovide_interval_seconds=-1)


@pytest.mark.trio
async def test_pin_types(memory_config):
    peer = Peer(memory_config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    try:
        # 1. Create a DAG (root -> child)
        child_data = {"data": "child"}
        child_cid = await peer.add_node(child_data)

        root_data = {"links": [{"/": child_cid}]}
        root_cid = await peer.add_node(root_data)

        # 2. Pin root recursively
        await peer.add_pin(root_cid, recursive=True)

        # 3. List pins
        pins_all = await peer.list_pins(type_filter="all")
        pins_recursive = await peer.list_pins(type_filter="recursive")
        pins_indirect = await peer.list_pins(type_filter="indirect")
        pins_direct = await peer.list_pins(type_filter="direct")

        assert pins_recursive.get(root_cid) == "recursive"
        assert pins_indirect.get(child_cid) == "indirect"
        assert len(pins_direct) == 0

        assert pins_all.get(root_cid) == "recursive"
        assert pins_all.get(child_cid) == "indirect"

        # 4. Add a direct pin
        direct_cid = await peer.add_node({"data": "direct"})
        await peer.add_pin(direct_cid, recursive=False)

        pins_direct2 = await peer.list_pins("direct")
        assert pins_direct2.get(direct_cid) == "direct"
    finally:
        await peer.close()


@pytest.mark.trio
async def test_atomic_save():
    import json
    from pathlib import Path

    from py_ipfs_lite.pin import PinStore

    with tempfile.TemporaryDirectory() as tmpdir:
        pin_file = Path(tmpdir) / "pins.json"
        store = PinStore(str(pin_file))

        # Add a pin to trigger a save
        store.add_pin(
            "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi", "recursive"
        )

        # Check that the .tmp file doesn't exist anymore, meaning the swap was successful
        tmp_file = pin_file.with_suffix(".tmp")
        assert not tmp_file.exists()

        # Check that the target file does exist and has correct contents
        assert pin_file.exists()
        with open(pin_file) as f:
            data = json.load(f)
            assert (
                "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
                in data["pins"]
            )
