"""
DNS resolution utilities with retry, exponential backoff, and optional timeout.

Used by bootstrap discovery and transports (TCP, WebSocket) for consistent
DNS resolution behavior and optional metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

from multiaddr import Multiaddr
from multiaddr.resolvers import DNSResolver

logger = logging.getLogger(__name__)


@dataclass
class DNSResolutionMetrics:
    """Simple metrics for DNS resolution (success/failure counts)."""

    success_count: int = 0
    failure_count: int = 0

    def record_success(self) -> None:
        self.success_count += 1

    def record_failure(self) -> None:
        self.failure_count += 1


# Module-level optional metrics (optional use)
_default_metrics: DNSResolutionMetrics | None = None


def get_default_dns_metrics() -> DNSResolutionMetrics | None:
    """Return the default DNS metrics instance if set."""
    return _default_metrics


def set_default_dns_metrics(metrics: DNSResolutionMetrics | None) -> None:
    """Set the default DNS metrics instance (e.g. for bootstrap or host)."""
    global _default_metrics
    _default_metrics = metrics


async def resolve_multiaddr_with_retry(
    maddr: Multiaddr,
    resolver: DNSResolver | None = None,
    *,
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    timeout_seconds: float | None = 10.0,
    metrics: DNSResolutionMetrics | None = None,
) -> list[Multiaddr] | None:
    """
    Resolve a DNS multiaddr with retries and exponential backoff.

    :param maddr: Multiaddr to resolve (dns/dns4/dns6/dnsaddr as first protocol).
    :param resolver: DNSResolver instance; if None, a new one is created.
    :param max_retries: Maximum number of resolution attempts (including first).
    :param base_delay: Initial delay in seconds before first retry.
    :param max_delay: Maximum delay in seconds between retries.
    :param timeout_seconds: Per-attempt timeout in seconds; None for no timeout.
    :param metrics: Optional metrics to record success/failure.
    :return: List of resolved Multiaddrs, or None if all attempts failed.
    """
    import trio

    if resolver is None:
        resolver = DNSResolver()

    used_metrics = metrics or get_default_dns_metrics()
    delay = base_delay
    last_error: Exception | None = None

    for attempt in range(max_retries):
        result: list[Multiaddr] | None = None
        try:
            if timeout_seconds is not None and timeout_seconds > 0:
                with trio.move_on_after(timeout_seconds) as cancel_scope:
                    result = await resolver.resolve(maddr)
                # Distinguish: timeout vs no-addresses vs success via cancel scope.
                # Timeout: cancel_scope.cancelled_caught is True.
                # No addresses: scope not cancelled, result is [] or None.
                # Success: scope not cancelled and result non-empty.
                if cancel_scope.cancelled_caught:
                    last_error = TimeoutError(
                        f"DNS resolution timed out after {timeout_seconds}s"
                    )
                elif not result:
                    last_error = ValueError("Resolver returned no addresses")
                else:
                    if used_metrics:
                        used_metrics.record_success()
                    return result
            else:
                result = await resolver.resolve(maddr)
                if not result:
                    last_error = ValueError("Resolver returned no addresses")
                else:
                    if used_metrics:
                        used_metrics.record_success()
                    return result
        # Re-raise trio.Cancelled; timeouts are handled via cancel_scope.
        except trio.Cancelled:
            raise
        # Catch all other exceptions during DNS resolution attempts.
        except Exception as e:
            # Record the exception as the last error encountered.
            last_error = e
            # Log this attempt's failure; retries continue.
            logger.debug(
                "DNS resolution attempt %s/%s failed for %s: %s",
                attempt + 1,
                max_retries,
                maddr,
                e,
            )

        if used_metrics:
            used_metrics.record_failure()

        if attempt < max_retries - 1:
            logger.debug(
                "Retrying DNS resolution for %s in %.2fs",
                maddr,
                delay,
            )
            await trio.sleep(delay)
            delay = min(delay * 2, max_delay)

    logger.warning(
        "DNS resolution failed after %s attempts for %s: %s",
        max_retries,
        maddr,
        last_error,
    )
    return None


__all__ = [
    "DNSResolutionMetrics",
    "get_default_dns_metrics",
    "resolve_multiaddr_with_retry",
    "set_default_dns_metrics",
]
