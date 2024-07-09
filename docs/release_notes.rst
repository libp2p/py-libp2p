Release Notes
=============

.. towncrier release notes start

py-libp2p v0.2.0 (2024-07-09)
-----------------------------

Breaking Changes
~~~~~~~~~~~~~~~~

- Drop support for ``python<3.8`` (`#447 <https://github.com/ethereum/py-libp2p/issues/447>`__)
- Drop dep for unmaintained ``async-service`` and copy relevant functions into a local tool of the same name (`#467 <https://github.com/ethereum/py-libp2p/issues/467>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- Move contributing and history info from README to docs (`#454 <https://github.com/ethereum/py-libp2p/issues/454>`__)
- Display example usage and full code in docs (`#466 <https://github.com/ethereum/py-libp2p/issues/466>`__)


Features
~~~~~~~~

- Add basic support for ``python3.8, 3.9, 3.10, 3.11, 3.12`` (`#447 <https://github.com/ethereum/py-libp2p/issues/447>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Merge updates from ethereum python project template, including using ``pre-commit`` for linting, change name of ``master`` branch to ``main``, lots of linting changes (`#447 <https://github.com/ethereum/py-libp2p/issues/447>`__)
- Fix docs CI, drop ``bumpversion`` for ``bump-my-version``, reorg tests (`#454 <https://github.com/ethereum/py-libp2p/issues/454>`__)
- Turn ``mypy`` checks on and remove ``async_generator`` dependency (`#464 <https://github.com/ethereum/py-libp2p/issues/464>`__)
- Convert ``KeyType`` enum to use ``protobuf.KeyType`` options rather than ints, rebuild protobufs to include ``ECC_P256`` (`#465 <https://github.com/ethereum/py-libp2p/issues/465>`__)
- Bump to ``mypy==1.10.0``, run ``pre-commit`` local hook instead of ``mirrors-mypy`` (`#472 <https://github.com/ethereum/py-libp2p/issues/472>`__)
- Bump ``protobufs`` dep to ``>=5.27.2`` and rebuild protobuf definition with ``protoc==27.2`` (`#473 <https://github.com/ethereum/py-libp2p/issues/473>`__)


Removals
~~~~~~~~

- Drop ``async-exit-stack`` dep, as of py37 can import ``AsyncExitStack`` from contextlib, also open ``pynacl`` dep to bottom pin only (`#468 <https://github.com/ethereum/py-libp2p/issues/468>`__)


libp2p v0.1.5 (2020-03-25)
---------------------------

Features
~~~~~~~~

- Dial all multiaddrs stored for a peer when attempting to connect (not just the first one in the peer store). (`#386 <https://github.com/libp2p/py-libp2p/issues/386>`__)
- Migrate transport stack to trio-compatible code. Merge in #404. (`#396 <https://github.com/libp2p/py-libp2p/issues/396>`__)
- Migrate network stack to trio-compatible code. Merge in #404. (`#397 <https://github.com/libp2p/py-libp2p/issues/397>`__)
- Migrate host, peer and protocols stacks to trio-compatible code. Merge in #404. (`#398 <https://github.com/libp2p/py-libp2p/issues/398>`__)
- Migrate muxer and security transport stacks to trio-compatible code. Merge in #404. (`#399 <https://github.com/libp2p/py-libp2p/issues/399>`__)
- Migrate pubsub stack to trio-compatible code. Merge in #404. (`#400 <https://github.com/libp2p/py-libp2p/issues/400>`__)
- Fix interop tests w/ new trio-style code. Merge in #404. (`#401 <https://github.com/libp2p/py-libp2p/issues/401>`__)
- Fix remainder of test code w/ new trio-style code. Merge in #404. (`#402 <https://github.com/libp2p/py-libp2p/issues/402>`__)
- Add initial infrastructure for `noise` security transport. (`#405 <https://github.com/libp2p/py-libp2p/issues/405>`__)
- Add `PatternXX` of `noise` security transport. (`#406 <https://github.com/libp2p/py-libp2p/issues/406>`__)
- The `msg_id` in a pubsub message is now configurable by the user of the library. (`#410 <https://github.com/libp2p/py-libp2p/issues/410>`__)


Bugfixes
~~~~~~~~

- Use `sha256` when calculating a peer's ID from their public key in Kademlia DHTs. (`#385 <https://github.com/libp2p/py-libp2p/issues/385>`__)
- Store peer ids in ``set`` instead of ``list`` and check if peer id exists in ``dict`` before accessing to prevent ``KeyError``. (`#387 <https://github.com/libp2p/py-libp2p/issues/387>`__)
- Do not close a connection if it has been reset. (`#394 <https://github.com/libp2p/py-libp2p/issues/394>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Add support for `fastecdsa` on windows (and thereby supporting windows installation via `pip`) (`#380 <https://github.com/libp2p/py-libp2p/issues/380>`__)
- Prefer f-string style formatting everywhere except logging statements. (`#389 <https://github.com/libp2p/py-libp2p/issues/389>`__)
- Mark `lru` dependency as third-party to fix a windows inconsistency. (`#392 <https://github.com/libp2p/py-libp2p/issues/392>`__)
- Bump `multiaddr` dependency to version `0.0.9` so that multiaddr objects are hashable. (`#393 <https://github.com/libp2p/py-libp2p/issues/393>`__)
- Remove incremental mode of mypy to disable some warnings. (`#403 <https://github.com/libp2p/py-libp2p/issues/403>`__)


libp2p v0.1.4 (2019-12-12)
--------------------------

Features
~~~~~~~~

- Added support for Python 3.6 (`#372 <https://github.com/libp2p/py-libp2p/issues/372>`__)
- Add signing and verification to pubsub (`#362 <https://github.com/libp2p/py-libp2p/issues/362>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Refactor and cleanup gossipsub (`#373 <https://github.com/libp2p/py-libp2p/issues/373>`__)


libp2p v0.1.3 (2019-11-27)
--------------------------

Bugfixes
~~~~~~~~

- Handle Stream* errors (like ``StreamClosed``) during calls to ``stream.write()`` and
  ``stream.read()`` (`#350 <https://github.com/libp2p/py-libp2p/issues/350>`__)
- Relax the protobuf dependency to play nicely with other libraries. It was pinned to 3.9.0, and now
  permits v3.10 up to (but not including) v4. (`#354 <https://github.com/libp2p/py-libp2p/issues/354>`__)
- Fixes KeyError when peer in a stream accidentally closes and resets the stream, because handlers
  for both will try to ``del streams[stream_id]`` without checking if the entry still exists. (`#355 <https://github.com/libp2p/py-libp2p/issues/355>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- Use Sphinx & autodoc to generate docs, now available on `py-libp2p.readthedocs.io <https://py-libp2p.readthedocs.io>`_ (`#318 <https://github.com/libp2p/py-libp2p/issues/318>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Added Makefile target to test a packaged version of libp2p before release. (`#353 <https://github.com/libp2p/py-libp2p/issues/353>`__)
- Move helper tools from ``tests/`` to ``libp2p/tools/``, and some mildly-related cleanups. (`#356 <https://github.com/libp2p/py-libp2p/issues/356>`__)


Miscellaneous changes
~~~~~~~~~~~~~~~~~~~~~

- `#357 <https://github.com/libp2p/py-libp2p/issues/357>`__


v0.1.2
--------------

Welcome to the great beyond, where changes were not tracked by release...
