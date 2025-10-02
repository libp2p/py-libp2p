Release Notes
=============

.. towncrier release notes start

py-libp2p v0.3.0 (2025-09-25)
-----------------------------

Breaking Changes
~~~~~~~~~~~~~~~~

- identify protocol use now prefix-length messages by default. use use_varint_format param for old raw messages (`#761 <https://github.com/libp2p/py-libp2p/issues/761>`__)


Bugfixes
~~~~~~~~

- Improved type safety in `get_mux()` and `get_protocols()` by returning properly typed values instead
  of `Any`. Also updated `identify.py` and `discovery.py` to handle `None` values safely and
  compare protocols correctly. (`#746 <https://github.com/libp2p/py-libp2p/issues/746>`__)
- fixed malformed PeerId in test_peerinfo (`#757 <https://github.com/libp2p/py-libp2p/issues/757>`__)
- Fixed incorrect handling of raw protobuf format in identify protocol. The identify example now properly handles both raw and length-prefixed (varint) message formats, provides better error messages, and displays connection status with peer IDs. Replaced mock-based tests with comprehensive real network integration tests for both formats. (`#778 <https://github.com/libp2p/py-libp2p/issues/778>`__)
- Fixed incorrect handling of raw protobuf format in identify push protocol. The identify push example now properly handles both raw and length-prefixed (varint) message formats, provides better error messages, and displays connection status with peer IDs. Replaced mock-based tests with comprehensive real network integration tests for both formats. (`#784 <https://github.com/libp2p/py-libp2p/issues/784>`__)
- Recompiled protobufs that were out of date and added a `make` rule so that protobufs are always up to date. (`#818 <https://github.com/libp2p/py-libp2p/issues/818>`__)
- Added multiselect type consistency in negotiate method. Updates all the usages of the method. (`#837 <https://github.com/libp2p/py-libp2p/issues/837>`__)
- Fixed message id type inconsistency in handle ihave and message id parsing improvement in handle iwant in pubsub module. (`#843 <https://github.com/libp2p/py-libp2p/issues/843>`__)
- Fix kbucket splitting in routing table when full. Routing table now maintains multiple kbuckets and properly distributes peers as specified by the Kademlia DHT protocol. (`#846 <https://github.com/libp2p/py-libp2p/issues/846>`__)
- Fix multi-address listening bug in swarm.listen()

  - Fix early return in swarm.listen() that prevented listening on all addresses
  - Add comprehensive tests for multi-address listening functionality
  - Ensure all available interfaces are properly bound and connectable (`#863 <https://github.com/libp2p/py-libp2p/issues/863>`__)
- Fixed cross-platform path handling by replacing hardcoded OS-specific
  paths with standardized utilities in core modules and examples. (`#886 <https://github.com/libp2p/py-libp2p/issues/886>`__)
- Exposed timeout method in muxer multistream and updated all the usage. Added testcases to verify that timeout value is passed correctly (`#896 <https://github.com/libp2p/py-libp2p/issues/896>`__)
- enhancement: Add write lock to `YamuxStream` to prevent concurrent write race conditions

  - Implements ReadWriteLock for `YamuxStream` write operations
  - Prevents data corruption from concurrent write operations
  - Read operations remain lock-free due to existing `Yamux` architecture
  - Resolves race conditions identified in Issue #793 (`#897 <https://github.com/libp2p/py-libp2p/issues/897>`__)
- Fix multiaddr dependency to use the last py-multiaddr commit hash to resolve installation issues (`#927 <https://github.com/libp2p/py-libp2p/issues/927>`__)
- Fixed Windows CI/CD tests to use correct Python version instead of hardcoded Python 3.11. test 2 (`#952 <https://github.com/libp2p/py-libp2p/issues/952>`__)
- Fix flaky test_find_node in kad_dht by eliminating race conditions and adding retry mechanism

  - Enhanced dht_pair fixture to force peer discovery during setup, eliminating async race conditions
  - Added retry mechanism with proper type annotations for additional resilience
  - Added pytest-rerunfailures dependency and flaky test marker
  - Resolves intermittent CI failures in tests/core/kad_dht/test_kad_dht.py::test_find_node (`#956 <https://github.com/libp2p/py-libp2p/issues/956>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- Improve error message under the function decode_uvarint_from_stream in libp2p/utils/varint.py file (`#760 <https://github.com/libp2p/py-libp2p/issues/760>`__)
- Clarified the requirement for a trailing newline in newsfragments to pass lint checks. (`#775 <https://github.com/libp2p/py-libp2p/issues/775>`__)


Features
~~~~~~~~

- Added experimental WebSocket transport support with basic WS and WSS functionality. This includes:

  - WebSocket transport implementation with trio-websocket backend
  - Support for both WS (WebSocket) and WSS (WebSocket Secure) protocols
  - Basic connection management and stream handling
  - TLS configuration support for WSS connections
  - Multiaddr parsing for WebSocket addresses
  - Integration with libp2p host and peer discovery

  **Note**: This is experimental functionality. Advanced features like proxy support,
  interop testing, and production examples are still in development. See
  https://github.com/libp2p/py-libp2p/discussions/937 for the complete roadmap of missing features. (`#585 <https://github.com/libp2p/py-libp2p/issues/585>`__)
- Added `Bootstrap` peer discovery module that allows nodes to connect to predefined bootstrap peers for network discovery. (`#711 <https://github.com/libp2p/py-libp2p/issues/711>`__)
- Add lock for read/write to avoid interleaving receiving messages in mplex_stream.py (`#748 <https://github.com/libp2p/py-libp2p/issues/748>`__)
- Add logic to clear_peerdata method in peerstore (`#750 <https://github.com/libp2p/py-libp2p/issues/750>`__)
- Added the `Certified Addr-Book` interface supported by `Envelope` and `PeerRecord` class.
  Integrated the signed-peer-record transfer in the identify/push protocols. (`#753 <https://github.com/libp2p/py-libp2p/issues/753>`__)
- add length-prefixed support to identify protocol (`#761 <https://github.com/libp2p/py-libp2p/issues/761>`__)
- Add QUIC transport support for faster, more efficient peer-to-peer connections with native stream multiplexing. (`#763 <https://github.com/libp2p/py-libp2p/issues/763>`__)
- Added Thin Waist address validation utilities (with support for interface enumeration, optimal binding, and wildcard expansion). (`#811 <https://github.com/libp2p/py-libp2p/issues/811>`__)
- KAD-DHT now include signed-peer-records in its protobuf message schema, for more secure peer-discovery. (`#815 <https://github.com/libp2p/py-libp2p/issues/815>`__)
- Added `Random Walk` peer discovery module that enables random peer exploration for improved peer discovery. (`#822 <https://github.com/libp2p/py-libp2p/issues/822>`__)
- Implement closed_stream notification in MyNotifee

  - Add notify_closed_stream method to swarm notification system for proper stream lifecycle management
  - Integrate remove_stream hook in SwarmConn to enable stream closure notifications
  - Add comprehensive tests for closed_stream functionality in test_notify.py
  - Enable stream lifecycle integration for proper cleanup and resource management (`#826 <https://github.com/libp2p/py-libp2p/issues/826>`__)
- Add automatic peer dialing in bootstrap module using trio.Nursery. (`#849 <https://github.com/libp2p/py-libp2p/issues/849>`__)
- Fix type for gossipsub_message_id for consistency and security (`#859 <https://github.com/libp2p/py-libp2p/issues/859>`__)
- Enhanced Swarm networking with retry logic, exponential backoff, and multi-connection support. Added configurable retry mechanisms that automatically recover from transient connection failures using exponential backoff with jitter to prevent thundering herd problems. Introduced connection pooling that allows multiple concurrent connections per peer for improved performance and fault tolerance. Added load balancing across connections and automatic connection health management. All enhancements are fully backward compatible and can be configured through new RetryConfig and ConnectionConfig classes. (`#874 <https://github.com/libp2p/py-libp2p/issues/874>`__)
- Updated all example scripts and core modules to use secure loopback addresses instead of wildcard addresses for network binding.
  The `get_wildcard_address` function and related logic now utilize all available interfaces safely, improving security and consistency across the codebase. (`#885 <https://github.com/libp2p/py-libp2p/issues/885>`__)
- PubSub routers now include signed-peer-records in RPC messages for secure peer-info exchange. (`#889 <https://github.com/libp2p/py-libp2p/issues/889>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- remove FIXME comment since it's obsolete and 32-byte prefix support is there but not enabled by default (`#592 <https://github.com/libp2p/py-libp2p/issues/592>`__)
- Add comprehensive tests for relay_discovery method in circuit_relay_v2 (`#749 <https://github.com/libp2p/py-libp2p/issues/749>`__)
- [mplex] Add timeout and error handling during stream close (`#752 <https://github.com/libp2p/py-libp2p/issues/752>`__)
- fixed a typecheck error using cast in peerinfo.py (`#757 <https://github.com/libp2p/py-libp2p/issues/757>`__)
- Fix raw format reading in identify/push protocol and add comprehensive test coverage for both varint and raw formats (`#761 <https://github.com/libp2p/py-libp2p/issues/761>`__)
- Pin py-multiaddr dependency to specific git commit db8124e2321f316d3b7d2733c7df11d6ad9c03e6 (`#766 <https://github.com/libp2p/py-libp2p/issues/766>`__)
- Make TProtocol as Optional[TProtocol] to keep types consistent in py-libp2p/libp2p/protocol_muxer/multiselect.py (`#770 <https://github.com/libp2p/py-libp2p/issues/770>`__)
- Replace the libp2p.peer.ID cache attributes with functools.cached_property functional decorator. (`#772 <https://github.com/libp2p/py-libp2p/issues/772>`__)
- Yamux RawConnError Logging Refactor - Improved error handling and debug logging (`#784 <https://github.com/libp2p/py-libp2p/issues/784>`__)
- Add Thin Waist address validation utilities and integrate into echo example

  - Add ``libp2p/utils/address_validation.py`` with dynamic interface discovery
  - Implement ``get_available_interfaces()``, ``get_optimal_binding_address()``, and ``expand_wildcard_address()``
  - Update echo example to use dynamic address discovery instead of hardcoded wildcard
  - Add safe fallbacks for environments lacking Thin Waist support
  - Temporarily disable IPv6 support due to libp2p handshake issues (TODO: re-enable when resolved) (`#811 <https://github.com/libp2p/py-libp2p/issues/811>`__)
- The TODO IK patterns in Noise has been deprecated in specs: https://github.com/libp2p/specs/tree/master/noise#handshake-pattern (`#816 <https://github.com/libp2p/py-libp2p/issues/816>`__)
- Remove the already completed TODO tasks in Peerstore:
  TODO: Set up an async task for periodic peer-store cleanup for expired addresses and records.
  TODO: Make proper use of this function (`#819 <https://github.com/libp2p/py-libp2p/issues/819>`__)
- Improved PubsubNotifee integration tests and added failure scenario coverage. (`#855 <https://github.com/libp2p/py-libp2p/issues/855>`__)
- Remove unused upgrade_listener function from transport upgrader

  - Remove unused `upgrade_listener` function from `libp2p/transport/upgrader.py` (Issue 2 from #726)
  - Clean up unused imports related to the removed function
  - Improve code maintainability by removing dead code (`#883 <https://github.com/libp2p/py-libp2p/issues/883>`__)
- Replace magic numbers with named constants and enums for clarity and maintainability

  **Key Changes:**
  - **Introduced type-safe enums** for better code clarity:
  - `RelayRole(Flag)` enum with HOP, STOP, CLIENT roles supporting bitwise combinations (e.g., `RelayRole.HOP | RelayRole.STOP`)
  - `ReservationStatus(Enum)` for reservation lifecycle management (ACTIVE, EXPIRED, REJECTED)
  - **Replaced magic numbers with named constants** throughout the codebase, improving code maintainability and eliminating hardcoded timeout values (15s, 30s, 10s) with descriptive constant names
  - **Added comprehensive timeout configuration system** with new `TimeoutConfig` dataclass supporting component-specific timeouts (discovery, protocol, DCUtR)
  - **Enhanced configurability** of `RelayDiscovery`, `CircuitV2Protocol`, and `DCUtRProtocol` constructors with optional timeout parameters
  - **Improved architecture consistency** with clean configuration flow across all circuit relay components
  - **Backward Compatibility:** All changes maintain full backward compatibility. Existing code continues to work unchanged while new timeout configuration options are available for users who need them. (`#917 <https://github.com/libp2p/py-libp2p/issues/917>`__)


Miscellaneous Changes
~~~~~~~~~~~~~~~~~~~~~

- `#934 <https://github.com/libp2p/py-libp2p/issues/934>`__


Performance Improvements
~~~~~~~~~~~~~~~~~~~~~~~~

- Added throttling for async topic validators in validate_msg, enforcing a
  concurrency limit to prevent resource exhaustion under heavy load. (`#755 <https://github.com/libp2p/py-libp2p/issues/755>`__)


py-libp2p v0.2.9 (2025-07-09)
-----------------------------

Breaking Changes
~~~~~~~~~~~~~~~~

- Reordered the arguments to ``upgrade_security`` to place ``is_initiator`` before ``peer_id``, and made ``peer_id`` optional.
  This allows the method to reflect the fact that peer identity is not required for inbound connections. (`#681 <https://github.com/libp2p/py-libp2p/issues/681>`__)


Bugfixes
~~~~~~~~

- Add timeout wrappers in:
  1. ``multiselect.py``: ``negotiate`` function
  2. ``multiselect_client.py``: ``select_one_of`` , ``query_multistream_command`` functions
  to prevent indefinite hangs when a remote peer does not respond. (`#696 <https://github.com/libp2p/py-libp2p/issues/696>`__)
- Align stream creation logic with yamux specification (`#701 <https://github.com/libp2p/py-libp2p/issues/701>`__)
- Fixed an issue in ``Pubsub`` where async validators were not handled reliably under concurrency. Now uses a safe aggregator list for consistent behavior. (`#702 <https://github.com/libp2p/py-libp2p/issues/702>`__)


Features
~~~~~~~~

- Added support for ``Kademlia DHT`` in py-libp2p. (`#579 <https://github.com/libp2p/py-libp2p/issues/579>`__)
- Limit concurrency in ``push_identify_to_peers`` to prevent resource congestion under high peer counts. (`#621 <https://github.com/libp2p/py-libp2p/issues/621>`__)
- Store public key and peer ID in peerstore during handshake

  Modified the InsecureTransport class to accept an optional peerstore parameter and updated the handshake process to store the received public key and peer ID in the peerstore when available.

  Added test cases to verify:
  1. The peerstore remains unchanged when handshake fails due to peer ID mismatch
  2. The handshake correctly adds a public key to a peer ID that already exists in the peerstore but doesn't have a public key yet (`#631 <https://github.com/libp2p/py-libp2p/issues/631>`__)
- Fixed several flow-control and concurrency issues in the ``YamuxStream`` class. Previously, stress-testing revealed that transferring data over ``DEFAULT_WINDOW_SIZE`` would break the stream due to inconsistent window update handling and lock management. The fixes include:

  - Removed sending of window updates during writes to maintain correct flow-control.
  - Added proper timeout handling when releasing and acquiring locks to prevent concurrency errors.
  - Corrected the ``read`` function to properly handle window updates for both ``read_until_EOF`` and ``read_n_bytes``.
  - Added event logging at ``send_window_updates`` and ``waiting_for_window_updates`` for better observability. (`#639 <https://github.com/libp2p/py-libp2p/issues/639>`__)
- Added support for ``Multicast DNS`` in py-libp2p (`#649 <https://github.com/libp2p/py-libp2p/issues/649>`__)
- Optimized pubsub publishing to send multiple topics in a single message instead of separate messages per topic. (`#685 <https://github.com/libp2p/py-libp2p/issues/685>`__)
- Optimized pubsub message writing by implementing a write_msg() method that uses pre-allocated buffers and single write operations, improving performance by eliminating separate varint prefix encoding and write operations in FloodSub and GossipSub. (`#687 <https://github.com/libp2p/py-libp2p/issues/687>`__)
- Added peer exchange and backoff logic as part of Gossipsub v1.1 upgrade (`#690 <https://github.com/libp2p/py-libp2p/issues/690>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Added sparse connect utility function to pubsub test utilities for creating test networks with configurable connectivity. (`#679 <https://github.com/libp2p/py-libp2p/issues/679>`__)
- Added comprehensive tests for pubsub connection utility functions to verify degree limits are enforced, excess peers are handled correctly, and edge cases (degree=0, negative values, empty lists) are managed gracefully. (`#707 <https://github.com/libp2p/py-libp2p/issues/707>`__)
- Added extra tests for identify push concurrency cap under high peer load (`#708 <https://github.com/libp2p/py-libp2p/issues/708>`__)


Miscellaneous Changes
~~~~~~~~~~~~~~~~~~~~~

- `#678 <https://github.com/libp2p/py-libp2p/issues/678>`__, `#684 <https://github.com/libp2p/py-libp2p/issues/684>`__


py-libp2p v0.2.8 (2025-06-10)
-----------------------------

Breaking Changes
~~~~~~~~~~~~~~~~

- The `NetStream.state` property is now async and requires `await`. Update any direct state access to use `await stream.state`. (`#300 <https://github.com/libp2p/py-libp2p/issues/300>`__)


Bugfixes
~~~~~~~~

- Added proper state management and resource cleanup to `NetStream`, fixing memory leaks and improved error handling. (`#300 <https://github.com/libp2p/py-libp2p/issues/300>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- Updated examples to automatically use random port, when `-p` flag is not given (`#661 <https://github.com/libp2p/py-libp2p/issues/661>`__)


Features
~~~~~~~~

- Allow passing `listen_addrs` to `new_swarm` to customize swarm listening behavior. (`#616 <https://github.com/libp2p/py-libp2p/issues/616>`__)
- Feature: Support for sending `ls` command over `multistream-select` to list supported protocols from remote peer.
  This allows inspecting which protocol handlers a peer supports at runtime. (`#622 <https://github.com/libp2p/py-libp2p/issues/622>`__)
- implement AsyncContextManager for IMuxedStream to support async with (`#629 <https://github.com/libp2p/py-libp2p/issues/629>`__)
- feat: add method to compute time since last message published by a peer and remove fanout peers based on ttl. (`#636 <https://github.com/libp2p/py-libp2p/issues/636>`__)
- implement blacklist management for `pubsub.Pubsub` with methods to get, add, remove, check, and clear blacklisted peer IDs. (`#641 <https://github.com/libp2p/py-libp2p/issues/641>`__)
- fix: remove expired peers from peerstore based on TTL (`#650 <https://github.com/libp2p/py-libp2p/issues/650>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Modernizes several aspects of the project, notably using ``pyproject.toml`` for project info instead of ``setup.py``, using ``ruff`` to replace several separate linting tools, and ``pyrefly`` in addition to ``mypy`` for typing. Also includes changes across the codebase to conform to new linting and typing rules. (`#618 <https://github.com/libp2p/py-libp2p/issues/618>`__)


Removals
~~~~~~~~

- Removes support for python 3.9 and updates some code conventions, notably using ``|`` operator in typing instead of ``Optional`` or ``Union`` (`#618 <https://github.com/libp2p/py-libp2p/issues/618>`__)


py-libp2p v0.2.7 (2025-05-22)
-----------------------------

Bugfixes
~~~~~~~~

- ``handler()`` inside ``TCPListener.listen()`` does not catch exceptions thrown during handshaking steps (from ``Sawrm``).
  These innocuous exceptions will become fatal and crash the process if not handled. (`#586 <https://github.com/libp2p/py-libp2p/issues/586>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- Fixed the `contributing.rst` file to include the Libp2p Discord Server Link. (`#592 <https://github.com/libp2p/py-libp2p/issues/592>`__)


Features
~~~~~~~~

- Added support for the Yamux stream multiplexer (/yamux/1.0.0) as the preferred option, retaining Mplex (/mplex/6.7.0) for backward compatibility. (`#534 <https://github.com/libp2p/py-libp2p/issues/534>`__)
- added ``direct peers`` as part of gossipsub v1.1 upgrade. (`#594 <https://github.com/libp2p/py-libp2p/issues/594>`__)
- Feature: Logging in py-libp2p via env vars (`#608 <https://github.com/libp2p/py-libp2p/issues/608>`__)
- Added support for multiple-error formatting in the `MultiError` class. (`#613 <https://github.com/libp2p/py-libp2p/issues/613>`__)


py-libp2p v0.2.6 (2025-05-12)
-----------------------------

Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- Expand the Introduction section in the documentation with a detailed overview of Py-libp2p. (`#560 <https://github.com/libp2p/py-libp2p/issues/560>`__)


Features
~~~~~~~~

- Added identify-push protocol implementation and examples to demonstrate how peers can proactively push their identity information to other peers when it changes. (`#552 <https://github.com/libp2p/py-libp2p/issues/552>`__)
- Added AutoNAT protocol (`#561 <https://github.com/libp2p/py-libp2p/issues/561>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Bumps dependency to ``protobuf>=6.30.1``. (`#576 <https://github.com/libp2p/py-libp2p/issues/576>`__)
- Removes old interop tests, creates placeholders for new ones, and turns on interop testing in CI. (`#588 <https://github.com/libp2p/py-libp2p/issues/588>`__)


py-libp2p v0.2.5 (2025-04-14)
-----------------------------

Bugfixes
~~~~~~~~

- Fixed flaky test_simple_last_seen_cache by adding a retry loop for reliable expiry detection across platforms. (`#558 <https://github.com/libp2p/py-libp2p/issues/558>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- Added install and getting started documentation. (`#559 <https://github.com/libp2p/py-libp2p/issues/559>`__)


Features
~~~~~~~~

- Added a ``pub-sub`` example having ``gossipsub`` as the router to demonstrate how to use the pub-sub module in py-libp2p. (`#515 <https://github.com/libp2p/py-libp2p/issues/515>`__)
- Added documentation on how to add examples to the libp2p package. (`#550 <https://github.com/libp2p/py-libp2p/issues/550>`__)
- Added Windows-specific development setup instructions to `docs/contributing.rst`. (`#559 <https://github.com/libp2p/py-libp2p/issues/559>`__)


py-libp2p v0.2.4 (2025-03-27)
-----------------------------

Bugfixes
~~~~~~~~

- Added Windows compatibility by using coincurve instead of fastecdsa on Windows platforms (`#507 <https://github.com/libp2p/py-libp2p/issues/507>`__)


py-libp2p v0.2.3 (2025-03-27)
-----------------------------

Bugfixes
~~~~~~~~

- Fixed import path in the examples to use updated `net_stream` module path, resolving ModuleNotFoundError when running the examples. (`#513 <https://github.com/libp2p/py-libp2p/issues/513>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- Updates ``Feature Breakdown`` in ``README`` to more closely match the list of standard modules. (`#498 <https://github.com/libp2p/py-libp2p/issues/498>`__)
- Adds detailed Sphinx-style docstrings to ``abc.py``. (`#535 <https://github.com/libp2p/py-libp2p/issues/535>`__)


Features
~~~~~~~~

- Improved the implementation of the identify protocol and enhanced test coverage to ensure proper functionality and network layer address delegation. (`#358 <https://github.com/libp2p/py-libp2p/issues/358>`__)
- Adds the ability to check connection status of a peer in the peerstore. (`#420 <https://github.com/libp2p/py-libp2p/issues/420>`__)
- implemented ``timed_cache`` module which will allow to implement ``seen_ttl`` configurable param for pubsub and protocols extending it. (`#518 <https://github.com/libp2p/py-libp2p/issues/518>`__)
- Added a maximum RSA key size limit of 4096 bits to prevent resource exhaustion attacks.Consolidated validation logic to use a single error message source and
  added tests to catch invalid key sizes (including negative values). (`#523 <https://github.com/libp2p/py-libp2p/issues/523>`__)
- Added automated testing of ``demo`` applications as part of CI to prevent demos from breaking silently. Tests are located in `tests/core/examples/test_examples.py`. (`#524 <https://github.com/libp2p/py-libp2p/issues/524>`__)
- Added an example implementation of the identify protocol to demonstrate its usage and help users understand how to properly integrate it into their libp2p applications. (`#536 <https://github.com/libp2p/py-libp2p/issues/536>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- moved all interfaces to ``libp2p.abc`` along with all libp2p custom types to ``libp2p.custom_types``. (`#228 <https://github.com/libp2p/py-libp2p/issues/228>`__)
- moved ``libp2p/tools/factories`` to ``tests``. (`#503 <https://github.com/libp2p/py-libp2p/issues/503>`__)
- Fixes broken CI lint run, bumps ``pre-commit-hooks`` version to ``5.0.0`` and ``mdformat`` to ``0.7.22``. (`#522 <https://github.com/libp2p/py-libp2p/issues/522>`__)
- Rebuilds protobufs with ``protoc v30.1``. (`#542 <https://github.com/libp2p/py-libp2p/issues/542>`__)
- Moves ``pubsub`` testing tools from ``libp2p.tools`` and ``factories`` from ``tests`` to ``tests.utils``. (`#543 <https://github.com/libp2p/py-libp2p/issues/543>`__)


py-libp2p v0.2.2 (2025-02-20)
-----------------------------

Bugfixes
~~~~~~~~

- - This fix issue #492 adding a missing break statement that lowers GIL usage from 99% to 0%-2%. (`#492 <https://github.com/libp2p/py-libp2p/issues/492>`__)


Features
~~~~~~~~

- Create entry points for demos to be run directly from installed package (`#490 <https://github.com/libp2p/py-libp2p/issues/490>`__)
- Merge template, adding python 3.13 to CI checks. (`#496 <https://github.com/libp2p/py-libp2p/issues/496>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Drop CI runs for python 3.8, run ``pyupgrade`` to bring code up to python 3.9. (`#497 <https://github.com/libp2p/py-libp2p/issues/497>`__)
- Rename ``typing.py`` to ``custom_types.py`` for clarity. (`#500 <https://github.com/libp2p/py-libp2p/issues/500>`__)


py-libp2p v0.2.1 (2024-12-20)
-----------------------------

Bugfixes
~~~~~~~~

- Added missing check to reject messages claiming to be from ourselves but not locally published in pubsub's ``push_msg`` function (`#413 <https://github.com/libp2p/py-libp2p/issues/413>`__)
- Added missing check in ``add_addrs`` function for duplicate addresses in ``peerdata`` (`#485 <https://github.com/libp2p/py-libp2p/issues/485>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- added missing details of params in ``IPubsubRouter`` (`#486 <https://github.com/libp2p/py-libp2p/issues/486>`__)


Features
~~~~~~~~

- Added ``PingService`` class in ``host/ping.py`` which can be used to initiate ping requests to peers and added tests for the same (`#344 <https://github.com/libp2p/py-libp2p/issues/344>`__)
- Added ``get_connected_peers`` method in class ``IHost`` which can be used to get a list of peer ids of currently connected peers (`#419 <https://github.com/libp2p/py-libp2p/issues/419>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Update ``sphinx_rtd_theme`` options and drop pdf build of docs (`#481 <https://github.com/libp2p/py-libp2p/issues/481>`__)
- Update ``trio`` package version dependency (`#482 <https://github.com/libp2p/py-libp2p/issues/482>`__)


py-libp2p v0.2.0 (2024-07-09)
-----------------------------

Breaking Changes
~~~~~~~~~~~~~~~~

- Drop support for ``python<3.8`` (`#447 <https://github.com/libp2p/py-libp2p/issues/447>`__)
- Drop dep for unmaintained ``async-service`` and copy relevant functions into a local tool of the same name (`#467 <https://github.com/libp2p/py-libp2p/issues/467>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- Move contributing and history info from README to docs (`#454 <https://github.com/libp2p/py-libp2p/issues/454>`__)
- Display example usage and full code in docs (`#466 <https://github.com/libp2p/py-libp2p/issues/466>`__)


Features
~~~~~~~~

- Add basic support for ``python3.8, 3.9, 3.10, 3.11, 3.12`` (`#447 <https://github.com/libp2p/py-libp2p/issues/447>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Merge updates from ethereum python project template, including using ``pre-commit`` for linting, change name of ``master`` branch to ``main``, lots of linting changes (`#447 <https://github.com/libp2p/py-libp2p/issues/447>`__)
- Fix docs CI, drop ``bumpversion`` for ``bump-my-version``, reorg tests (`#454 <https://github.com/libp2p/py-libp2p/issues/454>`__)
- Turn ``mypy`` checks on and remove ``async_generator`` dependency (`#464 <https://github.com/libp2p/py-libp2p/issues/464>`__)
- Convert ``KeyType`` enum to use ``protobuf.KeyType`` options rather than ints, rebuild protobufs to include ``ECC_P256`` (`#465 <https://github.com/libp2p/py-libp2p/issues/465>`__)
- Bump to ``mypy==1.10.0``, run ``pre-commit`` local hook instead of ``mirrors-mypy`` (`#472 <https://github.com/libp2p/py-libp2p/issues/472>`__)
- Bump ``protobufs`` dep to ``>=5.27.2`` and rebuild protobuf definition with ``protoc==27.2`` (`#473 <https://github.com/libp2p/py-libp2p/issues/473>`__)


Removals
~~~~~~~~

- Drop ``async-exit-stack`` dep, as of py37 can import ``AsyncExitStack`` from contextlib, also open ``pynacl`` dep to bottom pin only (`#468 <https://github.com/libp2p/py-libp2p/issues/468>`__)


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
