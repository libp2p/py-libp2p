Bound multistream-select message reads to 64 KiB to prevent pre-authentication
memory exhaustion from oversized varint length prefixes during protocol negotiation (`GHSA-hmjq-g7pp-rw3x <https://github.com/libp2p/py-libp2p/security/advisories/GHSA-hmjq-g7pp-rw3x>`__).
