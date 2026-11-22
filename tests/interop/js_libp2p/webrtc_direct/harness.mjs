// Minimal js-libp2p WebRTC-Direct interop harness for py-libp2p's test suite.
// Same CLI and output contract as tests/interop/go_libp2p/webrtc_direct/main.go.
//
// Modes:
//
//   node harness.mjs listen                 — listen on an OS-chosen UDP port,
//                                             print "LISTEN <multiaddr-with-/p2p/>"
//                                             once per address, then
//                                             "CONNECTED <peer>" for each inbound
//                                             connection.
//   node harness.mjs dial -version N <addr> — dial a /webrtc-direct multiaddr
//                                             speaking WebRTC-Direct vN (1 or 2),
//                                             print "DIAL_OK <peer>" and exit 0.
//
// The listener accepts v1 and v2 regardless of -version.
import { webRTCDirect } from '@libp2p/webrtc'
import { multiaddr } from '@multiformats/multiaddr'
import { createLibp2p } from 'libp2p'

const usage = 'usage: harness.mjs [listen | dial -version N <multiaddr>]'

function fail (err) {
  process.stderr.write(`FAIL ${err?.stack ?? err}\n`)
  process.exit(1)
}

const [mode, ...rest] = process.argv.slice(2)
let version = 1
const positional = []
for (let i = 0; i < rest.length; i++) {
  if (rest[i] === '-version') {
    version = Number(rest[++i])
  } else {
    positional.push(rest[i])
  }
}
if (version !== 1 && version !== 2) {
  fail(new Error(`unknown WebRTC-Direct version ${version}`))
}

try {
  if (mode === 'listen') {
    const node = await createLibp2p({
      addresses: { listen: ['/ip4/0.0.0.0/udp/0/webrtc-direct'] },
      transports: [webRTCDirect()]
    })
    node.addEventListener('connection:open', (evt) => {
      console.log(`CONNECTED ${evt.detail.remotePeer}`)
    })
    await node.start()
    for (const addr of node.getMultiaddrs()) {
      console.log(`LISTEN ${addr}`)
    }
    // Serve until the test kills us.
    process.on('SIGTERM', () => { node.stop().finally(() => process.exit(0)) })
  } else if (mode === 'dial' && positional.length === 1) {
    const node = await createLibp2p({
      transports: [webRTCDirect({ dialerVersion: version })]
    })
    await node.start()
    const conn = await node.dial(multiaddr(positional[0]), {
      signal: AbortSignal.timeout(30_000)
    })
    console.log(`DIAL_OK ${conn.remotePeer}`)
    await node.stop()
    process.exit(0)
  } else {
    fail(new Error(usage))
  }
} catch (err) {
  fail(err)
}
