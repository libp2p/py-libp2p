import { spawn } from 'child_process'
import { TestResults } from './test_utils.js'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

async function testJSClientPyServer() {
  const results = new TestResults()
  let pyProcess = null

  try {
    const pyServerPath = join(__dirname, '..', 'py_node', 'py_websocket_node.py')

    console.log('Starting Python server...')
    pyProcess = spawn('python', [
      pyServerPath, 'server', '8004', 'false', '30'
    ], { stdio: 'pipe' })

    await new Promise(resolve => setTimeout(resolve, 3000))
    console.log('Python server should be ready on port 8004')

    const targetUrl = 'http://127.0.0.1:8004'
    const testMessage = 'Hello from JS client'

    console.log(`Sending message to Python server: ${testMessage}`)

    try {
      const response = await fetch(targetUrl, {
        method: 'POST',
        body: testMessage,
        headers: {
          'Content-Type': 'text/plain'
        }
      })

      if (response.ok) {
        const responseText = await response.text()
        console.log(`Received response: ${responseText}`)

        if (responseText.includes(testMessage)) {
          results.addResult('js_to_py_communication', true, {
            sent: testMessage,
            received: responseText
          })
          console.log('JS to Python test completed successfully')
        } else {
          results.addResult('js_to_py_communication', false, {
            sent: testMessage,
            received: responseText,
            error: 'Response does not contain original message'
          })
          console.log('JS to Python test failed: unexpected response')
        }
      } else {
        results.addResult('js_to_py_communication', false, {
          error: `HTTP ${response.status}: ${response.statusText}`
        })
        console.log(`JS to Python test failed: HTTP ${response.status}`)
      }
    } catch (error) {
      results.addResult('js_to_py_communication', false, {
        error: `Fetch error: ${error.message}`
      })
      console.log(`JS to Python test failed: ${error.message}`)
    }

  } catch (error) {
    results.addError(`Test error: ${error}`)
    console.error('Test error:', error)

  } finally {
    if (pyProcess) {
      console.log('\nStopping Python server...')
      pyProcess.kill()
    }
  }

  return results.toJSON()
}

console.log('=== JavaScript Client to Python Server Test ===')
testJSClientPyServer().then(results => {
  console.log('\nTest Results:', JSON.stringify(results, null, 2))
})
