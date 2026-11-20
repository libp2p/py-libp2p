# Records / IPNS — Name-Format & Validator-Registration Issues

## Summary

The IPNS validator (`libp2p/records/ipns.py`) rejects base58btc peer-ID names in `/ipns/` keys (the format used by go-ipfs and py-ipfs-lite), accepting only the hex-multihash form. Additionally, the `ipns` namespace validator is never registered by default, so IPNS records are silently accepted without validation.

## Issues

- **base58 names rejected**: `/ipns/<base58-peer-id>` keys fail validation; only hex-encoded multihash names are accepted.
- **`ipns` validator not registered by default**: The default validator set only registers `pk`; `ipns` records are silently accepted without validation (implicit acceptance).

## Environment

- py-libp2p version: latest main branch
- Python version: 3.12+
- OS: macOS/Linux
