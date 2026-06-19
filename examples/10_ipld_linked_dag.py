import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    print("=== Example 10: Linked IPLD DAG Knowledge Graph ===")
    
    # We use memory blockstore for a fast, isolated example
    peer = Peer(
        Config(
            reprovide_interval_seconds=-1,
            blockstore_type="memory"
        ), 
        listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )
    await peer.start()

    print("\nBuilding IPLD Knowledge Graph...")
    
    # Bottom of DAG — leaf nodes
    dataset_cid = await peer.add_node({"name": "wikitext-103", "size_gb": 1.8, "sha256": "abc..."}, codec="dag-cbor")
    print(f"1. Dataset node added: {dataset_cid}")
    
    checkpoint_cid = await peer.add_node({"epoch": 42, "loss": 0.031, "dataset": {"/": dataset_cid}}, codec="dag-cbor")
    print(f"2. Checkpoint node added: {checkpoint_cid}")
    
    model_cid = await peer.add_node({"arch": "transformer", "params": "7B", "checkpoint": {"/": checkpoint_cid}}, codec="dag-cbor")
    print(f"3. Model node added: {model_cid}")
    
    agent_cid = await peer.add_node({"id": "summarizer-v2", "model": {"/": model_cid}, "version": "2.1.0"}, codec="dag-cbor")
    print(f"4. Agent node added (Root): {agent_cid}")

    print(f"\nAgent root CID: {agent_cid}")
    
    print("\nNow traversing the graph by following CID links...")
    # Traverse the graph — fetch agent, follow links
    agent = await peer.get_node(agent_cid)
    print(f"  → Agent: {agent['id']} (v{agent['version']})")
    
    model = await peer.get_node(agent["model"]["/"])
    print(f"  → Model: {model['arch']} ({model['params']})")
    
    ckpt = await peer.get_node(model["checkpoint"]["/"])
    print(f"  → Checkpoint: epoch {ckpt['epoch']} (loss {ckpt['loss']})")
    
    dataset = await peer.get_node(ckpt["dataset"]["/"])
    print(f"  → Dataset: {dataset['name']} ({dataset['size_gb']} GB)")
    
    print(f"\n✓ Successfully traversed 4-hop DAG: agent → model → checkpoint → dataset")

    await peer.close()

if __name__ == "__main__":
    trio.run(main)
