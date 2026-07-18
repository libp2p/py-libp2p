#!/usr/bin/env node

import { createLibp2p } from 'libp2p'
import { tcp } from '@libp2p/tcp'
import { noise } from '@chainsafe/libp2p-noise'
import { yamux } from '@chainsafe/libp2p-yamux'
import { ping } from '@libp2p/ping'
import { identify } from '@libp2p/identify'
import fs from 'fs'
import path from 'path'

// Create logs directory if it doesn't exist
const logsDir = path.join(process.cwd(), '../logs')
if (!fs.existsSync(logsDir)) {
  fs.mkdirSync(logsDir, { recursive: true })
}

// Setup logging
const logFile = path.join(logsDir, 'js_ping_server.log')
const logStream = fs.createWriteStream(logFile, { flags: 'w' })

function log(message) {
  const timestamp = new Date().toISOString()
  const logLine = `${timestamp} - ${message}\n`
  logStream.write(logLine)
  console.log(message)
}

async function createNode(port) {
  log('🔧 Creating libp2p node...')

  const node = await createLibp2p({
    addresses: {
      listen: [`/ip4/0.0.0.0/tcp/${port}`]
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

async function runServer(port) {
  log('🚀 Starting js-libp2p ping server...')

  const node = await createNode(port)

  // Add connection event listeners
  node.addEventListener('peer:connect', (evt) => {
    log(`🔗 New peer connected: ${evt.detail.toString()}`)
  })

  node.addEventListener('peer:disconnect', (evt) => {
    log(`❌ Peer disconnected: ${evt.detail.toString()}`)
  })

  // Add protocol handler for incoming streams
  node.addEventListener('peer:identify', (evt) => {
    log(`🔍 Peer identified: ${evt.detail.peerId.toString()}`)
    log(`   Protocols: ${evt.detail.protocols.join(', ')}`)
    log(`   Listen addresses: ${evt.detail.listenAddrs.map(addr => addr.toString()).join(', ')}`)
  })

  await node.start()
  log('✅ Node started')

  const peerId = node.peerId.toString()
  const listenAddrs = node.getMultiaddrs()

  log(`📋 Peer ID: ${peerId}`)
  log(`🌐 Listen addresses:`)
  listenAddrs.forEach(addr => {
    log(`   ${addr.toString()}`)
  })

  // Find the main TCP address for easy copy-paste
  const tcpAddr = listenAddrs.find(addr =>
    addr.toString().includes('/tcp/') &&
    !addr.toString().includes('/ws')
  )

  if (tcpAddr) {
    log(`\n🧪 Test with py-libp2p:`)
    log(`   python ping_client.py ${tcpAddr.toString()}`)
    log(`\n🧪 Test with js-libp2p:`)
    log(`   node ping-client.js ${tcpAddr.toString()}`)
  }

  log(`\n🏓 Ping service is running with protocol: /ipfs/ping/1.0.0`)
  log(`🔐 Security: Noise encryption`)
  log(`🚇 Muxer: Yamux stream multiplexing`)
  log(`\n⏳ Waiting for connections...`)
  log('Press Ctrl+C to exit')

  // Keep the server running
  return new Promise((resolve, reject) => {
    process.on('SIGINT', () => {
      log('\n🛑 Shutting down server...')
      node.stop().then(() => {
        log('⏹️  Server stopped')
        logStream.end()
        resolve()
      }).catch(reject)
    })

    process.on('uncaughtException', (error) => {
      log(`💥 Uncaught exception: ${error.message}`)
      if (error.stack) {
        log(`Stack: ${error.stack}`)
      }
      logStream.end()
      reject(error)
    })
  })
}

async function main() {
  const args = process.argv.slice(2)
  const port = parseInt(args[0]) || 9000

  if (port <= 0 || port > 65535) {
    console.error('❌ Port must be between 1 and 65535')
    process.exit(1)
  }

  try {
    await runServer(port)
  } catch (error) {
    console.error(`💥 Fatal error: ${error.message}`)
    if (error.stack) {
      console.error(`Stack: ${error.stack}`)
    }
    process.exit(1)
  }
}

main().catch((error) => {
  console.error(`💥 Fatal error: ${error.message}`)
  if (error.stack) {
    console.error(`Stack: ${error.stack}`)
  }
  process.exit(1)
})
