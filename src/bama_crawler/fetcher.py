"""
Web Page Fetcher Module

This module handles the fetching of web pages with features including:
- Rate limiting and polite crawling
- JavaScript rendering support
- CAPTCHA detection
- Proxy support
- Retry handling
- Response timing
"""

import requests
import time
import logging
from datetime import datetime, timezone
import email.utils as eut
from urllib.parse import urlsplit
from requests.exceptions import RequestException, Timeout, SSLError, ProxyError
from playwright.sync_api import sync_playwright

from .utils import RateLimiter

logger = logging.getLogger("fetcher")

class Fetcher:
    """
    A web page fetcher with support for JavaScript rendering and rate limiting.
    
    This class handles HTTP requests with features like:
    - Configurable delays between requests
    - Automatic retries
    - Optional JavaScript rendering
    - CAPTCHA detection
    - Proxy support
    - Polite crawling with user agent and contact information
    """
    
    def __init__(self, user_agent: str, timeout: int, retries: int, delay: float,
                 proxy=None, enable_render=True, contact_email: str | None = None):
        """
        Initialize the fetcher with the specified configuration.
        
        Args:
            user_agent (str): User agent string to identify the crawler
            timeout (int): Request timeout in seconds
            retries (int): Number of retry attempts for failed requests
            delay (float): Minimum delay between requests to the same host
            proxy (str, optional): Proxy server URL
            enable_render (bool): Whether to enable JavaScript rendering
            contact_email (str, optional): Contact email for crawler identification
        """
        self.user_agent = user_agent
        self.timeout = timeout
        self.retries = retries
        self.delay = delay
        self.proxy = proxy
        self.enable_render = enable_render
        self.contact_email = contact_email

        # Initialize requests session with proper headers
        self.session = requests.Session()
        headers = {"User-Agent": self.user_agent}
        if self.contact_email:
            headers["From"] = self.contact_email  # Identify crawler operator
        self.session.headers.update(headers)
        if self.proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})

        # Per-host rate limiting
        self._rate = RateLimiter(delay)

    def _detect_captcha(self, html: str) -> bool:
        """
        Detect if a page contains a CAPTCHA challenge.
        
        Performs simple text-based detection of common CAPTCHA implementations
        and challenge pages.
        
        Args:
            html (str): The HTML content to check
            
        Returns:
            bool: True if CAPTCHA is detected, False otherwise
        """
        if not html:
            return False
        lower = html.lower()
        keys = [
            "captcha", "g-recaptcha", "hcaptcha",
            "cf-challenge", "cf-turnstile",
            "are you human", "bot verification", "attention required"
        ]
        return any(k in lower for k in keys)

    def _parse_retry_after(self, value: str) -> int:
        """
        Parse the Retry-After header value to determine wait time.
        
        Handles both delta-seconds and HTTP-date formats according to RFC 7231.
        
        Args:
            value (str): The Retry-After header value
            
        Returns:
            int: Number of seconds to wait (>= 0). Returns 0 if parsing fails.
        """
        if not value:
            return 0
        v = value.strip()
        
        # Handle delta-seconds format
        if v.isdigit():
            try:
                return max(0, int(v))
            except Exception:
                return 0
                
        # Handle HTTP-date format
        try:
            dt = eut.parsedate_to_datetime(v)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            wait = int((dt - datetime.now(timezone.utc)).total_seconds())
            return max(0, wait)
        except Exception:
            return 0

    def fetch(self, url: str):
        """
        Fetch a URL with automatic retries and JavaScript rendering support.
        
        Features:
        - Rate limiting per host
        - Automatic retries with backoff
        - Respects Retry-After headers
        - Optional JavaScript rendering
        - CAPTCHA detection
        
        Args:
            url (str): The URL to fetch
            
        Returns:
            tuple: (
                status_code: int or None,
                headers: dict,
                content: bytes,
                elapsed_time: float,
                error: str or None
            )
        """
        last_err = None
        start = time.time()
        host = urlsplit(url).netloc
        logger.debug(f"Starting fetch for {url}")

        for attempt in range(1, self.retries + 2):
            try:
                # Apply per-host rate limiting
                self._rate.wait(host)
                logger.debug(f"Attempt {attempt} for {url}")

                # Make the request
                resp = self.session.get(url, timeout=self.timeout)
                ct = resp.headers.get("Content-Type", "") or ""
                status = resp.status_code
                content = resp.text

                # Handle rate limiting responses (429 Too Many Requests, 503 Service Unavailable)
                if status in (429, 503):
                    ra = resp.headers.get("Retry-After", "")
                    wait = self._parse_retry_after(ra)
                    if wait > 0:
                        logger.warning(f"⏳ Retry-After {wait}s for {url}")
                        time.sleep(min(wait, 120))  # Cap at reasonable maximum
                    raise RequestException(f"retryable status {status}")

                # Handle JavaScript-heavy pages with rendering if enabled
                if self.enable_render and "text/html" in ct and self._looks_js_page(content):
                    logger.debug(f"🔄 Rendering with Playwright: {url}")
                    rendered_html = self._render_with_playwright(url)
                    if rendered_html:
                        content = rendered_html
                        status = 200

                elapsed = time.time() - start

                # Check for CAPTCHA challenges
                if "text/html" in ct:
                    text = content if isinstance(content, str) else str(content)
                    if self._detect_captcha(text):
                        return status, resp.headers, text.encode("utf-8", "ignore"), elapsed, "CAPTCHA_DETECTED"

                # Return successful response
                return status, resp.headers, content.encode("utf-8"), elapsed, None

            except (RequestException, Timeout, ProxyError, SSLError) as e:
                last_err = str(e)
                time.sleep(1.0 * attempt)  # Simple exponential backoff

        # Return error state after all retries exhausted
        elapsed = time.time() - start
        return None, {}, b"", elapsed, last_err

    def _looks_js_page(self, html: str) -> bool:
        """
        Detect if a page appears to be JavaScript-heavy or a Single Page Application.
        
        Checks for common SPA frameworks and patterns, including:
        - Vue.js root elements
        - Next.js identifiers
        - Redux/Vuex state containers
        - Minimal initial HTML (likely requiring JS for content)
        
        Args:
            html (str): The HTML content to analyze
            
        Returns:
            bool: True if the page appears to require JavaScript rendering
        """
        lower = html.lower()
        return (
            "<div id=\"app\"" in lower or      # Vue.js
            "<div id='app'" in lower or        # Vue.js (single quotes)
            "id=\"__next\"" in lower or        # Next.js
            "window.__INITIAL_STATE__" in lower or  # Vuex/Redux state
            len(html.strip()) < 1000           # Minimal initial HTML
        )

    def _render_with_playwright(self, url: str) -> str:
        """
        Render a JavaScript-heavy page using Playwright.
        
        Features:
        - Headless Chrome browser
        - Anti-bot detection evasion
        - Full page scrolling for lazy-loaded content
        - Configurable viewport and locale settings
        
        Args:
            url (str): The URL to render
            
        Returns:
            str: The rendered HTML content, or None if rendering fails
        """
        try:
            with sync_playwright() as p:
                # Launch browser with anti-detection settings
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",  # Hide automation
                        "--no-sandbox", "--disable-dev-shm-usage",        # Container compatibility
                        "--disable-gpu", "--disable-extensions"           # Performance
                    ]
                )
                
                # Configure browser context
                context = browser.new_context(
                    user_agent=self.user_agent,
                    viewport={"width": 1366, "height": 768},  # Standard desktop size
                    java_script_enabled=True,
                    locale="fa-IR",                           # Persian locale
                    timezone_id="Asia/Tehran"                 # Iran timezone
                )
                
                # Navigate and scroll
                page = context.new_page()
                page.goto(url, wait_until="networkidle", timeout=self.timeout * 1000)
                
                # Scroll to load lazy content
                page.evaluate("""
                    async () => {
                        let totalHeight = 0;
                        let distance = 800;
                        while (totalHeight < document.body.scrollHeight) {
                            window.scrollBy(0, distance);
                            totalHeight += distance;
                            await new Promise(r => setTimeout(r, 600));
                        }
                    }
                """)
                
                # Ensure all content is loaded
                time.sleep(2)
                page.wait_for_load_state("networkidle", timeout=self.timeout * 1000)
                
                # Get final HTML and cleanup
                html = page.content()
                context.close()
                browser.close()
                return html
                
        except Exception as e:
            logger.warning(f"Playwright render failed for {url}: {e}")
            return None
