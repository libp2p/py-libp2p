"""
Block Pricing Engine for Bitswap 1.3.0 - Root CID Pricing.

Computes prices for files/DAGs based on total size, not individual blocks.
Supports configurable pricing strategies:
- Free: All blocks are free (price = 0)
- Fixed: Fixed price per file regardless of size
- Size-based: Price scales with total file size (units per KB)
- Custom: User-defined pricing function
"""

from collections.abc import Callable
import logging

logger = logging.getLogger(__name__)


class BlockPricingEngine:
    """
    Computes prices for Bitswap blocks based on configurable strategies.

    Pricing is typically done at the root CID level (total file size),
    not per-block, to avoid charging for each chunk separately.

    Example:
        >>> # Size-based pricing: 100 micro-USDC per KB
        >>> pricing = BlockPricingEngine(
        ...     strategy="size_based",
        ...     units_per_kb=100,
        ... )
        >>>
        >>> # 5 MB file = 5000 KB × 100 = 500,000 micro-units = $0.50
        >>> price = pricing.compute_price("bafyroot...", block_size=5_000_000)
        >>> print(f"${price / 1_000_000:.2f}")  # $0.50
        >>>
        >>> # Mark specific CIDs as free
        >>> pricing.set_free("bafyfree123...")
        >>> pricing.compute_price("bafyfree123...", 1_000_000)  # 0 (free)

    """

    def __init__(
        self,
        strategy: str = "size_based",
        units_per_kb: float = 100.0,
        fixed_price: int = 0,
        custom_pricing_fn: Callable[[str, int], int] | None = None,
        default_free: bool = False,
    ):
        """
        Initialize pricing engine.

        Args:
            strategy: Pricing strategy - "free", "fixed", "size_based", or "custom"
            units_per_kb: Price per KB for size_based strategy (micro-units)
            fixed_price: Fixed price for "fixed" strategy (micro-units)
            custom_pricing_fn: Custom function(cid_str, size) → price
                               for "custom" strategy
            default_free: If True, all CIDs are free by default

        Strategies:
            - "free": Always return 0 (all blocks free)
            - "fixed": Return fixed_price for all blocks
            - "size_based": price = max(1, int(size_kb * units_per_kb))
            - "custom": Use custom_pricing_fn(cid_str, block_size)

        """
        self.strategy = strategy
        self.units_per_kb = units_per_kb
        self.fixed_price = fixed_price
        self.custom_pricing_fn = custom_pricing_fn
        self.default_free = default_free

        # Per-CID overrides: cid_hex → price (0 = free, >0 = specific price)
        self._cid_prices: dict[str, int] = {}

        logger.info(
            f"Pricing engine initialized: strategy={strategy} "
            f"units_per_kb={units_per_kb} default_free={default_free}"
        )

    def set_price(self, cid: str | bytes, price: int) -> None:
        """
        Set a specific price for a CID (overrides strategy).

        Args:
            cid: The CID (hex string or bytes)
            price: Price in micro-units (0 = free)

        """
        cid_hex = _cid_to_hex(cid)
        self._cid_prices[cid_hex] = price
        logger.info(f"Set price for {cid_hex[:20]}... = {price} units")

    def set_free(self, cid: str | bytes) -> None:
        """
        Mark a CID as free (price = 0).

        Args:
            cid: The CID to mark as free

        """
        self.set_price(cid, 0)

    def compute_price(self, cid_str: str, block_size: int) -> int:
        """
        Compute the price for a block/file.

        Args:
            cid_str: The CID as a hex string
            block_size: Size in bytes (for root CID, this is total file size)

        Returns:
            Price in micro-units (0 = free, >0 = paid)

        Note:
            For multi-block files, call this ONCE with the root CID and total size,
            not for each individual chunk.

        """
        # Check for per-CID override
        if cid_str in self._cid_prices:
            price = self._cid_prices[cid_str]
            logger.debug(f"Using override price for {cid_str[:20]}... = {price}")
            return price

        # Apply default free policy
        if self.default_free:
            return 0

        # Apply strategy
        if self.strategy == "free":
            return 0

        elif self.strategy == "fixed":
            return self.fixed_price

        elif self.strategy == "size_based":
            # Price = units_per_kb × size_in_kb (minimum 1 unit)
            kb = block_size / 1024
            price = max(1, int(kb * self.units_per_kb))
            logger.debug(
                f"Size-based pricing: {block_size}B = {kb:.2f}KB × "
                f"{self.units_per_kb} = {price} units"
            )
            return price

        elif self.strategy == "custom":
            if self.custom_pricing_fn is None:
                raise ValueError("Custom strategy requires custom_pricing_fn")
            return self.custom_pricing_fn(cid_str, block_size)

        else:
            raise ValueError(f"Unknown pricing strategy: {self.strategy}")

    def get_units_per_kb(self) -> float:
        """
        Get the current units_per_kb rate (for size_based strategy).

        Returns:
            Units per KB, or 0.0 if not using size_based strategy

        """
        if self.strategy == "size_based":
            return self.units_per_kb
        return 0.0


# ── Helper functions ──────────────────────────────────────────────────────────


def _cid_to_hex(cid: str | bytes) -> str:
    """Convert CID to hex string for consistent storage."""
    if isinstance(cid, bytes):
        return cid.hex()
    elif isinstance(cid, str):
        # If already hex, return as-is
        try:
            bytes.fromhex(cid)
            return cid
        except ValueError:
            # Assume it's a base58/base32 encoded CID string
            return cid.encode().hex()
    else:
        raise TypeError(f"CID must be str or bytes, got {type(cid)}")
