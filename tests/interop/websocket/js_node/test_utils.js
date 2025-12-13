export class TestResults {
    constructor() {
        this.results = {}
        this.errors = []
        this.startTime = Date.now()
    }

    addResult(testName, success, details = null) {
        this.results[testName] = {
            success,
            details,
            timestamp: Date.now(),
            duration: Date.now() - this.startTime
        }
    }

    addError(error) {
        this.errors.push(error.toString())
    }

    toJSON() {
        return {
            results: this.results,
            errors: this.errors,
            totalTests: Object.keys(this.results).length,
            passed: Object.values(this.results).filter(r => r.success).length,
            failed: Object.values(this.results).filter(r => !r.success).length,
            totalDuration: Date.now() - this.startTime
        }
    }

    printSummary() {
        const data = this.toJSON()
        console.log('\n' + '='.repeat(50))
        console.log('TEST RESULTS SUMMARY')
        console.log('='.repeat(50))
        console.log(`Total Tests: ${data.totalTests}`)
        console.log(`Passed: ${data.passed}`)
        console.log(`Failed: ${data.failed}`)
        console.log(`Duration: ${data.totalDuration}ms`)

        if (this.errors.length > 0) {
            console.log(`\nErrors (${this.errors.length}):`)
            this.errors.forEach(error => console.log(`  - ${error}`))
        }

        console.log('\nDetailed Results:')
        Object.entries(this.results).forEach(([testName, result]) => {
            const status = result.success ? '✓ PASS' : '✗ FAIL'
            console.log(`  ${testName}: ${status} (${result.duration}ms)`)
            if (result.details && !result.success) {
                console.log(`    Details: ${JSON.stringify(result.details)}`)
            }
        })
    }
}

export async function waitForServerReady(host, port, timeout = 10000) {
    const startTime = Date.now()

    while (Date.now() - startTime < timeout) {
        try {
            const response = await fetch(`http://${host}:${port}`, {
                method: 'HEAD',
                signal: AbortSignal.timeout(1000)
            })
            return true
        } catch (error) {
            await new Promise(resolve => setTimeout(resolve, 500))
        }
    }

    return false
}

export async function saveResultsToFile(results, filename = 'test_results.json') {
    try {
        const fs = await import('fs')
        fs.writeFileSync(filename, JSON.stringify(results, null, 2))
        console.log(`Results saved to ${filename}`)
    } catch (error) {
        console.error(`Failed to save results: ${error}`)
    }
}
