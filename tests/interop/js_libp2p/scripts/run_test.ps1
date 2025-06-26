#!/usr/bin/env pwsh

# run_test.ps1 - libp2p Interoperability Test Runner (PowerShell)
# Tests py-libp2p <-> js-libp2p ping communication

$ErrorActionPreference = "Stop"

# Colors for output
$Red = "`e[31m"
$Green = "`e[32m"
$Yellow = "`e[33m"
$Blue = "`e[34m"
$Cyan = "`e[36m"
$Reset = "`e[0m"

function Write-ColorOutput {
    param([string]$Message, [string]$Color = $Reset)
    Write-Host "${Color}${Message}${Reset}"
}

Write-ColorOutput "[CHECK] Checking prerequisites..." $Cyan
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-ColorOutput "[ERROR] Python not found. Install Python 3.7+" $Red
    exit 1
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-ColorOutput "[ERROR] Node.js not found. Install Node.js 16+" $Red
    exit 1
}

Write-ColorOutput "[CHECK] Checking port 8000..." $Blue
$portCheck = netstat -a -n -o | findstr :8000
if ($portCheck) {
    Write-ColorOutput "[ERROR] Port 8000 in use. Free the port." $Red
    Write-ColorOutput $portCheck $Yellow
    exit 1
}

Write-ColorOutput "[DEBUG] Cleaning up Python processes..." $Blue
Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*ping.py*" } | Stop-Process -Force -ErrorAction SilentlyContinue

Write-ColorOutput "[PYTHON] Starting server on port 8000..." $Yellow
Set-Location -Path "py_node"
$pyLogFile = "py_server_8000.log"
$pyErrLogFile = "py_server_8000.log.err"
$pyDebugLogFile = "ping_debug.log"

if (Test-Path $pyLogFile) { Remove-Item $pyLogFile -Force -ErrorAction SilentlyContinue }
if (Test-Path $pyErrLogFile) { Remove-Item $pyErrLogFile -Force -ErrorAction SilentlyContinue }
if (Test-Path $pyDebugLogFile) { Remove-Item $pyDebugLogFile -Force -ErrorAction SilentlyContinue }

$pyProcess = Start-Process -FilePath "python" -ArgumentList "-u", "ping.py", "server", "--port", "8000" -NoNewWindow -PassThru -RedirectStandardOutput $pyLogFile -RedirectStandardError $pyErrLogFile
Write-ColorOutput "[DEBUG] Python server PID: $($pyProcess.Id)" $Blue
Write-ColorOutput "[DEBUG] Python logs: $((Get-Location).Path)\$pyLogFile, $((Get-Location).Path)\$pyErrLogFile, $((Get-Location).Path)\$pyDebugLogFile" $Blue

$timeoutSeconds = 20
$startTime = Get-Date
$serverStarted = $false

while (((Get-Date) - $startTime).TotalSeconds -lt $timeoutSeconds -and -not $serverStarted) {
    if (Test-Path $pyLogFile) {
        $content = Get-Content $pyLogFile -Raw -ErrorAction SilentlyContinue
        if ($content -match "Server started|Listening") {
            $serverStarted = $true
            Write-ColorOutput "[OK] Python server started" $Green
        }
    }
    if (Test-Path $pyErrLogFile) {
        $errContent = Get-Content $pyErrLogFile -Raw -ErrorAction SilentlyContinue
        if ($errContent) {
            Write-ColorOutput "[DEBUG] Error log: $errContent" $Yellow
        }
    }
    Start-Sleep -Milliseconds 500
}

if (-not $serverStarted) {
    Write-ColorOutput "[ERROR] Python server failed to start" $Red
    Write-ColorOutput "[DEBUG] Logs:" $Yellow
    if (Test-Path $pyLogFile) { Get-Content $pyLogFile | Write-ColorOutput -Color $Yellow }
    if (Test-Path $pyErrLogFile) { Get-Content $pyErrLogFile | Write-ColorOutput -Color $Yellow }
    if (Test-Path $pyDebugLogFile) { Get-Content $pyDebugLogFile | Write-ColorOutput -Color $Yellow }
    Write-ColorOutput "[DEBUG] Trying foreground run..." $Yellow
    python -u ping.py server --port 8000
    exit 1
}

# Extract Peer ID
$peerInfo = $null
if (Test-Path $pyLogFile) {
    $content = Get-Content $pyLogFile -Raw
    $peerIdPattern = "Peer ID:\s*([A-Za-z0-9]+)"
    $peerIdMatch = [regex]::Match($content, $peerIdPattern)
    if ($peerIdMatch.Success) {
        $peerId = $peerIdMatch.Groups[1].Value
        $peerInfo = @{
            PeerId = $peerId
            MultiAddr = "/ip4/127.0.0.1/tcp/8000/p2p/$peerId"
        }
        Write-ColorOutput "[OK] Peer ID: $peerId" $Cyan
        Write-ColorOutput "[OK] MultiAddr: $($peerInfo.MultiAddr)" $Cyan
    }
}

if (-not $peerInfo) {
    Write-ColorOutput "[ERROR] Could not extract Peer ID" $Red
    if (Test-Path $pyLogFile) { Get-Content $pyLogFile | Write-ColorOutput -Color $Yellow }
    if (Test-Path $pyErrLogFile) { Get-Content $pyErrLogFile | Write-ColorOutput -Color $Yellow }
    if (Test-Path $pyDebugLogFile) { Get-Content $pyDebugLogFile | Write-ColorOutput -Color $Yellow }
    Stop-Process -Id $pyProcess.Id -Force -ErrorAction SilentlyContinue
    exit 1
}

# Start JavaScript client
Write-ColorOutput "[JAVASCRIPT] Starting client..." $Yellow
Set-Location -Path "../js_node"
$jsLogFile = "test_js_client_to_py_server.log"
$jsErrLogFile = "test_js_client_to_py_server.log.err"

if (Test-Path $jsLogFile) { Remove-Item $jsLogFile -Force -ErrorAction SilentlyContinue }
if (Test-Path $jsErrLogFile) { Remove-Item $jsErrLogFile -Force -ErrorAction SilentlyContinue }

$jsProcess = Start-Process -FilePath "node" -ArgumentList "src/ping.js", "client", $peerInfo.MultiAddr, "3" -NoNewWindow -PassThru -RedirectStandardOutput $jsLogFile -RedirectStandardError $jsErrLogFile
Write-ColorOutput "[DEBUG] JavaScript client PID: $($jsProcess.Id)" $Blue
Write-ColorOutput "[DEBUG] Client logs: $((Get-Location).Path)\$jsLogFile, $((Get-Location).Path)\$jsErrLogFile" $Blue

# Wait for client to complete
$clientTimeout = 10
$clientStart = Get-Date
while (-not $jsProcess.HasExited -and (((Get-Date) - $clientStart).TotalSeconds -lt $clientTimeout)) {
    Start-Sleep -Seconds 1
}

if (-not $jsProcess.HasExited) {
    Write-ColorOutput "[DEBUG] JavaScript client did not exit, terminating..." $Yellow
    Stop-Process -Id $jsProcess.Id -Force -ErrorAction SilentlyContinue
}

Write-ColorOutput "[CHECK] Results..." $Cyan
$success = $false
if (Test-Path $jsLogFile) {
    $jsLogContent = Get-Content $jsLogFile -Raw -ErrorAction SilentlyContinue
    if ($jsLogContent -match "successful|Ping.*successful") {
        $success = $true
        Write-ColorOutput "[SUCCESS] Ping test passed" $Green
    } else {
        Write-ColorOutput "[FAILED] No successful pings" $Red
        Write-ColorOutput "[DEBUG] Client log path: $((Get-Location).Path)\$jsLogFile" $Yellow
        Write-ColorOutput "Client log:" $Yellow
        Write-ColorOutput $jsLogContent $Yellow
        if (Test-Path $jsErrLogFile) {
            Write-ColorOutput "[DEBUG] Client error log path: $((Get-Location).Path)\$jsErrLogFile" $Yellow
            Write-ColorOutput "Client error log:" $Yellow
            Get-Content $jsErrLogFile | Write-ColorOutput -Color $Yellow
        }
        Write-ColorOutput "[DEBUG] Python server log path: $((Get-Location).Path)\..\py_node\$pyLogFile" $Yellow
        Write-ColorOutput "Python server log:" $Yellow
        if (Test-Path "../py_node/$pyLogFile") {
            $pyLogContent = Get-Content "../py_node/$pyLogFile" -Raw -ErrorAction SilentlyContinue
            if ($pyLogContent) { Write-ColorOutput $pyLogContent $Yellow } else { Write-ColorOutput "Empty or inaccessible" $Yellow }
        } else {
            Write-ColorOutput "File not found" $Yellow
        }
        Write-ColorOutput "[DEBUG] Python server error log path: $((Get-Location).Path)\..\py_node\$pyErrLogFile" $Yellow
        Write-ColorOutput "Python server error log:" $Yellow
        if (Test-Path "../py_node/$pyErrLogFile") {
            $pyErrLogContent = Get-Content "../py_node/$pyErrLogFile" -Raw -ErrorAction SilentlyContinue
            if ($pyErrLogContent) { Write-ColorOutput $pyErrLogContent $Yellow } else { Write-ColorOutput "Empty or inaccessible" $Yellow }
        } else {
            Write-ColorOutput "File not found" $Yellow
        }
        Write-ColorOutput "[DEBUG] Python debug log path: $((Get-Location).Path)\..\py_node\$pyDebugLogFile" $Yellow
        Write-ColorOutput "Python debug log:" $Yellow
        if (Test-Path "../py_node/$pyDebugLogFile") {
            $pyDebugLogContent = Get-Content "../py_node/$pyDebugLogFile" -Raw -ErrorAction SilentlyContinue
            if ($pyDebugLogContent) { Write-ColorOutput $pyDebugLogContent $Yellow } else { Write-ColorOutput "Empty or inaccessible" $Yellow }
        } else {
            Write-ColorOutput "File not found" $Yellow
        }
    }
}

Write-ColorOutput "[CLEANUP] Stopping processes..." $Yellow
Stop-Process -Id $pyProcess.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $jsProcess.Id -Force -ErrorAction SilentlyContinue
Set-Location -Path "../"

if ($success) {
    Write-ColorOutput "[SUCCESS] Test completed" $Green
    exit 0
} else {
    Write-ColorOutput "[FAILED] Test failed" $Red
    exit 1
}
