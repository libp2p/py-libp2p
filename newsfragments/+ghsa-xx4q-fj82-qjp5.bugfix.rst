Enforce yamux per-stream receive-window limits on incoming DATA frames and
treat window violations as a protocol error that terminates the session, so a
remote peer cannot grow stream buffers without bound
(`GHSA-xx4q-fj82-qjp5 <https://github.com/libp2p/py-libp2p/security/advisories/GHSA-xx4q-fj82-qjp5>`__).
