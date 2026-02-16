BREAKING CHANGE: CIDv1 Codec Varint Encoding
============================================

Summary
-------

CIDv1 now uses proper **varint encoding** for codec values, as specified in the
`multicodec specification <https://github.com/multiformats/multicodec>`_. This
changes the binary format for CIDs using codecs with values :math:`\ge 128`.

Impact
------

- **95% of CIDs unaffected**: Common codecs (``raw``, ``dag-pb``, ``dag-cbor``)
  use values ``< 128``, which encode identically in both the legacy
  single-byte and the new varint formats.
- **5% of CIDs affected**: Codecs such as ``dag-jose`` (``0x85``),
  ``dag-json`` (``0x129``), and other experimental codecs with values
  :math:`\ge 128` now use multi-byte varint encoding. Their CIDv1 byte layout
  changes and thus their CID *identities* change.

Migration Required
------------------

If you use ``dag-jose``, ``dag-json``, or custom codecs :math:`\ge 128`:

1. **Identify affected CIDs** using ``detect_cid_encoding_format()`` (in ``libp2p.bitswap.cid``).
2. **Recompute CIDs** from original data using ``recompute_cid_from_data()`` (in ``libp2p.bitswap.cid``).
3. **Update storage** (databases, caches, indexes) with the new CIDs.

Code Examples
-------------

Check if your CIDs are affected
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   from libp2p.bitswap.cid import detect_cid_encoding_format

   info = detect_cid_encoding_format(your_cid)

   if info["is_breaking"]:
       print(f"CID uses {info['codec_name']} and needs migration")

Recompute affected CIDs
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   from libp2p.bitswap.cid import recompute_cid_from_data

   # old_cid: the existing CID
   # original_data: the original data that was hashed
   new_cid = recompute_cid_from_data(old_cid, original_data)

Backward Compatibility
----------------------

Code continues to accept integer codec values for API compatibility:

.. code-block:: python

   from libp2p.bitswap.cid import CODEC_RAW, compute_cid_v1

   data = b"example"

   # All of these work:
   cid1 = compute_cid_v1(data, codec=0x55)      # int
   cid2 = compute_cid_v1(data, codec="raw")     # str
   cid3 = compute_cid_v1(data, codec=CODEC_RAW) # Code object
