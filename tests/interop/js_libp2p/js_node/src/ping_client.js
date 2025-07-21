#!/usr/bin/env node

import { createLibp2p } from 'libp2p'
import { tcp } from '@libp2p/tcp'
import { noise } from '@chainsafe/libp2p-noise'
import { yamux } from '@chainsafe/libp2p-yamux'
import { ping } from '@libp2p/ping'
import { identify } from '@libp2p/identify'
import { multiaddr } from '@multiformats/multiaddr'
import fs from 'fs'
import path from 'path'

// Create logs directory if it doesn't exist
const logsDir = path.join(process.cwd(), '../logs')
if (!fs.existsSync(logsDir)) {
  fs.mkdirSync(logsDir, { recursive: true })
}

// Setup logging
const logFile = path.join(logsDir, 'js_ping_client.log')
const logStream = fs.createWriteStream(logFile, { flags: 'w' })

function log(message) {
  const timestamp = new Date().toISOString()
  const logLine = `${timestamp} - ${message}\n`
  logStream.write(logLine)
  console.log(message)
}

async function createNode() {
  log('🔧 Creating libp2p node...')

  const node = await createLibp2p({
    addresses: {
      listen: ['/ip4/0.0.0.0/tcp/0'] // Random port
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
      ping: ping({
        protocolPrefix: 'ipfs', // Use ipfs prefix to match py-libp2p
        maxInboundStreams: 32,
        maxOutboundStreams: 64,
        timeout: 30000,
        runOnTransientConnection: true
      }),
      identify: identify()
    },
    connectionManager: {
      minConnections: 0,
      maxConnections: 100,
      dialTimeout: 30000,
      maxParallelDials: 10
    }
  })

  log('✅ Node created successfully')
  return node
}

async function runClient(targetAddr, count = 5) {
  log('🚀 Starting js-libp2p ping client...')

  const node = await createNode()

  // Add connection event listeners
  node.addEventListener('peer:connect', (evt) => {
    log(`🔗 Connected to peer: ${evt.detail.toString()}`)
  })

  node.addEventListener('peer:disconnect', (evt) => {
    log(`❌ Disconnected from peer: ${evt.detail.toString()}`)
  })

  await node.start()
  log('✅ Node started')

  log(`📋 Our Peer ID: ${node.peerId.toString()}`)
  log(`🎯 Target: ${targetAddr}`)

  try {
    const ma = multiaddr(targetAddr)
    const targetPeerId = ma.getPeerId()

    if (!targetPeerId) {
      throw new Error('Could not extract peer ID from multiaddr')
    }

    log(`🎯 Target Peer ID: ${targetPeerId}`)

    // Parse multiaddr components for debugging
    const components = ma.toString().split('/')
    log(`📍 Target components: ${components.join(' → ')}`)

    log('🔗 Attempting to dial peer...')
    const connection = await node.dial(ma)
    log('✅ Connection established!')
    log(`🔗 Connected to: ${connection.remotePeer.toString()}`)
    log(`🔗 Connection status: ${connection.status}`)
    log(`🔗 Connection direction: ${connection.direction}`)

    // List available protocols
    if (connection.remoteAddr) {
      log(`🌐 Remote address: ${connection.remoteAddr.toString()}`)
    }

    // Wait for connection to stabilize
    log('⏳ Waiting for connection to stabilize...')
    await new Promise(resolve => setTimeout(resolve, 2000))

    // Attempt ping sequence
    log(`\n🏓 Starting ping sequence (${count} pings)...`)
    const rtts = []

    for (let i = 1; i <= count; i++) {
      try {
        log(`\n🏓 Sending ping ${i}/${count}...`)
        const start = Date.now()

        // Create a more robust ping with better error handling
        const pingPromise = node.services.ping.ping(connection.remotePeer)
        const timeoutPromise = new Promise((_, reject) =>
          setTimeout(() => reject(new Error('Ping timeout (15s)')), 15000)
        )

        const latency = await Promise.race([pingPromise, timeoutPromise])
        const totalRtt = Date.now() - start

        rtts.push(latency)
        log(`✅ Ping ${i} successful!`)
        log(`   Reported latency: ${latency}ms`)
        log(`   Total RTT: ${totalRtt}ms`)

        // Wait between pings
        if (i < count) {
          await new Promise(resolve => setTimeout(resolve, 1000))
        }
      } catch (error) {
        log(`❌ Ping ${i} failed: ${error.message}`)
        log(`   Error type: ${error.constructor.name}`)
        if (error.code) {
          log(`   Error code: ${error.code}`)
        }

        // Check if connection is still alive
        if (connection.status !== 'open') {
          log(`⚠️  Connection status changed to: ${connection.status}`)
          break
        }
      }
    }

    // Print statistics
    if (rtts.length > 0) {
      const avg = rtts.reduce((a, b) => a + b, 0) / rtts.length
      const min = Math.min(...rtts)
      const max = Math.max(...rtts)
      const lossRate = ((count - rtts.length) / count * 100).toFixed(1)

      log(`\n📊 Ping Statistics:`)
      log(`   Packets: Sent=${count}, Received=${rtts.length}, Lost=${count - rtts.length}`)
      log(`   Loss rate: ${lossRate}%`)
      log(`   Latency: min=${min}ms, avg=${avg.toFixed(2)}ms, max=${max}ms`)
    } else {
      log(`\n📊 All pings failed (${count} attempts)`)
    }

    // Close connection gracefully
    log('\n🔒 Closing connection...')
    await connection.close()

  } catch (error) {
    log(`❌ Client error: ${error.message}`)
    log(`   Error type: ${error.constructor.name}`)
    if (error.stack) {
      log(`   Stack trace: ${error.stack}`)
    }
    process.exit(1)
  } finally {
    log('🛑 Stopping node...')
    await node.stop()
    log('⏹️  Client stopped')
    logStream.end()
  }
}

async function main() {
  const args = process.argv.slice(2)

  if (args.length === 0) {
    console.log('Usage:')
    console.log('  node ping-client.js <target-multiaddr> [count]')
    console.log('')
    console.log('Examples:')
    console.log('  node ping-client.js /ip4/127.0.0.1/tcp/8000/p2p/QmExample... 5')
    console.log('  node ping-client.js /ip4/127.0.0.1/tcp/8000/p2p/QmExample... 10')
    process.exit(1)
  }

  const targetAddr = args[0]
  const count = parseInt(args[1]) || 5

  if (count <= 0 || count > 100) {
    console.error('❌ Count must be between 1 and 100')
    process.exit(1)
  }

  await runClient(targetAddr, count)
}

// Handle graceful shutdown
process.on('SIGINT', () => {
  log('\n👋 Shutting down...')
  logStream.end()
  process.exit(0)
})

process.on('uncaughtException', (error) => {
  log(`💥 Uncaught exception: ${error.message}`)
  if (error.stack) {
    log(`Stack: ${error.stack}`)
  }
  logStream.end()
  process.exit(1)
})

main().catch((error) => {
  log(`💥 Fatal error: ${error.message}`)
  if (error.stack) {
    log(`Stack: ${error.stack}`)
  }
  logStream.end()
  process.exit(1)
})
