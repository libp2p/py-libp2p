import { createLibp2p }          from 'libp2p'
import { webSockets }            from '@libp2p/websockets'
import { ping }                  from '@libp2p/ping'
import { noise }                 from '@chainsafe/libp2p-noise'
import { plaintext }             from '@libp2p/plaintext'
import { yamux }                 from '@chainsafe/libp2p-yamux'
// import { identify }              from '@libp2p/identify' // Commented out for compatibility

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

  // Security configuration
  switch (SECURITY) {
    case 'noise':
      options.connectionEncryption = [noise()]
      break
    case 'plaintext':
      options.connectionEncryption = [plaintext()]
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
  if (node.services && node.services.registrar) {
    const protocols = node.services.registrar.getProtocols()
    for (const protocol of protocols) {
      console.log('DEBUG: Protocol:', protocol)
    }
  }

  // Debug: Print connection encryption protocols
  console.log('DEBUG: Connection encryption protocols:')
  try {
    if (node.components && node.components.connectionEncryption) {
      for (const encrypter of node.components.connectionEncryption) {
        console.log('DEBUG: Encrypter:', encrypter.protocol)
      }
    }
  } catch (e) {
    console.log('DEBUG: Could not access connectionEncryption:', e.message)
  }

  // Debug: Print stream muxer protocols
  console.log('DEBUG: Stream muxer protocols:')
  try {
    if (node.components && node.components.streamMuxers) {
      for (const muxer of node.components.streamMuxers) {
        console.log('DEBUG: Muxer:', muxer.protocol)
      }
    }
  } catch (e) {
    console.log('DEBUG: Could not access streamMuxers:', e.message)
  }

  // Keep the process alive
  await new Promise(() => {})
}

main().catch(err => {
  console.error(err)
  process.exit(1)
})
