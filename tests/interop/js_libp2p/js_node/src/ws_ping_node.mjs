import { createLibp2p }          from 'libp2p'
import { webSockets }            from '@libp2p/websockets'
import { ping }                  from '@libp2p/ping'
import { plaintext }             from '@libp2p/insecure'
import { mplex }                 from '@libp2p/mplex'

async function main() {
  const node = await createLibp2p({
    transports:           [ webSockets() ],
    connectionEncryption: [ plaintext() ],
    streamMuxers:         [ mplex() ],
    services: {
      // installs /ipfs/ping/1.0.0 handler
      ping: ping()
    },
    addresses: {
      listen: ['/ip4/127.0.0.1/tcp/0/ws']
    }
  })

  await node.start()

  console.log(node.peerId.toString())
  for (const addr of node.getMultiaddrs()) {
    console.log(addr.toString())
  }

  // Keep the process alive
  await new Promise(() => {})
}

main().catch(err => {
  console.error(err)
  process.exit(1)
})
