"""
Adaptive delay utilities for error handling and retry mechanisms.

This module provides intelligent delay strategies that adapt based on error types
and retry attempts, replacing fixed delays with more efficient approaches.
"""

import logging
import random
import time
from enum import Enum
from typing import Dict, Optional

import trio

logger = logging.getLogger("libp2p.tools.adaptive_delays")


class ErrorType(Enum):
    """Classification of error types for adaptive delay strategies."""
    
    # Network-related errors that may be temporary
    NETWORK_TIMEOUT = "network_timeout"
    CONNECTION_REFUSED = "connection_refused"
    CONNECTION_RESET = "connection_reset"
    NETWORK_UNREACHABLE = "network_unreachable"
    
    # Resource-related errors
    RESOURCE_EXHAUSTED = "resource_exhausted"
    RATE_LIMITED = "rate_limited"
    
    # Protocol-related errors
    PROTOCOL_ERROR = "protocol_error"
    INVALID_MESSAGE = "invalid_message"
    
    # Persistent errors that shouldn't be retried immediately
    PERMISSION_DENIED = "permission_denied"
    INVALID_ARGUMENT = "invalid_argument"
    
    # Unknown errors
    UNKNOWN = "unknown"


class AdaptiveDelayStrategy:
    """
    Adaptive delay strategy that adjusts sleep times based on error type and retry count.
    
    This replaces fixed delays with intelligent backoff that:
    - Uses shorter delays for temporary network issues
    - Implements exponential backoff for persistent errors
    - Adds jitter to prevent thundering herd problems
    - Provides circuit breaker functionality
    """
    
    def __init__(
        self,
        base_delay: float = 0.001,  # 1ms base delay
        max_delay: float = 1.0,     # 1 second max delay
        backoff_multiplier: float = 2.0,
        jitter_factor: float = 0.1,
        max_retries: int = 5
    ):
        """
        Initialize the adaptive delay strategy.
        
        :param base_delay: Base delay in seconds for first retry
        :param max_delay: Maximum delay in seconds
        :param backoff_multiplier: Multiplier for exponential backoff
        :param jitter_factor: Factor for adding random jitter (0.0 to 1.0)
        :param max_retries: Maximum number of retries before giving up
        """
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_multiplier = backoff_multiplier
        self.jitter_factor = jitter_factor
        self.max_retries = max_retries
        
        # Error type specific delays (multipliers for base delay)
        self.error_delays = {
            ErrorType.NETWORK_TIMEOUT: 1.0,
            ErrorType.CONNECTION_REFUSED: 2.0,
            ErrorType.CONNECTION_RESET: 1.5,
            ErrorType.NETWORK_UNREACHABLE: 3.0,
            ErrorType.RESOURCE_EXHAUSTED: 5.0,
            ErrorType.RATE_LIMITED: 10.0,
            ErrorType.PROTOCOL_ERROR: 0.5,
            ErrorType.INVALID_MESSAGE: 0.5,
            ErrorType.PERMISSION_DENIED: 0.1,  # Very short delay, likely won't help
            ErrorType.INVALID_ARGUMENT: 0.1,   # Very short delay, likely won't help
            ErrorType.UNKNOWN: 2.0,
        }
        
        # Track retry counts per operation
        self.retry_counts: Dict[str, int] = {}
    
    def classify_error(self, error: Exception) -> ErrorType:
        """
        Classify an error to determine appropriate delay strategy.
        
        :param error: The exception to classify
        :return: ErrorType classification
        """
        error_name = type(error).__name__.lower()
        error_str = str(error).lower()
        
        # Network-related errors
        if any(keyword in error_name or keyword in error_str for keyword in 
               ['timeout', 'timed out', 'time out']):
            return ErrorType.NETWORK_TIMEOUT
        elif any(keyword in error_name or keyword in error_str for keyword in 
                 ['connection refused', 'refused', 'econnrefused']):
            return ErrorType.CONNECTION_REFUSED
        elif any(keyword in error_name or keyword in error_str for keyword in 
                 ['connection reset', 'reset', 'econnreset']):
            return ErrorType.CONNECTION_RESET
        elif any(keyword in error_name or keyword in error_str for keyword in 
                 ['network unreachable', 'unreachable', 'enunreach']):
            return ErrorType.NETWORK_UNREACHABLE
        
        # Resource-related errors
        elif any(keyword in error_name or keyword in error_str for keyword in 
                 ['resource', 'exhausted', 'memory', 'disk']):
            return ErrorType.RESOURCE_EXHAUSTED
        elif any(keyword in error_name or keyword in error_str for keyword in 
                 ['rate limit', 'throttle', 'too many']):
            return ErrorType.RATE_LIMITED
        
        # Protocol-related errors
        elif any(keyword in error_name or keyword in error_str for keyword in 
                 ['protocol', 'invalid protocol']):
            return ErrorType.PROTOCOL_ERROR
        elif any(keyword in error_name or keyword in error_str for keyword in 
                 ['invalid message', 'malformed', 'parse']):
            return ErrorType.INVALID_MESSAGE
        
        # Permission/argument errors
        elif any(keyword in error_name or keyword in error_str for keyword in 
                 ['permission', 'denied', 'forbidden']):
            return ErrorType.PERMISSION_DENIED
        elif any(keyword in error_name or keyword in error_str for keyword in 
                 ['invalid argument', 'bad argument', 'argument']):
            return ErrorType.INVALID_ARGUMENT
        
        return ErrorType.UNKNOWN
    
    def calculate_delay(
        self, 
        error: Exception, 
        operation_id: str = "default",
        retry_count: Optional[int] = None
    ) -> float:
        """
        Calculate adaptive delay based on error type and retry count.
        
        :param error: The exception that occurred
        :param operation_id: Unique identifier for the operation (for tracking retries)
        :param retry_count: Override retry count (if None, uses internal tracking)
        :return: Delay in seconds
        """
        if retry_count is None:
            self.retry_counts[operation_id] = self.retry_counts.get(operation_id, 0) + 1
            retry_count = self.retry_counts[operation_id]
        
        # Don't retry if we've exceeded max retries
        if retry_count > self.max_retries:
            return 0.0
        
        # Classify the error
        error_type = self.classify_error(error)
        
        # Get base delay for this error type
        error_multiplier = self.error_delays.get(error_type, 1.0)
        base_delay = self.base_delay * error_multiplier
        
        # Apply exponential backoff
        delay = base_delay * (self.backoff_multiplier ** (retry_count - 1))
        
        # Cap at maximum delay
        delay = min(delay, self.max_delay)
        
        # Add jitter to prevent thundering herd
        jitter = delay * self.jitter_factor * (2 * random.random() - 1)
        delay += jitter
        
        # Ensure delay is not negative
        delay = max(0.0, delay)
        
        logger.debug(
            f"Calculated adaptive delay: {delay:.4f}s for {error_type.value} "
            f"(retry {retry_count}/{self.max_retries})"
        )
        
        return delay
    
    async def sleep_for_error(
        self, 
        error: Exception, 
        operation_id: str = "default"
    ) -> bool:
        """
        Sleep for an adaptive delay based on the error.
        
        :param error: The exception that occurred
        :param operation_id: Unique identifier for the operation
        :return: True if should retry, False if max retries exceeded
        """
        delay = self.calculate_delay(error, operation_id)
        
        if delay <= 0:
            logger.debug(f"Max retries exceeded for operation {operation_id}")
            return False
        
        if delay > 0:
            logger.debug(f"Sleeping for {delay:.4f}s before retry")
            await trio.sleep(delay)
        
        return True
    
    def reset_retry_count(self, operation_id: str) -> None:
        """Reset retry count for a specific operation."""
        self.retry_counts.pop(operation_id, None)
    
    def get_retry_count(self, operation_id: str) -> int:
        """Get current retry count for an operation."""
        return self.retry_counts.get(operation_id, 0)


# Global instance for easy access
default_adaptive_delay = AdaptiveDelayStrategy()


async def adaptive_sleep(error: Exception, operation_id: str = "default") -> bool:
    """
    Convenience function for adaptive sleep with default strategy.
    
    :param error: The exception that occurred
    :param operation_id: Unique identifier for the operation
    :return: True if should retry, False if max retries exceeded
    """
    return await default_adaptive_delay.sleep_for_error(error, operation_id)
