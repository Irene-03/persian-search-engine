"""
Utility Functions for Web Crawler

This module provides various utility functions and classes for:
- URL normalization and handling
- Rate limiting
- Hashing functions
"""

import hashlib
import threading
from urllib.parse import urlsplit, urlunsplit, urljoin, urldefrag, quote, unquote

def sha256_hex(s: str) -> str:
    """
    Calculate SHA-256 hash of a string.
    
    Args:
        s (str): Input string
        
    Returns:
        str: Hexadecimal representation of SHA-256 hash
    """
    return hashlib.sha256(s.encode('utf-8','ignore')).hexdigest()

def normalize_url(base: str, href: str):
    """
    Normalize a URL by applying various transformations.
    
    Transformations:
    - Convert relative to absolute URLs
    - Remove fragments
    - Normalize case of scheme and host
    - Remove default ports (80/443)
    - Normalize path encoding
    
    Args:
        base (str): Base URL for resolving relative URLs
        href (str): URL or relative path to normalize
        
    Returns:
        str or None: Normalized URL, or None if invalid
    """
    try:
        # Convert relative to absolute URL
        abs_url = urljoin(base, href)
        # Remove fragment
        abs_url, _ = urldefrag(abs_url)
        # Split URL into components
        parts = list(urlsplit(abs_url))
        # Normalize scheme and host
        parts[0] = parts[0].lower()  # scheme
        parts[1] = parts[1].lower()  # netloc
        # Remove default ports
        if parts[1].endswith(':80') and parts[0] == 'http':
            parts[1] = parts[1][:-3]
        if parts[1].endswith(':443') and parts[0] == 'https':
            parts[1] = parts[1][:-4]
        # Normalize path encoding
        parts[2] = quote(unquote(parts[2]))
        return urlunsplit(parts)
    except Exception:
        return None

class RateLimiter:
    """
    Thread-safe rate limiter for controlling request rates per key (e.g., per host).
    
    Features:
    - Minimum delay between requests
    - Thread-safe operation
    - Per-key rate limiting
    - Race condition protection
    """
    
    def __init__(self, min_delay: float):
        """
        Initialize rate limiter.
        
        Args:
            min_delay (float): Minimum delay between requests in seconds
        """
        self.min_delay = max(0.0, float(min_delay))
        self.lock = threading.Lock()
        self.last = {}  # Last request time per key

    def wait(self, key: str):
        """
        Wait if needed to maintain minimum delay between requests.
        
        Thread-safe implementation that prevents race conditions by
        using request time for calculations.
        
        Args:
            key (str): Key to rate limit on (e.g., hostname)
        """
        if self.min_delay <= 0:
            return
            
        import time
        with self.lock:
            now = time.time()
            last = self.last.get(key, 0.0)
            delay = self.min_delay - (now - last)
            if delay > 0:
                time.sleep(delay)
            # Use 'now' to prevent race conditions
            self.last[key] = now + delay

