#!/usr/bin/env node

import { createLibp2p } from 'libp2p'
import { tcp } from '@libp2p/tcp'
import { noise } from '@chainsafe/libp2p-noise'
import { yamux } from '@chainsafe/libp2p-yamux'
import { ping } from '@libp2p/ping'
import { identify } from '@libp2p/identify'
import { multiaddr } from '@multiformats/multiaddr'

async function createNode() {
  return await createLibp2p({
    addresses: {
      listen: ['/ip4/0.0.0.0/tcp/0']
    },
    transports: [
      tcp()
    ],
    connectionEncrypters: [
      noise()
    ],
    streamMuxers: [
      yamux()
    ],
    services: {
      // Use ipfs prefix to match py-libp2p example
      ping: ping({
        protocolPrefix: 'ipfs',
        maxInboundStreams: 32,
        maxOutboundStreams: 64,
        timeout: 30000
      }),
      identify: identify()
    },
    connectionManager: {
      minConnections: 0,
      maxConnections: 100,
      dialTimeout: 30000
    }
  })
}

async function runServer() {
  console.log('🚀 Starting js-libp2p ping server...')

  const node = await createNode()
  await node.start()

  console.log('✅ Server started!')
  console.log(`📋 Peer ID: ${node.peerId.toString()}`)
  console.log('📍 Listening addresses:')

  node.getMultiaddrs().forEach(addr => {
    console.log(`   ${addr.toString()}`)
  })

  // Listen for connections
  node.addEventListener('peer:connect', (evt) => {
    console.log(`🔗 Peer connected: ${evt.detail.toString()}`)
  })

  node.addEventListener('peer:disconnect', (evt) => {
    console.log(`❌ Peer disconnected: ${evt.detail.toString()}`)
  })

  console.log('\n🎧 Server ready for ping requests...')
  console.log('Press Ctrl+C to exit')

  // Graceful shutdown
  process.on('SIGINT', async () => {
    console.log('\n🛑 Shutting down...')
    await node.stop()
    process.exit(0)
  })

  // Keep alive
  while (true) {
    await new Promise(resolve => setTimeout(resolve, 1000))
  }
}

async function runClient(targetAddr, count = 5) {
  console.log('🚀 Starting js-libp2p ping client...')

  const node = await createNode()
  await node.start()

  console.log(`📋 Our Peer ID: ${node.peerId.toString()}`)
  console.log(`🎯 Target: ${targetAddr}`)

  try {
    const ma = multiaddr(targetAddr)
    const targetPeerId = ma.getPeerId()

    if (!targetPeerId) {
      throw new Error('Could not extract peer ID from multiaddr')
    }

    console.log(`🎯 Target Peer ID: ${targetPeerId}`)
    console.log('🔗 Connecting to peer...')

    const connection = await node.dial(ma)
    console.log('✅ Connection established!')
    console.log(`🔗 Connected to: ${connection.remotePeer.toString()}`)

    // Add a small delay to let the connection fully establish
    await new Promise(resolve => setTimeout(resolve, 1000))

    const rtts = []

    for (let i = 1; i <= count; i++) {
      try {
        console.log(`\n🏓 Sending ping ${i}/${count}...`);
        console.log('[DEBUG] Attempting to open ping stream with protocol: /ipfs/ping/1.0.0');
        const start = Date.now()

        const stream = await connection.newStream(['/ipfs/ping/1.0.0']).catch(err => {
          console.error(`[ERROR] Failed to open ping stream: ${err.message}`);
          throw err;
        });
        console.log('[DEBUG] Ping stream opened successfully');

        const latency = await Promise.race([
          node.services.ping.ping(connection.remotePeer),
          new Promise((_, reject) =>
            setTimeout(() => reject(new Error('Ping timeout')), 30000) // Increased timeout
          )
        ]).catch(err => {
          console.error(`[ERROR] Ping ${i} error: ${err.message}`);
          throw err;
        });

        const rtt = Date.now() - start;

        rtts.push(latency)
        console.log(`✅ Ping ${i} successful!`)
        console.log(`   Reported latency: ${latency}ms`)
        console.log(`   Measured RTT: ${rtt}ms`)

        if (i < count) {
          await new Promise(resolve => setTimeout(resolve, 1000))
        }
      } catch (error) {
        console.error(`❌ Ping ${i} failed:`, error.message)
        // Try to continue with other pings
      }
    }

    // Stats
    if (rtts.length > 0) {
      const avg = rtts.reduce((a, b) => a + b, 0) / rtts.length
      const min = Math.min(...rtts)
      const max = Math.max(...rtts)

      console.log(`\n📊 Ping Statistics:`)
      console.log(`   Packets: Sent=${count}, Received=${rtts.length}, Lost=${count - rtts.length}`)
      console.log(`   Latency: min=${min}ms, avg=${avg.toFixed(2)}ms, max=${max}ms`)
    } else {
      console.log(`\n📊 All pings failed (${count} attempts)`)
    }

  } catch (error) {
    console.error('❌ Client error:', error.message)
    console.error('Stack:', error.stack)
    process.exit(1)
  } finally {
    await node.stop()
    console.log('\n⏹️  Client stopped')
  }
}

async function main() {
  const args = process.argv.slice(2)

  if (args.length === 0) {
    console.log('Usage:')
    console.log('  node ping.js server                    # Start ping server')
    console.log('  node ping.js client <multiaddr> [count]  # Ping a peer')
    console.log('')
    console.log('Examples:')
    console.log('  node ping.js server')
    console.log('  node ping.js client /ip4/127.0.0.1/tcp/12345/p2p/12D3Ko... 5')
    process.exit(1)
  }

  const mode = args[0]

  if (mode === 'server') {
    await runServer()
  } else if (mode === 'client') {
    if (args.length < 2) {
      console.error('❌ Client mode requires target multiaddr')
      process.exit(1)
    }
    const targetAddr = args[1]
    const count = parseInt(args[2]) || 5
    await runClient(targetAddr, count)
  } else {
    console.error('❌ Invalid mode. Use "server" or "client"')
    process.exit(1)
  }
}

main().catch(console.error)
