# Anyio Service Implementation

This module provides a robust async service implementation based on the anyio library. It offers a modern, actively maintained alternative to the previous async service implementation.

## Key Features

- Modern async primitives from anyio
- Full API compatibility with existing service implementations
- Improved performance and memory efficiency
- No task count limitations
- Robust error handling and task management
- Clean service lifecycle management

## Usage

```python
from libp2p.tools.anyio_service import Service, background_anyio_service

class MyService(Service):
    async def run(self):
        # Your service logic here
        pass

# Run service in background
async with background_anyio_service(MyService()) as manager:
    # Service is running
    pass
# Service is automatically cleaned up

# Or run service blocking
await AnyioManager.run_service(MyService())
```

## API

The implementation maintains the same public API as the previous async service implementation:

- `Service` - Base class for all services
- `ServiceAPI` - Interface defining service behavior
- `ManagerAPI` - Interface for service management
- `background_anyio_service()` - Context manager for running services
- `as_service()` - Decorator to create services from functions

## Benefits

- Eliminates reliance on unmaintained external codebase
- Leverages anyio's robust async primitives
- Reduces technical debt
- Improves maintainability
- Better error handling and task management
- No artificial task count limitations

## Migration

To migrate from the previous async service implementation:

1. Update imports to use `libp2p.tools.anyio_service` instead of `libp2p.tools.async_service`
1. No other code changes required - the API is fully compatible

## Requirements

- Python 3.7+
- anyio library
