"""
Environment variable proxy configuration support.
Mimics Go's http.ProxyFromEnvironment functionality.
"""

import os
import logging
from urllib.parse import urlparse
from typing import Optional

logger = logging.getLogger(__name__)


def get_proxy_from_environment(target_url: str) -> Optional[str]:
    """
    Get proxy URL from environment variables.
    
    Mimics Go's http.ProxyFromEnvironment behavior:
    - Uses HTTP_PROXY for ws:// URLs
    - Uses HTTPS_PROXY for wss:// URLs
    - Checks both lowercase and uppercase variants
    - Returns None if NO_PROXY matches the target
    
    Args:
        target_url: The WebSocket URL being dialed (ws:// or wss://)
        
    Returns:
        Proxy URL string or None if no proxy configured
        
    Examples:
        >>> os.environ['HTTP_PROXY'] = 'socks5://localhost:1080'
        >>> get_proxy_from_environment('ws://example.com')
        'socks5://localhost:1080'
        
        >>> os.environ['HTTPS_PROXY'] = 'socks5://proxy.corp:1080'
        >>> get_proxy_from_environment('wss://example.com')
        'socks5://proxy.corp:1080'
    """
    try:
        parsed = urlparse(target_url)
        scheme = parsed.scheme.lower()
        
        # Determine which proxy environment variable to use
        if scheme == "wss":
            # For secure WebSocket, check HTTPS_PROXY
            proxy_url = (
                os.environ.get("HTTPS_PROXY") or 
                os.environ.get("https_proxy")
            )
        elif scheme == "ws":
            # For insecure WebSocket, check HTTP_PROXY
            proxy_url = (
                os.environ.get("HTTP_PROXY") or 
                os.environ.get("http_proxy")
            )
        else:
            logger.debug(f"Unknown scheme '{scheme}', no proxy detection")
            return None
        
        if not proxy_url:
            logger.debug(f"No proxy configured for {scheme}:// connections")
            return None
        
        if _should_bypass_proxy(parsed.hostname, parsed.port):
            logger.debug(
                f"Bypassing proxy for {parsed.hostname}:{parsed.port} "
                f"due to NO_PROXY setting"
            )
            return None
        
        logger.debug(f"Using proxy from environment for {target_url}: {proxy_url}")
        return proxy_url
        
    except Exception as e:
        logger.warning(f"Error reading proxy from environment: {e}")
        return None


def _should_bypass_proxy(hostname: Optional[str], port: Optional[int]) -> bool:
    """
    Check if the given hostname/port should bypass proxy based on NO_PROXY.
    
    NO_PROXY format (comma-separated):
    - Direct hostname: "localhost"
    - Domain suffix: ".example.com" or "example.com"
    - Wildcard: "*" (bypass all)
    - IP addresses: "127.0.0.1"
    
    Args:
        hostname: Target hostname
        port: Target port (currently not used in matching)
        
    Returns:
        True if proxy should be bypassed, False otherwise
    """
    if not hostname:
        return False
    
    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy")
    if not no_proxy:
        return False
    
    no_proxy_entries = [entry.strip() for entry in no_proxy.split(",")]
    
    hostname_lower = hostname.lower()
    
    for entry in no_proxy_entries:
        if not entry:
            continue
        
        entry_lower = entry.lower()
        
        if entry_lower == "*":
            logger.debug(f"NO_PROXY contains '*', bypassing all proxies")
            return True
        
        if entry_lower == hostname_lower:
            logger.debug(f"NO_PROXY direct match: {entry}")
            return True
        
        if entry_lower.startswith(".") and hostname_lower.endswith(entry_lower):
            logger.debug(f"NO_PROXY suffix match with dot: {entry}")
            return True
        
        if hostname_lower.endswith("." + entry_lower):
            logger.debug(f"NO_PROXY suffix match: {entry}")
            return True
        
        if entry_lower == hostname_lower:
            logger.debug(f"NO_PROXY exact match: {entry}")
            return True
    
    return False


def validate_proxy_url(proxy_url: str) -> bool:
    """
    Validate that a proxy URL has a supported scheme.
    
    Args:
        proxy_url: Proxy URL to validate
        
    Returns:
        True if valid and supported, False otherwise
    """
    try:
        parsed = urlparse(proxy_url)
        supported_schemes = ("socks4", "socks4a", "socks5", "socks5h")
        
        if parsed.scheme not in supported_schemes:
            logger.warning(
                f"Unsupported proxy scheme: {parsed.scheme}. "
                f"Supported: {supported_schemes}"
            )
            return False
        
        if not parsed.hostname:
            logger.warning(f"Proxy URL missing hostname: {proxy_url}")
            return False
        
        return True
        
    except Exception as e:
        logger.warning(f"Invalid proxy URL: {proxy_url} - {e}")
        return False
