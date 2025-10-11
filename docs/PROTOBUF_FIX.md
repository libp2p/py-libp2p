# Protobuf Architecture Fix - IPFS Interoperability

## Summary

Fixed the protobuf definitions to match official IPFS/Boxo implementation for interoperability. The code was previously mixing DAG-PB and UnixFS definitions in a single proto file, which broke compatibility with official IPFS implementations.

## Changes Made

### 1. Separated DAG-PB and UnixFS Protobuf Definitions

**Before (BROKEN):**
- Single `dag_pb.proto` file containing both DAG-PB (PBLink, PBNode) AND UnixFS structures
- Extra fields (mode, mtime, UnixTime) that don't exist in official specs
- Syntax "proto3" instead of "proto2"

**After (CORRECT):**
- `dag_pb.proto` - ONLY DAG-PB spec (PBLink, PBNode) matching go-merkledag
- `unixfs.proto` - Separate UnixFS spec (Data, Metadata, IPFSTimestamp) matching go-unixfs
- Both use syntax "proto2" as per official specs

### 2. File Structure

```
libp2p/bitswap/pb/
├── bitswap.proto          ✅ CORRECT (matches ipfs/boxo/bitswap)
├── bitswap_pb2.py         ✅ Generated
├── bitswap_pb2.pyi        ✅ Generated
├── dag_pb.proto           ✅ FIXED (now matches go-merkledag)
├── dag_pb_pb2.py          ✅ Regenerated
├── dag_pb_pb2.pyi         ✅ Regenerated  
├── unixfs.proto           ✨ NEW (matches go-unixfs)
├── unixfs_pb2.py          ✨ Generated
└── unixfs_pb2.pyi         ✨ Generated
```

### 3. Official Proto Files Used

#### dag_pb.proto (from go-merkledag/pb/merkledag.proto)
```protobuf
syntax = "proto2";
package dag_pb;

message PBLink {
    optional bytes Hash = 1;   // CID of target
    optional string Name = 2;  // Link name
    optional uint64 Tsize = 3; // Cumulative size
}

message PBNode {
    repeated PBLink Links = 2; // Links to other blocks
    optional bytes Data = 1;   // Opaque data (UnixFS goes here)
}
```

#### unixfs.proto (from go-unixfs/pb/unixfs.proto)
```protobuf
syntax = "proto2";
package unixfs.pb;

message Data {
    enum DataType {
        Raw = 0;
        Directory = 1;
        File = 2;
        Metadata = 3;
        Symlink = 4;
        HAMTShard = 5;
    }
    
    required DataType Type = 1;
    optional bytes Data = 2;
    optional uint64 filesize = 3;
    repeated uint64 blocksizes = 4;
    optional uint64 hashType = 5;
    optional uint64 fanout = 6;
    optional uint32 mode = 7;
    optional IPFSTimestamp mtime = 8;
}

message IPFSTimestamp {
    required int64 seconds = 1;
    optional fixed32 nanos = 2;
}
```

### 4. Code Changes

**libp2p/bitswap/dag_pb.py:**
```python
# Before:
from .pb.dag_pb_pb2 import (
    PBNode,
    UnixFSData as PBUnixFSData,  # ❌ Didn't exist anymore
)

# After:
from .pb.dag_pb_pb2 import PBNode
from .pb.unixfs_pb2 import Data as PBUnixFSData  # ✅ Correct import
```

## How UnixFS and DAG-PB Work Together

This is the official IPFS architecture:

1. **DAG-PB Layer** (merkledag.proto):
   - Defines the Merkle DAG structure
   - `PBNode` contains links and opaque data
   - This is the IPLD codec layer

2. **UnixFS Layer** (unixfs.proto):  
   - Defines file system semantics
   - UnixFS `Data` message is serialized and stored in `PBNode.Data` field
   - This is the UnixFS layer on top of IPLD

3. **Example Structure**:
   ```
   PBNode {
       Links: [
           PBLink { Hash: <CID of chunk1>, Tsize: 262144 },
           PBLink { Hash: <CID of chunk2>, Tsize: 262144 }
       ],
       Data: <serialized UnixFS Data message>
   }
   
   Where the Data field contains:
   UnixFS Data {
       Type: File,
       filesize: 524288,
       blocksizes: [262144, 262144]
   }
   ```

## Verification

All 67 bitswap tests pass:
```bash
pytest tests/bitswap/ -v
================================ 67 passed, 2 warnings in 0.43s ===========================
```

## Official Sources

- DAG-PB spec: https://ipld.io/specs/codecs/dag-pb/spec/
- go-merkledag proto: https://github.com/ipfs/go-merkledag/blob/master/pb/merkledag.proto
- go-unixfs proto: https://github.com/ipfs/boxo/blob/main/ipld/unixfs/pb/unixfs.proto
- bitswap proto: https://github.com/ipfs/boxo/blob/main/bitswap/message/pb/message.proto

## Next Steps

The protobuf definitions now match official IPFS specs exactly. However, there may still be issues with:

1. **Stream management**: The client needs to keep streams open to receive provider responses
2. **Message exchange protocol**: Need to verify the full bitswap handshake matches go-bitswap
3. **CID encoding**: Verify CID format matches (multibase, multihash, etc.)

These will need separate investigation and fixes.
