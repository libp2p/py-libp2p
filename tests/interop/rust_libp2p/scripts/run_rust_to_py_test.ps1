# scripts/run_rust_to_py_test.ps1
# Test script for rust-libp2p client connecting to py-libp2p server

param(
    [int]$Port = 8000,
    [int]$PingCount = 5,
    [int]$TimeoutSeconds = 30
)

Write-Host "=== rust-libp2p to py-libp2p Interop Test ===" -ForegroundColor Cyan
Write-Host "Starting py-libp2p server on port $Port..." -ForegroundColor Yellow

# Start Python server in background
$pyProcess = Start-Process -FilePath "python" -ArgumentList "py_node/ping.py", "server", "--port", $Port -PassThru -RedirectStandardOutput "py_server_output.txt" -RedirectStandardError "py_server_error.txt"

# Wait for server to start
Start-Sleep -Seconds 5

try {
    # Read the server output to get peer ID
    $maxWaitTime = 10
    $waited = 0
    $peerID = $null
    
    while ($waited -lt $maxWaitTime -and !$peerID) {
        if (Test-Path "py_server_output.txt") {
            $output = Get-Content "py_server_output.txt" -Raw
            if ($output -match "Peer ID: ([\w\d]+)") {
                $peerID = $matches[1]
                break
            }
        }
        Start-Sleep -Seconds 1
        $waited++
    }
    
    if (!$peerID) {
        Write-Host "Could not extract Peer ID from Python server output" -ForegroundColor Red
        Write-Host "Server output:" -ForegroundColor Yellow
        if (Test-Path "py_server_output.txt") {
            Get-Content "py_server_output.txt"
        }
        if (Test-Path "py_server_error.txt") {
            Write-Host "Server errors:" -ForegroundColor Red
            Get-Content "py_server_error.txt"
        }
        return
    }
    
    $multiaddr = "/ip4/127.0.0.1/tcp/$Port/p2p/$peerID"
    Write-Host "Python server started with Peer ID: $peerID" -ForegroundColor Green
    Write-Host "Full address: $multiaddr" -ForegroundColor Green
    
    Write-Host "Starting rust client..." -ForegroundColor Yellow
    
    # Run rust client
    $rustResult = Start-Process -FilePath "cargo" -ArgumentList "run", "--", $multiaddr -WorkingDirectory "rust_node" -Wait -PassThru -NoNewWindow
    
    if ($rustResult.ExitCode -eq 0) {
        Write-Host "Rust client completed successfully!" -ForegroundColor Green
    } else {
        Write-Host "Rust client failed with exit code: $($rustResult.ExitCode)" -ForegroundColor Red
    }
    
} finally {
    # Clean up
    Write-Host "Stopping Python server..." -ForegroundColor Yellow
    if ($pyProcess -and !$pyProcess.HasExited) {
        $pyProcess.Kill()
        $pyProcess.WaitForExit(5000)
    }
    
    # Clean up output files
    if (Test-Path "py_server_output.txt") { Remove-Item "py_server_output.txt" }
    if (Test-Path "py_server_error.txt") { Remove-Item "py_server_error.txt" }
    
    Write-Host "Test completed." -ForegroundColor Green
}