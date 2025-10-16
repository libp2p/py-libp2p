import { spawn } from 'child_process'
import { TestResults } from '../js_node/test_utils.js'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

async function testJSClientPyServer() {
    const results = new TestResults()
    let pyProcess = null
    
    try {
        const pyServerPath = join(__dirname, '..', 'py_node', 'simple_server.py')
        pyProcess = spawn('python', [
            pyServerPath, '8004', '15'
        ], { stdio: 'pipe' })
        
        await new Promise(resolve => setTimeout(resolve, 3000))
        
        const targetUrl = 'http://127.0.0.1:8004'
        const testMessage = 'Hello from JS client'
        
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
                
                if (responseText.includes(testMessage)) {
                    results.addResult('js_to_py_communication', true, {
                        sent: testMessage,
                        received: responseText
                    })
                } else {
                    results.addResult('js_to_py_communication', false, {
                        sent: testMessage,
                        received: responseText
                    })
                }
            } else {
                results.addResult('js_to_py_communication', false, {
                    error: `HTTP ${response.status}: ${response.statusText}`
                })
            }
        } catch (error) {
            results.addResult('js_to_py_communication', false, {
                error: `Fetch error: ${error.message}`
            })
        }
        
    } catch (error) {
        results.addError(`Test error: ${error}`)
        
    } finally {
        if (pyProcess) {
            pyProcess.kill()
        }
    }
    
    return results.toJSON()
}

testJSClientPyServer().then(results => {
    console.log('Test Results:', JSON.stringify(results, null, 2))
})
