# async_service Migration Proof of Concept

This directory contains a proof of concept for migrating the existing `async_service` implementation in py-libp2p to a simpler, more maintainable implementation based on [anyio](https://github.com/agronholm/anyio).

## Background

The current `async_service` implementation in py-libp2p was copied from the now unmaintained [ethereum/async-service](https://github.com/ethereum/async-service) repository. This proof of concept demonstrates how we could replace it with a streamlined implementation that leverages modern Python concurrency libraries.

## Benefits of Migration

1. **Reduced Maintenance Burden**: By using anyio, we delegate the complex concurrency management to a well-maintained library.
1. **Simplified Implementation**: The new implementation is significantly simpler (~400 lines vs. ~1000 lines) while preserving the core functionality.
1. **Backend Agnostic**: The solution works with both Trio and asyncio through anyio's abstraction.
1. **Modern Structured Concurrency**: Leverages anyio's task groups for cleaner task management and error propagation.
1. **Preserved API Surface**: Existing code using `async_service` can be migrated with minimal changes.

## Implementation Details

The implementation maintains the core concepts from the original:

- `ServiceAPI` and `Service` base class for defining services
- Manager for lifecycle and task management
- Support for daemon tasks and child services
- Task statistics tracking
- Error propagation and cancellation

The key changes are:

- Uses anyio's structured concurrency primitives (`TaskGroup` and `CancelScope`)
- Simplified task tracking and cancellation logic
- Cleaner implementation of service lifecycle management

## Migration Path

For existing services, the migration would typically involve:

1. Updating imports to point to the new implementation
1. Testing to ensure behavior is preserved
1. Potentially adjusting code that relied on implementation details

No changes should be needed to the service interface itself, as the API remains largely compatible.

## Requirements

- Python 3.8+
- anyio

## Example Usage

```python
from service.base import Service
from service.manager import AnyIOManager

class MyService(Service):
    async def run(self):
        # Schedule background tasks
        self.manager.run_daemon_task(self.background_task)

        # Main service logic
        while True:
            await self.process_data()
            if self.manager.is_cancelled:
                break

    async def background_task(self):
        while True:
            await self.monitor_something()

# Run the service
await AnyIOManager.run_service(MyService())
```

See the `examples/` directory for more detailed examples.

## Next Steps

If this approach is accepted:

1. Add comprehensive tests
1. Create a full implementation with documentation
1. Update existing py-libp2p services to use the new implementation
1. Remove the old implementation
