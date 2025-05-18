import trio

from interop.exec.config.mod import (
    Config,
    ConfigError,
)
from interop.lib import (
    run_test,
)


async def main() -> None:
    try:
        config = Config.from_env()
    except ConfigError as e:
        print(f"Config error: {e}")
        return

    # Uncomment and implement when ready
    _ = await run_test(
        config.transport,
        config.ip,
        config.port,
        config.is_dialer,
        config.test_timeout,
        config.redis_addr,
        config.sec_protocol,
        config.muxer,
    )


if __name__ == "__main__":
    trio.run(main)
