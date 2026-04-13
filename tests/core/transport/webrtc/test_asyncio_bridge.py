"""
Tests for the trio ↔ asyncio bridge.

These test the bridge in isolation — no aiortc dependency needed.  We use
plain asyncio coroutines (sleep, gather, etc.) to exercise the bridge
mechanics: lifecycle, concurrency, error propagation, cancellation, and
stress.
"""

from __future__ import annotations

import asyncio

import pytest
import trio

from libp2p.transport.webrtc._asyncio_bridge import (
    AsyncioBridge,
    AsyncioBridgeError,
)

# ---------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------


class TestLifecycle:
    @pytest.mark.trio
    async def test_start_and_stop(self):
        bridge = AsyncioBridge()
        assert not bridge.is_running
        await bridge.start()
        assert bridge.is_running
        assert bridge.loop is not None
        await bridge.stop()
        assert not bridge.is_running
        assert bridge.loop is None

    @pytest.mark.trio
    async def test_context_manager(self):
        async with AsyncioBridge() as bridge:
            assert bridge.is_running
        assert not bridge.is_running

    @pytest.mark.trio
    async def test_double_start_is_noop(self):
        async with AsyncioBridge() as bridge:
            await bridge.start()  # second start — should not raise
            assert bridge.is_running

    @pytest.mark.trio
    async def test_double_stop_is_noop(self):
        bridge = AsyncioBridge()
        await bridge.start()
        await bridge.stop()
        await bridge.stop()  # second stop — should not raise
        assert not bridge.is_running

    @pytest.mark.trio
    async def test_restart_after_stop_raises(self):
        bridge = AsyncioBridge()
        await bridge.start()
        await bridge.stop()
        with pytest.raises(AsyncioBridgeError, match="Cannot restart"):
            await bridge.start()

    @pytest.mark.trio
    async def test_stop_without_start_is_noop(self):
        bridge = AsyncioBridge()
        await bridge.stop()  # never started — should not raise

    @pytest.mark.trio
    async def test_repr(self):
        bridge = AsyncioBridge()
        assert "idle" in repr(bridge)
        await bridge.start()
        assert "running" in repr(bridge)
        await bridge.stop()
        assert "stopped" in repr(bridge)


# ---------------------------------------------------------------
# Basic coroutine execution
# ---------------------------------------------------------------


class TestRunCoro:
    @pytest.mark.trio
    async def test_simple_return(self):
        async with AsyncioBridge() as bridge:
            result = await bridge.run_coro(self._add(2, 3))
            assert result == 5

    @pytest.mark.trio
    async def test_return_none(self):
        async with AsyncioBridge() as bridge:
            result = await bridge.run_coro(self._noop())
            assert result is None

    @pytest.mark.trio
    async def test_return_large_data(self):
        async with AsyncioBridge() as bridge:
            data = await bridge.run_coro(self._make_bytes(1_000_000))
            assert len(data) == 1_000_000

    @pytest.mark.trio
    async def test_run_coro_on_stopped_bridge(self):
        bridge = AsyncioBridge()
        with pytest.raises(AsyncioBridgeError, match="not running"):
            await bridge.run_coro(self._noop())

    @pytest.mark.trio
    async def test_run_coro_after_stop(self):
        bridge = AsyncioBridge()
        await bridge.start()
        await bridge.stop()
        with pytest.raises(AsyncioBridgeError, match="not running"):
            await bridge.run_coro(self._noop())

    @staticmethod
    async def _add(a: int, b: int) -> int:
        await asyncio.sleep(0)
        return a + b

    @staticmethod
    async def _noop() -> None:
        await asyncio.sleep(0)

    @staticmethod
    async def _make_bytes(n: int) -> bytes:
        await asyncio.sleep(0)
        return b"\x42" * n


# ---------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------


class TestErrorPropagation:
    @pytest.mark.trio
    async def test_value_error_propagates(self):
        async with AsyncioBridge() as bridge:
            with pytest.raises(ValueError, match="boom"):
                await bridge.run_coro(self._raise_value_error())

    @pytest.mark.trio
    async def test_runtime_error_propagates(self):
        async with AsyncioBridge() as bridge:
            with pytest.raises(RuntimeError, match="oops"):
                await bridge.run_coro(self._raise_runtime_error())

    @pytest.mark.trio
    async def test_custom_exception_propagates(self):
        async with AsyncioBridge() as bridge:
            with pytest.raises(_CustomError, match="custom"):
                await bridge.run_coro(self._raise_custom())

    @pytest.mark.trio
    async def test_exception_does_not_kill_bridge(self):
        """After an error, the bridge should still be usable."""
        async with AsyncioBridge() as bridge:
            with pytest.raises(ValueError):
                await bridge.run_coro(self._raise_value_error())
            # Bridge should still work
            result = await bridge.run_coro(self._return_ok())
            assert result == "ok"

    @staticmethod
    async def _raise_value_error() -> None:
        raise ValueError("boom")

    @staticmethod
    async def _raise_runtime_error() -> None:
        raise RuntimeError("oops")

    @staticmethod
    async def _raise_custom() -> None:
        raise _CustomError("custom")

    @staticmethod
    async def _return_ok() -> str:
        return "ok"


class _CustomError(Exception):
    pass


# ---------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------


class TestConcurrency:
    @pytest.mark.trio
    async def test_concurrent_coroutines(self):
        """Run 50 concurrent coroutines through the bridge."""
        async with AsyncioBridge() as bridge:
            results: list[int] = []

            async def _run_one(i: int) -> None:
                val = await bridge.run_coro(self._delayed_return(i, 0.01))
                results.append(val)

            async with trio.open_nursery() as nursery:
                for i in range(50):
                    nursery.start_soon(_run_one, i)

            assert sorted(results) == list(range(50))

    @pytest.mark.trio
    async def test_100_rapid_fire(self):
        """100 coroutines with no artificial delay."""
        async with AsyncioBridge() as bridge:
            results = []

            async def _run(i: int) -> None:
                val = await bridge.run_coro(self._immediate_return(i))
                results.append(val)

            async with trio.open_nursery() as nursery:
                for i in range(100):
                    nursery.start_soon(_run, i)

            assert len(results) == 100
            assert set(results) == set(range(100))

    @pytest.mark.trio
    async def test_mixed_success_and_failure(self):
        """Some coroutines succeed, some fail — bridge survives both."""
        async with AsyncioBridge() as bridge:
            successes = []
            failures = []

            async def _run(i: int) -> None:
                try:
                    if i % 3 == 0:
                        await bridge.run_coro(self._raise_if_divisible())
                    else:
                        val = await bridge.run_coro(self._immediate_return(i))
                        successes.append(val)
                except ValueError:
                    failures.append(i)

            async with trio.open_nursery() as nursery:
                for i in range(30):
                    nursery.start_soon(_run, i)

            # 10 failures (0, 3, 6, ..., 27), 20 successes
            assert len(failures) == 10
            assert len(successes) == 20

    @staticmethod
    async def _delayed_return(val: int, delay: float) -> int:
        await asyncio.sleep(delay)
        return val

    @staticmethod
    async def _immediate_return(val: int) -> int:
        return val

    @staticmethod
    async def _raise_if_divisible() -> None:
        raise ValueError("divisible by 3")


# ---------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------


class TestCancellation:
    @pytest.mark.trio
    async def test_trio_cancel_scope_unblocks(self):
        """Cancelling a trio scope unblocks run_coro immediately."""
        async with AsyncioBridge() as bridge:

            async def _slow_asyncio_coro() -> None:
                await asyncio.sleep(999)

            scope = trio.CancelScope(deadline=trio.current_time() + 0.1)
            with scope:
                await bridge.run_coro(_slow_asyncio_coro())
                pytest.fail("Should have been cancelled by deadline")

            assert scope.cancelled_caught, "Cancel scope did not fire"

    @pytest.mark.trio
    async def test_bridge_works_after_cancel(self):
        """After a scope cancellation, the bridge remains usable."""
        async with AsyncioBridge() as bridge:

            async def _slow() -> None:
                await asyncio.sleep(999)

            scope = trio.CancelScope(deadline=trio.current_time() + 0.1)
            with scope:
                await bridge.run_coro(_slow())

            assert scope.cancelled_caught, "Cancel scope did not fire"

            # Give the asyncio loop a moment to clean up the cancelled future
            await trio.sleep(0.05)

            # Bridge should still work
            result = await bridge.run_coro(_return_42())
            assert result == 42


# ---------------------------------------------------------------
# Fire-and-forget
# ---------------------------------------------------------------


class TestFireAndForget:
    @pytest.mark.trio
    async def test_fire_and_forget_runs(self):
        async with AsyncioBridge() as bridge:
            flag: list[bool] = []

            async def _set_flag() -> None:
                flag.append(True)

            bridge.schedule_fire_and_forget(_set_flag())
            await trio.sleep(0.1)  # Give it time to run
            assert flag == [True]

    @pytest.mark.trio
    async def test_fire_and_forget_error_is_logged_not_raised(self):
        async with AsyncioBridge() as bridge:

            async def _explode() -> None:
                raise RuntimeError("kaboom")

            # Should not raise
            bridge.schedule_fire_and_forget(_explode())
            await trio.sleep(0.1)
            # Bridge still alive
            assert bridge.is_running

    @pytest.mark.trio
    async def test_fire_and_forget_on_stopped_bridge(self):
        bridge = AsyncioBridge()

        async def _noop() -> None:
            pass

        # Should not raise — just silently discards
        bridge.schedule_fire_and_forget(_noop())


# ---------------------------------------------------------------
# Stress
# ---------------------------------------------------------------


class TestStress:
    @pytest.mark.trio
    async def test_sequential_start_stop_cycles(self):
        """Create and destroy 10 bridges sequentially."""
        for _ in range(10):
            async with AsyncioBridge() as bridge:
                result = await bridge.run_coro(_return_42())
                assert result == 42

    @pytest.mark.trio
    async def test_many_small_coros(self):
        """500 trivial coroutines to check for resource leaks."""
        async with AsyncioBridge() as bridge:
            for i in range(500):
                result = await bridge.run_coro(_return_42())
                assert result == 42


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------


async def _return_42() -> int:
    return 42
