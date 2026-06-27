import trio

from py_ipfs_lite.config import Config
from py_ipfs_lite.peer import Peer


async def main():
    print("=== Example 14: Multi-Peer Distributed RAG Pipeline ===")

    # We use memory blockstore for a fast, isolated example
    # Indexer — stores document chunks
    print("\n--- Starting Indexer Peer ---")
    indexer = Peer(
        Config(reprovide_interval_seconds=-1, blockstore_type="memory"),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"],
    )
    await indexer.start()

    documents = [
        "IPFS is a distributed file system that seeks to connect all computing devices...",
        "Filecoin is a decentralized storage network built on IPFS with economic incentives...",
        "libp2p is a modular networking framework used in IPFS, Ethereum 2.0, and Polkadot...",
    ]

    # Store each chunk and build an index node
    print("Indexing documents into IPLD...")
    chunk_links = []
    for i, doc in enumerate(documents):
        chunk_cid = await indexer.add_node(
            {"text": doc, "source": f"doc-{i}"}, codec="dag-cbor"
        )
        chunk_links.append({"/": chunk_cid})
        print(f"  Indexed chunk {i} -> CID: {chunk_cid}")

    index_cid = await indexer.add_node(
        {"type": "rag-index", "chunks": chunk_links}, codec="dag-cbor"
    )
    print(f"\nIndexed {len(documents)} chunks. Root Index CID: {index_cid}")

    # Retriever — fetches index, simulates relevance scoring
    print("\n--- Starting Retriever Peer ---")
    retriever = Peer(
        Config(reprovide_interval_seconds=-1, blockstore_type="memory"),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"],
    )
    await retriever.start()

    indexer_addr = str(indexer.host.addrs()[0])

    print(f"Fetching Index CID from Indexer at {indexer_addr}...")
    index = await retriever.get_node(index_cid, provider_addr=indexer_addr)

    query = "How does Filecoin relate to IPFS?"
    print(f"\nExecuting Query: '{query}'")

    results = []
    # Fetch chunks from indexer
    for chunk_link in index["chunks"]:
        chunk = await retriever.get_node(chunk_link["/"], provider_addr=indexer_addr)
        # Simple term frequency relevance scoring
        score = sum(
            w in chunk["text"].lower() for w in query.lower().replace("?", "").split()
        )
        results.append((score, chunk["text"], chunk_link["/"]))

    results.sort(reverse=True, key=lambda x: x[0])

    context = "\n".join(text for _, text, _ in results[:2])
    print("\nRAG Context Assembled (Top 2 chunks):")
    print("-" * 50)
    print(context)
    print("-" * 50)
    print(f"Context CID refs: {[cid[:20] + '...' for _, _, cid in results[:2]]}")

    await retriever.close()
    await indexer.close()


if __name__ == "__main__":
    trio.run(main)
