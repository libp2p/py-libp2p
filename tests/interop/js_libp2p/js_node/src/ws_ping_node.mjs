import { createLibp2p }          from 'libp2p'
import { webSockets }            from '@libp2p/websockets'
import { ping }                  from '@libp2p/ping'
import { noise }                 from '@chainsafe/libp2p-noise'
import { plaintext }             from '@libp2p/plaintext'
import { yamux }                 from '@chainsafe/libp2p-yamux'

// Configuration from environment (with defaults for compatibility)
const TRANSPORT = process.env.transport || 'ws'
const SECURITY = process.env.security || 'noise'
const MUXER = process.env.muxer || 'yamux'
const IP = process.env.ip || '0.0.0.0'

async function main() {
  console.log(`🔧 Configuration: transport=${TRANSPORT}, security=${SECURITY}, muxer=${MUXER}`)

  // Build options following the proven pattern from test-plans-fork
  const options = {
    start: true,
    connectionGater: {
      denyDialMultiaddr: async () => false
    },
    connectionMonitor: {
      enabled: false
    },
    services: {
      ping: ping()
    }
  }

  // Transport configuration (following get-libp2p.ts pattern)
  switch (TRANSPORT) {
    case 'ws':
      options.transports = [webSockets()]
      options.addresses = {
        listen: [`/ip4/${IP}/tcp/0/ws`]
      }
      break
    case 'wss':
      process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0'
      options.transports = [webSockets()]
      options.addresses = {
        listen: [`/ip4/${IP}/tcp/0/wss`]
      }
      break
    default:
      throw new Error(`Unknown transport: ${TRANSPORT}`)
  }

  // Security configuration - use connectionEncrypters (plural) for libp2p v3.x
  switch (SECURITY) {
    case 'noise':
      options.connectionEncrypters = [noise()]
      break
    case 'plaintext':
      options.connectionEncrypters = [plaintext()]
      break
    default:
      throw new Error(`Unknown security: ${SECURITY}`)
  }

  // Muxer configuration
  switch (MUXER) {
    case 'yamux':
      options.streamMuxers = [yamux()]
      break
    default:
      throw new Error(`Unknown muxer: ${MUXER}`)
  }

  console.log('🔧 Creating libp2p node with proven interop configuration...')
  const node = await createLibp2p(options)

  await node.start()

  console.log(node.peerId.toString())
  for (const addr of node.getMultiaddrs()) {
    console.log(addr.toString())
  }

  // Debug: Print supported protocols
  console.log('DEBUG: Supported protocols:')
  try {
    const protocols = node.getProtocols()
    for (const protocol of protocols) {
      console.log('DEBUG: Protocol:', protocol)
    }
  } catch (e) {
    console.log('DEBUG: Could not get protocols:', e.message)
  }

  // Keep the process alive
  await new Promise(() => {})
}

main().catch(err => {
  console.error(err)
  process.exit(1)
})
