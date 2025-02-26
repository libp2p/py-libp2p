"""
AnyIO-based manager implementation.
"""
import anyio
import inspect
import logging
import sys
from functools import wraps
from typing import Any, Awaitable, Callable, List, Optional, TypeVar

from .abc import ServiceAPI, ManagerAPI, InternalManagerAPI
from .exceptions import LifecycleError, DaemonTaskExit
from .stats import Stats, TaskStats

class AnyIOManager(InternalManagerAPI):
    """
    Manager implementation using anyio's structured concurrency.
    """
    logger = logging.getLogger("async_service.AnyIOManager")
    
    def __init__(self, service: ServiceAPI) -> None:
        if hasattr(service, "_manager"):
            raise LifecycleError("Service already has a manager.")
        else:
            service._manager = self
        
        self._service = service
        self._errors: List[tuple] = []
        
        # State flags
        self._started = False
        self._running = False
        self._cancelled = False
        self._finished = False
        
        # Task tracking
        self._total_task_count = 0
        self._done_task_count = 0
        
        # Event for tracking service lifecycle
        self._started_event = anyio.Event()
        self._finished_event = anyio.Event()
        
        # Task group for managing tasks
        self._task_group = None
        self._cancel_scope = None
    
    def __str__(self) -> str:
        status_flags = "".join(
            (
                "S" if self.is_started else "s",
                "R" if self.is_running else "r",
                "C" if self.is_cancelled else "c",
                "F" if self.is_finished else "f",
                "E" if self.did_error else "e",
            )
        )
        return f"<AnyIOManager[{self._service}] flags={status_flags}>"
    
    @property
    def is_started(self) -> bool:
        return self._started
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    @property
    def is_cancelled(self) -> bool:
        return self._cancelled
    
    @property
    def is_finished(self) -> bool:
        return self._finished
    
    @property
    def did_error(self) -> bool:
        return len(self._errors) > 0
    
    def cancel(self) -> None:
        if not self._cancelled and self._cancel_scope is not None:
            self._cancelled = True
            self._cancel_scope.cancel()
    
    async def stop(self) -> None:
        self.cancel()
        await self.wait_finished()
    
    async def wait_started(self) -> None:
        await self._started_event.wait()
    
    async def wait_finished(self) -> None:
        await self._finished_event.wait()
    
    @classmethod
    async def run_service(cls, service: ServiceAPI) -> None:
        manager = cls(service)
        await manager.run()
    
    async def run(self) -> None:
        if self._started:
            raise LifecycleError("Service already started")
        
        self._started = True
        self._running = True
        self._started_event.set()
        
        try:
            async with anyio.create_task_group() as task_group:
                self._task_group = task_group
                
                async with anyio.CancelScope() as cancel_scope:
                    self._cancel_scope = cancel_scope
                    
                    try:
                        # Run the service's main function
                        await self._service.run()
                    except Exception:
                        self._errors.append(sys.exc_info())
                        self.logger.exception(
                            "Service %s raised an exception", self._service
                        )
                        self.cancel()
        finally:
            self._running = False
            self._finished = True
            self._finished_event.set()
    
    def run_task(
        self, async_fn: Callable[..., Awaitable[Any]], 
        *args: Any, 
        daemon: bool = False, 
        name: str = None
    ) -> None:
        if not self.is_running:
            raise LifecycleError(
                "Tasks may not be scheduled if the service is not running"
            )
        
        if self.is_cancelled:
            self.logger.debug(
                "%s: service is being cancelled. Not running task %s", 
                self, 
                name or async_fn.__name__
            )
            return
        
        if name is None:
            name = getattr(async_fn, "__name__", repr(async_fn))
        
        self._total_task_count += 1
        
        async def _tracked_task() -> None:
            try:
                await async_fn(*args)
                if daemon:
                    raise DaemonTaskExit(f"Daemon task {name} exited")
            except anyio.get_cancelled_exc_class():
                self.logger.debug("%s: task %s cancelled", self, name)
                raise
            except DaemonTaskExit:
                if not self.is_cancelled:
                    self.logger.error("%s: daemon task %s exited", self, name)
                    self._errors.append(sys.exc_info())
                    self.cancel()
            except Exception:
                self.logger.exception("%s: task %s raised an exception", self, name)
                self._errors.append(sys.exc_info())
                self.cancel()
            finally:
                self._done_task_count += 1
        
        if self._task_group is not None:
            self._task_group.start_soon(_tracked_task)
    
    def run_daemon_task(
        self, async_fn: Callable[..., Awaitable[Any]], 
        *args: Any, 
        name: str = None
    ) -> None:
        self.run_task(async_fn, *args, daemon=True, name=name)
    
    def run_child_service(
        self, service: ServiceAPI, 
        daemon: bool = False, 
        name: str = None
    ) -> ManagerAPI:
        if hasattr(service, "_manager"):
            raise LifecycleError("Child service already has a manager")
        
        if name is None:
            name = str(service)
        
        child_manager = AnyIOManager(service)
        
        async def _run_child_service() -> None:
            try:
                await child_manager.run()
                if daemon and not self.is_cancelled:
                    raise DaemonTaskExit(f"Daemon child service {name} exited")
            except anyio.get_cancelled_exc_class():
                raise
            except Exception:
                if not self.is_cancelled:
                    self.logger.exception(
                        "%s: child service %s raised an exception", 
                        self, 
                        name
                    )
                    self._errors.append(sys.exc_info())
                    self.cancel()
        
        self.run_task(_run_child_service, name=f"ChildService:{name}")
        
        return child_manager
    
    def run_daemon_child_service(
        self, service: ServiceAPI, 
        name: str = None
    ) -> ManagerAPI:
        return self.run_child_service(service, daemon=True, name=name)
    
    @property
    def stats(self) -> Stats:
        total_count = max(0, self._total_task_count)
        finished_count = min(total_count, self._done_task_count)
        return Stats(
            tasks=TaskStats(total_count=total_count, finished_count=finished_count)
        )

async def run_service(service: ServiceAPI) -> ManagerAPI:
    """
    Run a service in the background.
    
    Returns a context manager that will start the service when entered and
    stop it when exited.
    """
    manager = AnyIOManager(service)
    
    async with anyio.create_task_group() as task_group:
        task_group.start_soon(manager.run)
        await manager.wait_started()
        try:
            yield manager
        finally:
            await manager.stop()

def background_service(service_fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[None]]:
    """
    Decorator to run a function as a background service.
    """
    @wraps(service_fn)
    async def inner(*args: Any, **kwargs: Any) -> None:
        service_type = as_service(service_fn)
        service = service_type(*args, **kwargs)
        await AnyIOManager.run_service(service)
    
    return inner