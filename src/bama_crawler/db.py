"""
Database Module for URL Frontier Management

This module provides a SQLite-based storage system for managing the crawler's frontier
and tracking visited URLs. It handles:
- URL queue management with priorities
- Visited URL tracking
- Thread-safe database operations
- Automatic schema creation and management
"""

import sqlite3, os, threading, logging
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

# Database schema definition
SCHEMA = (
    'CREATE TABLE IF NOT EXISTS frontier('
    ' url TEXT PRIMARY KEY,'           # URL to be crawled
    ' priority INTEGER NOT NULL,'      # URL priority for crawling order
    ' depth INTEGER NOT NULL,'         # Link depth from seed URL
    ' parent_url TEXT'                 # URL where this link was found
    ');'
    'CREATE INDEX IF NOT EXISTS idx_priority ON frontier(priority);'  # For efficient priority-based retrieval
    'CREATE TABLE IF NOT EXISTS seen('
    ' url TEXT PRIMARY KEY'            # URLs that have been processed
    ');'
)

class DB:
    """
    Thread-safe SQLite database manager for the crawler's frontier.
    
    Provides methods for:
    - Adding URLs to the frontier
    - Retrieving URLs in priority order
    - Tracking visited URLs
    - Managing concurrent database access
    """
    
    def __init__(self, path: str):
        """
        Initialize the database connection.
        
        Args:
            path (str): Path to the SQLite database file.
                       Directory will be created if it doesn't exist.
        """
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._lock = threading.Lock()  # Thread synchronization lock
        with self._conn() as c:
            c.executescript(SCHEMA)     # Initialize database schema

    @contextmanager
    def _conn(self):
        """
        Context manager for database connections.
        
        Provides thread-safe connection handling with:
        - 30 second connection timeout
        - Autocommit mode (isolation_level=None)
        - Automatic connection cleanup
        """
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            yield conn
        finally:
            conn.close()

    def push_url(self, url: str, priority: int, depth: int, parent_url: Optional[str]):
        """
        Add a URL to the frontier if it's not already present.
        
        Args:
            url (str): URL to add
            priority (int): Crawling priority (lower values crawled first)
            depth (int): Link depth from seed URL
            parent_url (Optional[str]): URL where this link was found
            
        Returns:
            bool: True if URL was added, False if it was duplicate
            
        Raises:
            sqlite3.Error: If database operation fails
        """
        if not url or len(url) > 2048:  # Enforce URL length limit
            return False
            
        try:
            with self._lock, self._conn() as c:
                cur = c.execute(
                    'INSERT OR IGNORE INTO frontier(url,priority,depth,parent_url) VALUES (?,?,?,?)',
                    (url, priority, depth, parent_url)
                )
                return (cur.rowcount == 1)  # True if inserted, False if ignored
        except sqlite3.Error as e:
            logger.error(f"Database error in push_url: {e}")
            raise

    def pop_batch(self, n: int):
        """
        Get and remove a batch of URLs from the frontier.
        
        Retrieves URLs in priority order (lowest first) and removes them
        from the frontier atomically.
        
        Args:
            n (int): Maximum number of URLs to retrieve
            
        Returns:
            list: Tuples of (url, priority, depth, parent_url)
        """
        with self._lock, self._conn() as c:
            rows = c.execute(
                'SELECT url,priority,depth,parent_url FROM frontier ORDER BY priority ASC LIMIT ?', 
                (n,)
            ).fetchall()
            if rows:
                urls = [r[0] for r in rows]
                c.executemany('DELETE FROM frontier WHERE url=?', [(u,) for u in urls])
            return rows

    def mark_seen(self, url: str) -> bool:
        """
        Mark a URL as visited and verify it was recorded.
        
        Args:
            url (str): URL to mark as visited
            
        Returns:
            bool: True if URL was found in seen table after marking
        """
        with self._lock, self._conn() as c:
            c.execute('INSERT OR IGNORE INTO seen(url) VALUES (?)', (url,))
            found = c.execute('SELECT 1 FROM seen WHERE url=?',(url,)).fetchone() is not None
            return found

    def is_seen(self, url: str) -> bool:
        """
        Check if a URL has been visited.
        
        Args:
            url (str): URL to check
            
        Returns:
            bool: True if URL has been visited
        """
        with self._lock, self._conn() as c:
            return c.execute('SELECT 1 FROM seen WHERE url=?',(url,)).fetchone() is not None

    def frontier_size(self) -> int:
        """
        Get the number of URLs remaining in the frontier.
        
        Returns:
            int: Number of unprocessed URLs in the frontier
        """
        with self._conn() as c:
            res = c.execute("SELECT COUNT(*) FROM frontier").fetchone()
            return res[0] if res else 0
