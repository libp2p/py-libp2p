Release Notes
=============

.. towncrier release notes start

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
