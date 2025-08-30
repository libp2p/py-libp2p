These commands are to be run in `./interop/exec`

## Redis

```bash
docker run -p 6379:6379 -it redis:latest
```

## Listener

```bash
transport=tcp ip=127.0.0.1  redis_addr=6379 port=8001 test_timeout_seconds=180 security=noise muxer=yamux is_dialer=false python3 native_ping.py
```

## Dialer

```bash
transport=tcp ip=127.0.0.1  redis_addr=6379 port=8001 test_timeout_seconds=180 security=noise  muxer=yamux is_dialer=true python3 native_ping.py
```

## From the Rust-side (Listener)

```bash
RUST_LOG=debug redis_addr=localhost:6379 ip="0.0.0.0" transport=tcp security=noise muxer=yamux is_dialer="false" cargo run --bin native_ping
```
