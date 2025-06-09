# scripts/run_py_to_rust_test.ps1
# Test script for py-libp2p client connecting to rust-libp2p server

param(
    [int]$PingCount = 5,
    [int]$TimeoutSeconds = 30
)

Write-Host "=== py-libp2p to rust-libp2p Interop Test ===" -ForegroundColor Cyan
Write-Host "Starting rust-libp2p server..." -ForegroundColor Yellow

# Start rust server in background
$rustProcess = Start-Process -FilePath "cargo" -ArgumentList "run" -WorkingDirectory "rust_node" -PassThru -WindowStyle Hidden

# Wait a moment for server to start
Start-Sleep -Seconds 3

try {
    # Get the rust server's listening address from its output
    # For now, we'll assume it's listening on a predictable port
    # In a real scenario, you'd parse the server output to get the actual address
    
    Write-Host "Waiting for rust server to start..." -ForegroundColor Yellow
    Start-Sleep -Seconds 5
    
    # Try to find the server's peer ID and port from netstat or process output
    # For this test, we'll need to manually check the rust server output
    Write-Host "Please check the rust server output for its Peer ID and port" -ForegroundColor Red
    Write-Host "Then run the Python client manually with:" -ForegroundColor Yellow
    Write-Host "python py_node/ping.py client /ip4/127.0.0.1/tcp/<PORT>/p2p/<PEER_ID> --count $PingCount" -ForegroundColor Green
    
    # Keep the server running
    Write-Host "Press any key to stop the test..." -ForegroundColor Cyan
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    
} finally {
    # Clean up
    Write-Host "Stopping rust server..." -ForegroundColor Yellow
    if ($rustProcess -and !$rustProcess.HasExited) {
        $rustProcess.Kill()
        $rustProcess.WaitForExit(5000)
    }
    Write-Host "Test completed." -ForegroundColor Green
}