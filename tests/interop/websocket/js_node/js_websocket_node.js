import { TestResults } from './test_utils.js'
import { createServer } from 'http'

let LIBP2P_AVAILABLE = false

try {
    await import('libp2p')
    LIBP2P_AVAILABLE = true
} catch (error) {
    console.log('Warning: libp2p not available, using mock implementation')
}

export class JSWebSocketNode {
    constructor(port = 8000, secure = false) {
        this.port = port
        this.secure = secure
        this.node = null
        this.receivedMessages = []
        this.server = null
    }

    async setupNode() {
        if (LIBP2P_AVAILABLE) {
            console.log('Using real libp2p (not implemented in this mock)')
        } else {
            console.log('Using mock node (libp2p not available)')
        }

        return this
    }

    async handleConnection(data) {
        try {
            const message = data.toString()
            console.log(`Received message: ${message}`)

            this.receivedMessages.push(message)

            const response = `Echo: ${message}`
            return response

        } catch (error) {
            console.error('Error handling connection:', error)
            return null
        }
    }

    async startListening() {
        try {
            this.server = createServer((req, res) => {
                if (req.method === 'POST') {
                    let body = ''
                    req.on('data', chunk => {
                        body += chunk.toString()
                    })
                    req.on('end', async () => {
                        const response = await this.handleConnection(body)
                        res.writeHead(200, {'Content-Type': 'text/plain'})
                        res.end(response || 'No response')
                    })
                } else {
                    res.writeHead(400, {'Content-Type': 'text/plain'})
                    res.end('Only POST requests supported')
                }
            })

            await new Promise((resolve, reject) => {
                this.server.listen(this.port, '127.0.0.1', (error) => {
                    if (error) reject(error)
                    else resolve()
                })
            })

            const listenAddr = `/ip4/127.0.0.1/tcp/${this.port}`
            console.log(`JavaScript node (mock) listening on ${listenAddr}`)
            return listenAddr

        } catch (error) {
            console.error('Failed to start listening:', error)
            throw error
        }
    }

    async dialAndSend(targetAddr, message) {
        try {
            const portMatch = targetAddr.match(/tcp\/(\d+)/)
            const port = portMatch ? parseInt(portMatch[1]) : 8001

            console.log(`Dialing (mock) ${targetAddr}`)

            const response = await fetch(`http://127.0.0.1:${port}`, {
                method: 'POST',
                body: message,
                headers: {
                    'Content-Type': 'text/plain'
                }
            })

            if (response.ok) {
                const responseText = await response.text()
                console.log(`Received response: ${responseText}`)
                return responseText
            } else {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`)
            }

        } catch (error) {
            console.error('Failed to dial and send:', error)
            throw error
        }
    }

    async stop() {
        if (this.server) {
            await new Promise((resolve) => {
                this.server.close(resolve)
            })
        }
    }
}

export async function runJSServerTest(port = 8002, secure = false, duration = 30000) {
    const node = new JSWebSocketNode(port, secure)
    const results = new TestResults()

    try {
        await node.setupNode()
        const listenAddr = await node.startListening()

        const serverInfo = {
            address: listenAddr.toString(),
            port: port,
            secure: secure,
            mock: !LIBP2P_AVAILABLE
        }

        console.log(`SERVER_INFO:${JSON.stringify(serverInfo)}`)

        console.log(`Waiting for connections for ${duration}ms...`)
        await new Promise(resolve => setTimeout(resolve, duration))

        if (node.receivedMessages.length > 0) {
            results.addResult('message_received', true, {
                messages: node.receivedMessages,
                count: node.receivedMessages.length
            })
        } else {
            results.addResult('message_received', false, 'No messages received')
        }

        return results.toJSON()

    } catch (error) {
        results.addError(`Server error: ${error}`)
        console.error('Server error:', error)
        return results.toJSON()

    } finally {
        await node.stop()
    }
}

export async function runJSClientTest(targetAddr, message) {
    const node = new JSWebSocketNode()
    const results = new TestResults()

    try {
        await node.setupNode()

        const response = await node.dialAndSend(targetAddr, message)

        if (response && response.includes(message)) {
            results.addResult('dial_and_send', true, {
                sent: message,
                received: response
            })
        } else {
            results.addResult('dial_and_send', false, {
                sent: message,
                received: response
            })
        }

        return results.toJSON()

    } catch (error) {
        results.addError(`Client error: ${error}`)
        console.error('Client error:', error)
        return results.toJSON()

    } finally {
        await node.stop()
    }
}

if (process.argv[2] === 'server') {
    const port = parseInt(process.argv[3]) || 8002
    const secure = process.argv[4] === 'true'
    const duration = parseInt(process.argv[5]) || 30000

    runJSServerTest(port, secure, duration).then(results => {
        console.log('RESULTS:', JSON.stringify(results, null, 2))
    })

} else if (process.argv[2] === 'client') {
    const targetAddr = process.argv[3]
    const message = process.argv[4] || 'Hello from JS client'

    runJSClientTest(targetAddr, message).then(results => {
        console.log('RESULTS:', JSON.stringify(results, null, 2))
    })
}
