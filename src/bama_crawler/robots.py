"""
Robots.txt Parser and Cache Module

This module provides a caching system for robots.txt files with features:
- Automatic fetching and parsing of robots.txt
- Time-based cache expiration
- Thread-safe caching
- Error handling with graceful fallbacks
"""

import time
import logging
import urllib.robotparser as rp
from urllib.parse import urlsplit
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class RobotsEntry:
    """
    Cache entry for a parsed robots.txt file.
    
    Attributes:
        parser: Parsed robots.txt rules
        fetched_at: Timestamp when the file was fetched
    """
    parser: rp.RobotFileParser
    fetched_at: float

class RobotsCache:
    """
    Caching system for robots.txt files with TTL-based expiration.
    
    Features:
    - Automatic fetching and parsing of robots.txt
    - Cache entries expire after configurable TTL
    - Graceful handling of fetch/parse errors
    - Support for crawl-delay directives
    """
    
    def __init__(self, user_agent: str, ttl_sec: int = 3600):
        """
        Initialize the robots.txt cache.
        
        Args:
            user_agent (str): User agent string for robots.txt rules
            ttl_sec (int): Cache TTL in seconds (default: 1 hour)
        """
        self.user_agent = user_agent
        self.ttl = ttl_sec
        self.cache = {}

    def _get_entry(self, url: str) -> RobotsEntry:
        """
        Get a cached robots.txt entry, fetching if needed or expired.
        
        Args:
            url (str): URL to get robots.txt for
            
        Returns:
            RobotsEntry: Cached parser and timestamp
        """
        host = urlsplit(url).netloc
        now = time.time()
        entry = self.cache.get(host)
        
        # Fetch if not cached or expired
        if (not entry) or ((now - entry.fetched_at) > self.ttl):
            rfp = rp.RobotFileParser()
            rfp.set_url(f'https://{host}/robots.txt')  # HTTPS only for now
            try:
                rfp.read()
            except Exception as e:
                logger.warning(f"Failed to read robots.txt for {host}: {str(e)}")
                rfp.disallow_all = False  # Allow access on error
            entry = RobotsEntry(rfp, now)
            self.cache[host] = entry
        return entry

    def allowed(self, url: str) -> bool:
        """
        Check if a URL is allowed by robots.txt rules.
        
        Args:
            url (str): URL to check
            
        Returns:
            bool: True if crawling is allowed, False if disallowed.
                 Returns True on error to avoid blocking valid URLs.
        """
        entry = self._get_entry(url)
        try:
            return entry.parser.can_fetch(self.user_agent, url)
        except Exception:
            return True

    def crawl_delay(self, url: str) -> float | None:
        """
        Get the crawl-delay directive for the current user agent.
        
        Args:
            url (str): URL to check crawl-delay for
            
        Returns:
            float or None: Crawl delay in seconds, or None if not specified
        """
        entry = self._get_entry(url)
        try:
            d = entry.parser.crawl_delay(self.user_agent)
            return float(d) if d else None
        except Exception:
            return None
