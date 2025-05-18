These commands are to be run in `./interop/exec`

## Redis

```bash
docker run -p 6379:6379 -it redis:latest
```

## Listener

```bash
transport=tcp ip=0.0.0.0 is_dialer=false redis_addr=localhost:6379 test_timeout_seconds=180 security=insecure muxer=mplex  python3 native_ping.py
```

## Dialer

```bash
transport=tcp ip=0.0.0.0 is_dialer=true redis_addr=localhost:6379 port=8001 test_timeout_seconds=180 security=insecure muxer=mplex  python3 native_ping.py
```
