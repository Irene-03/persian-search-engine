"""
Frontier Module - Web Crawler Core Component

This module implements the crawler's frontier management, which handles URL discovery,
scheduling, and crawling coordination. It provides mechanisms for:
- URL queue management and prioritization
- Concurrent crawling with adaptive control
- Domain-specific rate limiting
- Progress tracking and reporting
- Checkpoint/resume capability
- Real-time statistics and visualization
"""

import concurrent.futures as cf
import logging
import os
import threading
import sys
import platform
from collections import defaultdict, deque
from urllib.parse import urlsplit

from .db import DB
from .robots import RobotsCache
from .fetcher import Fetcher
from .storage import Storage, CrawlRecord
from .parser import extract_links, is_html_content, same_reg_domain
from .utils import sha256_hex, normalize_url

import signal
import time
import json
from tqdm import tqdm

# Suppress noisy matplotlib logging
logging.getLogger("matplotlib").setLevel(logging.WARNING)
logging.getLogger("matplotlib.font_manager").setLevel(logging.WARNING)

import matplotlib
matplotlib.use("Agg")  # Use non-interactive backend for plotting
import matplotlib.pyplot as plt


class Crawler:
    """
    Main crawler class that orchestrates the web crawling process.
    
    This class manages URL frontier, concurrency, rate limiting, and data collection.
    It provides mechanisms for resumable crawling with checkpointing and real-time
    control through keyboard commands.
    """
    
    def __init__(self, cfg: dict, data_root: str):
        """
        Initialize crawler with configuration and data storage paths.
        
        Args:
            cfg (dict): Configuration dictionary containing crawler parameters
            data_root (str): Root directory for storing crawl data and state
        """
        self.cfg = cfg
        self.data_root = data_root

        # Parse allowed domains (can be string or list)
        raw_allowed = cfg["allowed_domain"]
        if isinstance(raw_allowed, list):
            self.allowed_domain = raw_allowed[0].strip().lower()
        else:
            self.allowed_domain = str(raw_allowed).strip().lower()

        # Core crawling parameters
        self.max_pages = int(cfg["max_pages"])   # Target number of unique successful HTML pages
        self.max_depth = int(cfg["max_depth"])   # Maximum link depth to crawl

        # Core components initialization
        self.db = DB(os.path.join(data_root, "state", "crawler.sqlite"))  # Persistent state
        self.storage = Storage(os.path.join(data_root))                   # Data storage
        self.robots = RobotsCache(cfg["user_agent"], int(cfg["robots_cache_ttl_sec"]))

        # Configure fetcher with timeout, retries, and rate limiting
        self.fetcher = Fetcher(
            cfg["user_agent"],
            int(cfg["request_timeout_sec"]),
            int(cfg["max_retries"]),
            float(cfg["min_delay_per_host_sec"]),
            cfg.get("proxy"),
            bool(cfg.get("enable_render", False)),
            contact_email=cfg.get("contact_email")
        )

        # Crawler behavior flags
        self.store_html = bool(cfg.get("store_html", True))          # Save HTML content
        self.respect_robots = bool(cfg.get("respect_robots", True))  # Follow robots.txt
        self.follow_subdomains = bool(cfg.get("follow_subdomains", True))  # Include subdomains

        # Statistics counters
        self.pages_ok = 0                   # Successfully crawled HTML pages
        self.error_count = 0                # Failed requests
        self.non_html_count = 0             # Non-HTML successful responses
        self.robots_blocked_count = 0        # URLs blocked by robots.txt

        self.dup_seen = 0                   # URLs already marked as seen
        self.dup_insert_ignored = 0         # Duplicate URLs in frontier
        self.dup_count = 0                  # Total duplicates (seen + ignored)

        self.total_bytes_saved = 0          # Total size of saved HTML
        self.timings = []                   # List of (url, elapsed_sec) tuples

        # Track unique discovered links (based on normalized URLs)
        self._unique_internal = set()       # Internal links within allowed domain
        self._unique_external = set()       # External links to other domains
        self.internal_links_unique = 0      # Count of unique internal links
        self.external_links_unique = 0      # Count of unique external links

        # Per-host concurrency control
        self.max_concurrency_per_host = int(cfg.get("max_concurrency_per_host", 2))
        self._host_sema = defaultdict(lambda: threading.Semaphore(self.max_concurrency_per_host))

        # CAPTCHA detection and quarantine
        self.captcha_quarantine_sec = int(cfg.get("captcha_quarantine_sec", 900))  # 15 minutes
        self.quarantine = {}  # host -> quarantine_until_timestamp

        # Terminal control flags
        self.stop_flag = False              # Signal to stop crawling
        self.pause_flag = False             # Signal to pause crawling
        self._pause_cv = threading.Condition()  # Condition variable for pause/resume

        # Thread-safe counter lock
        self._ok_lock = threading.Lock()    # Prevent exceeding max_pages limit

        # Adaptive concurrent requests controller
        self.adaptive_enabled = bool(cfg.get("adaptive_enabled", True))
        self.inflight_limit = int(cfg.get("adaptive_min_inflight", 4))    # Current limit
        self.ad_min = int(cfg.get("adaptive_min_inflight", 4))           # Minimum concurrent requests
        self.ad_max = int(cfg.get("adaptive_max_inflight", 32))          # Maximum concurrent requests
        self.ad_step = int(cfg.get("adaptive_step", 2))                  # Step size for adjustments
        self.ad_low = float(cfg.get("adaptive_latency_low_ms", 500)) / 1000.0   # Target low latency
        self.ad_high = float(cfg.get("adaptive_latency_high_ms", 2000)) / 1000.0  # Target high latency
        self.ad_err_high = float(cfg.get("adaptive_error_high", 0.15))   # Error rate threshold
        self._lat_window = deque(maxlen=200)  # Rolling window of request latencies
        self._err_window = deque(maxlen=200)  # Rolling window of request errors

        # Checkpoint configuration for resume capability
        self.checkpoint_enabled = bool(cfg.get("checkpoint_enabled", True))
        self.checkpoint_interval = int(cfg.get("checkpoint_interval_sec", 10))
        self.pause_at_checkpoint = bool(cfg.get("pause_at_checkpoint", False))
        self._last_checkpoint = 0
        self.checkpoint_path = os.path.join(self.storage.reports_dir, "checkpoint.json")
        self._load_checkpoint_if_exists()

        # UI components
        self.start_time = time.time()  # Track crawl duration
        self._pbar = None              # Progress bar instance

    def _load_checkpoint_if_exists(self):
        """
        Load crawler state from checkpoint file if it exists.
        
        Loads essential counters from the checkpoint.json file to enable
        crawl resumption. Currently restores:
        - Number of successfully crawled pages
        - Counts of unique internal/external links discovered
        
        This allows the crawler to continue from where it left off without
        recrawling already visited pages.
        """
        if not os.path.exists(self.checkpoint_path):
            return
        try:
            with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                cp = json.load(f)
            # Restore essential counters
            self.pages_ok = int(cp.get("pages_ok", 0))
            # Restore link counters for reporting consistency
            self.internal_links_unique = int(cp.get("internal_links_unique", 0))
            self.external_links_unique = int(cp.get("external_links_unique", 0))
        except Exception as e:
            logging.getLogger("crawler").warning("checkpoint read failed: %s", e)

    def seed(self, seeds):
        """
        Initialize the crawler with seed URLs.
        
        If a previous crawl state exists (pages crawled or URLs in frontier),
        seeding is skipped to ensure proper resumption of the previous crawl.
        
        Args:
            seeds (list): List of initial URLs to start crawling from
        """
        try:
            frontier_left = self.db.frontier_size()
        except Exception:
            frontier_left = 0

        if self.pages_ok > 0 or frontier_left > 0:
            logging.info(f"Resume detected: pages_ok={self.pages_ok}, frontier_left={frontier_left}. Skip seeding.")
            return

        added = 0
        for s in seeds:
            normalized_url = normalize_url(s, "")
            if normalized_url:
                inserted = self.db.push_url(normalized_url, 0, 0, None)
                if not inserted:
                    self.dup_insert_ignored += 1
                else:
                    added += 1
        logging.info(f"Seeded {added} URL(s).")

    def pause(self):
        """
        Pause the crawler.
        
        Sets the pause flag and waits for worker threads to complete
        their current tasks before pausing.
        """
        with self._pause_cv:
            self.pause_flag = True

    def resume(self):
        """
        Resume a paused crawler.
        
        Clears the pause flag and notifies all waiting threads to continue.
        """
        with self._pause_cv:
            self.pause_flag = False
            self._pause_cv.notify_all()

    def stop(self):
        """
        Stop the crawler gracefully.
        
        Sets the stop flag and ensures any paused threads are resumed
        to allow proper shutdown.
        """
        self.stop_flag = True
        self.resume()

    def _start_key_listener(self):
        """
        Start a background thread to listen for keyboard commands.
        
        Provides interactive control of the crawler:
        - p: Pause crawling
        - r: Resume crawling
        - s: Stop crawling gracefully
        
        Uses platform-specific input handling for Windows and Unix systems.
        """
        if platform.system().lower().startswith("win"):
            import msvcrt
            def _loop():
                print("⌨️  Keys: [p]ause  [r]esume  [s]top")
                while not self.stop_flag:
                    if msvcrt.kbhit():
                        ch = msvcrt.getch()
                        if not ch:
                            continue
                        key = ch.decode('utf-8', errors='ignore').lower()
                        if key == 'p':
                            self.pause();  print("\n⏸️  Paused. Press [r] to resume...")
                        elif key == 'r':
                            self.resume(); print("\n▶️  Resumed.")
                        elif key == 's':
                            print("\n🛑 Stop requested."); self.stop(); break
                    time.sleep(0.05)
            threading.Thread(target=_loop, daemon=True).start()
        else:
            import tty, termios, select
            def _loop():
                print("⌨️  Keys: [p]ause  [r]esume  [s]top")
                fd = sys.stdin.fileno()
                old = termios.tcgetattr(fd)
                try:
                    tty.setcbreak(fd)
                    while not self.stop_flag:
                        dr, _, _ = select.select([sys.stdin], [], [], 0.05)
                        if dr:
                            ch = sys.stdin.read(1).lower()
                            if ch == 'p':
                                self.pause();  print("\n⏸️  Paused. Press [r] to resume...")
                            elif ch == 'r':
                                self.resume(); print("\n▶️  Resumed.")
                            elif ch == 's':
                                print("\n🛑 Stop requested."); self.stop(); break
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
            threading.Thread(target=_loop, daemon=True).start()

    def _signal_handler(self, sig, frame):
        """
        Handle system signals (e.g., SIGINT from Ctrl+C).
        
        Initiates graceful shutdown of the crawler:
        1. Prints shutdown message
        2. Sets stop flag to prevent new tasks
        3. Closes progress bar if active
        4. Allows active threads to complete
        
        Args:
            sig: Signal number
            frame: Current stack frame
        """
        print("\n🛑 Stopping crawler... please wait for active threads to finish.")
        self.stop()
        if self._pbar:
            self._pbar.close()

    def get_status_dict(self):
        """
        Get current crawler status as a dictionary.
        
        Collects various metrics including:
        - Crawl progress and statistics
        - Performance metrics (rate, latency)
        - Queue and concurrency status
        - Error rates and duplicate counts
        
        Returns:
            dict: Dictionary containing current crawler status
        """
        elapsed_total = max(1e-6, time.time() - self.start_time)
        rate = self.pages_ok / elapsed_total
        queue_left = self.db.frontier_size()
        
        # Calculate rolling averages for latency and errors
        avg_lat = (sum(self._lat_window)/len(self._lat_window)) if self._lat_window else None
        err_rate = (sum(self._err_window)/len(self._err_window)) if self._err_window else 0.0
        
        return {
            # Domain configuration
            "allowed_domain": self.allowed_domain,
            
            # Core statistics
            "pages_ok": self.pages_ok,
            "error_count": self.error_count,
            "non_html_count": self.non_html_count,
            "robots_blocked_count": self.robots_blocked_count,
            
            # Duplicate tracking
            "dup_seen": self.dup_seen,
            "dup_insert_ignored": self.dup_insert_ignored,
            "dup_count": self.dup_seen + self.dup_insert_ignored,
            
            # Link statistics
            "internal_links_unique": self.internal_links_unique,
            "external_links_unique": self.external_links_unique,
            
            # Performance metrics
            "bytes_saved": self.total_bytes_saved,
            "elapsed_sec": elapsed_total,
            "rate_pages_per_sec": rate,
            "frontier_queue_size": queue_left,
            
            # Concurrency control
            "inflight_limit": self.inflight_limit,
            "adaptive_enabled": self.adaptive_enabled,
            "avg_latency_sec": avg_lat,
            "error_rate_window": err_rate,
            
            # State flags
            "paused": self.pause_flag,
            "stopped": self.stop_flag,
            "reports_dir": self.storage.reports_dir
        }

    def _write_checkpoint(self):
        """
        Write current crawler state to checkpoint file.
        
        Saves a snapshot of crawler status to disk for resuming later.
        The checkpoint includes:
        - All current statistics and counters
        - Timestamp of checkpoint
        - Queue and progress information
        
        The checkpoint file is written to the reports directory in JSON format.
        """
        snap = self.get_status_dict()
        snap["timestamp"] = time.time()
        
        try:
            with open(self.checkpoint_path, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.getLogger("crawler").warning("checkpoint write failed: %s", e)

    # ---------- Main loop ----------
    def run(self, workers: int = 32):
        logger = logging.getLogger("crawler")
        signal.signal(signal.SIGINT, self._signal_handler)

        print("🚀 Starting crawler... Press Ctrl+C to stop gracefully.")
        self._start_key_listener()

        # ✅ نوار پیشرفت از مقدار فعلی شروع کند (Resume)
        self._pbar = tqdm(
            total=self.max_pages,
            initial=min(self.pages_ok, self.max_pages),
            desc="Crawling",
            unit="page",
            ncols=90,
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]"
        )

        try:
            with cf.ThreadPoolExecutor(max_workers=workers) as pool:
                futures = set()

                while (not self.stop_flag) and (self.pages_ok < self.max_pages):
                    # Pause handling
                    with self._pause_cv:
                        while self.pause_flag and not self.stop_flag:
                            self._pause_cv.wait(timeout=0.2)
                    if self.stop_flag:
                        break

                    # Periodic checkpoint
                    now = time.time()
                    if self.checkpoint_enabled and (now - self._last_checkpoint >= self.checkpoint_interval):
                        self._write_checkpoint()
                        self._last_checkpoint = now
                        if self.pause_at_checkpoint:
                            self.pause()

                    # ظرفیت دقیق = باقیمانده تا سقف
                    remaining = max(0, self.max_pages - self.pages_ok)
                    if remaining == 0:
                        break
                    capacity = max(0, self.inflight_limit - len(futures))
                    capacity = min(capacity, remaining)

                    if capacity > 0:
                        batch = self.db.pop_batch(capacity * 2)
                        for url, prio, depth, parent in batch:
                            if self.stop_flag or self.pause_flag:
                                break

                            # If already seen → dup_seen
                            if self.db.is_seen(url) or depth > self.max_depth:
                                self.dup_seen += 1
                                continue

                            # domain check
                            if not same_reg_domain(url, self.allowed_domain, self.follow_subdomains):
                                self.dup_seen += 1
                                continue

                            # robots disallow
                            if self.respect_robots and not self.robots.allowed(url):
                                self.robots_blocked_count += 1
                                self.db.mark_seen(url)
                                continue

                            # CAPTCHA quarantine
                            host = urlsplit(url).netloc
                            until = self.quarantine.get(host)
                            if until and time.time() < until:
                                self.db.push_url(url, prio, depth, parent)
                                continue

                            if len(futures) >= self.inflight_limit:
                                break
                            futures.add(pool.submit(self._fetch_and_process, url, depth, parent))

                    # Collect completed
                    done, futures = cf.wait(futures, timeout=0.1, return_when=cf.FIRST_COMPLETED)
                    for fut in done:
                        try:
                            fut.result()
                        except Exception as e:
                            logger.exception("worker error: %s", e)

                    # UI + Adaptive
                    if self._pbar:
                        elapsed = max(1e-6, time.time() - self.start_time)
                        rate = self.pages_ok / elapsed
                        self._pbar.set_postfix_str(
                            f"ok={self.pages_ok} err={self.error_count} nonhtml={self.non_html_count} "
                            f"dup={self.dup_seen + self.dup_insert_ignored} robots={self.robots_blocked_count} "
                            f"inflight={len(futures)}/{self.inflight_limit} rate={rate:.2f}/s"
                        )
                        # همگام‌سازی سخت
                        self._pbar.n = min(self.pages_ok, self.max_pages)
                        self._pbar.refresh()

                    if self.adaptive_enabled:
                        self._maybe_adapt()

                pool.shutdown(wait=False, cancel_futures=True)
        finally:
            self._final_report()

    def _fetch_and_process(self, url: str, depth: int, parent):
        """
        Worker method to fetch and process a single URL.
        
        This method handles:
        1. URL fetching with rate limiting
        2. Response processing
        3. Link extraction and frontier updates
        4. Stats collection
        5. Error handling
        
        Args:
            url (str): URL to fetch and process
            depth (int): Current depth in crawl tree
            parent: URL of the page that linked to this URL
        """
        # Prevent exceeding max_pages limit
        with self._ok_lock:
            if self.pages_ok >= self.max_pages or self.stop_flag:
                return

        logger = logging.getLogger("crawler")
        host = urlsplit(url).netloc

        # Apply per-host rate limiting
        sem = self._host_sema[host]
        sem.acquire()
        try:
            # Fetch the URL
            status, headers, content, elapsed, err = self.fetcher.fetch(url)
            ct = headers.get("Content-Type", "") if headers else ""
            size = len(content) if content else None

            # Update performance metrics
            if elapsed is not None:
                self.timings.append((url, float(elapsed)))
                self._lat_window.append(float(elapsed))
            self._err_window.append(1.0 if err else 0.0)

            # Handle CAPTCHA detection
            if err == "CAPTCHA_DETECTED":
                # Quarantine the host and requeue the URL
                self.quarantine[host] = time.time() + self.captcha_quarantine_sec
                self.db.push_url(url, depth, depth, parent)
                rec = CrawlRecord(url, parent, depth, status, ct, size, elapsed, err)
                self.storage.save_record(rec)
                self.error_count += 1
                return

            # Handle other errors
            if err:
                rec = CrawlRecord(url, parent, depth, status, ct, size, elapsed, err)
                self.storage.save_record(rec)
                self.error_count += 1
                self.db.mark_seen(url)
                return

            # Check if response is valid HTML
            ok_html = bool(status and 200 <= status < 300 and is_html_content(headers) and content)

            if ok_html:
                # Store HTML content if enabled
                if self.store_html:
                    sha = sha256_hex(url)
                    sha_path = os.path.join(sha[:2], sha[2:4], sha + ".html")
                    self.total_bytes_saved += self.storage.save_html(sha_path, content)

                # Extract and process links
                links = extract_links(url, content)
                for discovered_url in links:
                    # Determine if link is to allowed domain
                    is_internal = same_reg_domain(
                        discovered_url, 
                        self.allowed_domain, 
                        self.follow_subdomains
                    )
                    
                    # Track unique internal/external links
                    if is_internal:
                        if discovered_url not in self._unique_internal:
                            self._unique_internal.add(discovered_url)
                            self.internal_links_unique = len(self._unique_internal)
                    else:
                        if discovered_url not in self._unique_external:
                            self._unique_external.add(discovered_url)
                            self.external_links_unique = len(self._unique_external)

                    # Save link in graph structure
                    self.storage.save_edge(url, discovered_url)

                    # Add internal links to frontier
                    if is_internal:
                        inserted = self.db.push_url(discovered_url, depth + 1, depth + 1, url)
                        if not inserted:
                            self.dup_insert_ignored += 1

                # Thread-safe counter increment with max_pages check
                counted = False
                with self._ok_lock:
                    if self.pages_ok < self.max_pages and not self.stop_flag:
                        self.pages_ok += 1
                        counted = True
                        if self.pages_ok >= self.max_pages:
                            self.stop_flag = True

                # Save crawl record
                rec = CrawlRecord(url, parent, depth, status, ct, size, elapsed, None)
                self.storage.save_record(rec)

                # Update progress bar
                if counted and self._pbar:
                    self._pbar.n = min(self.pages_ok, self.max_pages)
                    self._pbar.refresh()

            else:
                # Handle non-HTML 2xx responses
                if status and 200 <= status < 300:
                    self.non_html_count += 1
                rec = CrawlRecord(url, parent, depth, status, ct, size, elapsed, None)
                self.storage.save_record(rec)

            # Mark URL as processed
            self.db.mark_seen(url)

        finally:
            sem.release()

    def _maybe_adapt(self):
        """Adaptively adjust concurrent requests based on performance."""
        if len(self._lat_window) < 10:
            return
            
        avg_lat = sum(self._lat_window) / len(self._lat_window)
        err_rate = (sum(self._err_window) / len(self._err_window)) if self._err_window else 0.0
        q = self.db.frontier_size()

        if (avg_lat < self.ad_low and err_rate < self.ad_err_high / 2.0 and q > self.inflight_limit):
            self.inflight_limit = min(self.ad_max, self.inflight_limit + self.ad_step)

        if (avg_lat > self.ad_high) or (err_rate > self.ad_err_high):
            self.inflight_limit = max(self.ad_min, self.inflight_limit - self.ad_step)

    def _make_charts(self, summary: dict):
        """
        Generate visualization charts for crawl statistics.
        
        Creates three charts:
        1. Bar chart of various crawl counts
        2. Histogram of response times
        3. Pie chart of internal vs external links
        
        Args:
            summary (dict): Crawl summary statistics
        """
        reports_dir = self.storage.reports_dir

        # Create counts bar chart
        counts = {
            "ok": summary["pages_ok"],
            "errors": summary["error_count"],
            "non_html": summary["non_html_count"],
            "robots": summary["robots_blocked_count"],
            "dup": summary["dup_count"],
        }
        plt.figure()
        plt.bar(list(counts.keys()), list(counts.values()))
        plt.title("Crawl Results Distribution")
        plt.ylabel("Count")
        plt.tight_layout()
        plt.savefig(os.path.join(reports_dir, "counts.png"))
        plt.close()

        # Create response time histogram
        times = [t for _, t in self.timings if t is not None]
        if times:
            plt.figure()
            plt.hist(times, bins=30)
            plt.title("Response Time Distribution")
            plt.xlabel("Time (seconds)")
            plt.ylabel("Number of Pages")
            plt.tight_layout()
            plt.savefig(os.path.join(reports_dir, "times_hist.png"))
            plt.close()

        # Create internal vs external links pie chart
        plt.figure()
        plt.pie(
            [self.internal_links_unique, self.external_links_unique],
            labels=["Internal Links (Unique)", "External Links (Unique)"], 
            autopct="%1.1f%%"
        )
        plt.title("Distribution of Discovered Links")
        plt.tight_layout()
        plt.savefig(os.path.join(reports_dir, "links_pie.png"))
        plt.close()

    # ---------- Checkpoint ----------
    def _write_checkpoint(self):
        snap = self.get_status_dict()
        snap["timestamp"] = time.time()
        path = self.checkpoint_path  # reports/checkpoint.json
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.getLogger("crawler").warning("checkpoint write failed: %s", e)

    # ---------- Final report & charts ----------
    def _final_report(self):
        elapsed_total = max(1e-6, time.time() - self.start_time)
        rate = self.pages_ok / elapsed_total
        queue_left = self.db.frontier_size()
        fastest = min(self.timings, key=lambda x: x[1]) if self.timings else (None, None)
        slowest = max(self.timings, key=lambda x: x[1]) if self.timings else (None, None)

        # جمع‌بندی duplicateها
        self.dup_count = self.dup_seen + self.dup_insert_ignored

        summary = {
            "pages_ok": self.pages_ok,
            "error_count": self.error_count,
            "non_html_count": self.non_html_count,
            "robots_blocked_count": self.robots_blocked_count,
            "dup_seen": self.dup_seen,
            "dup_insert_ignored": self.dup_insert_ignored,
            "dup_count": self.dup_count,
            "internal_links_unique": self.internal_links_unique,
            "external_links_unique": self.external_links_unique,
            "total_bytes_saved": self.total_bytes_saved,
            "elapsed_total_sec": elapsed_total,
            "pages_per_sec": rate,
            "queue_left": queue_left,
            "fastest_fetch": {"url": fastest[0], "sec": fastest[1]} if fastest[0] else None,
            "slowest_fetch": {"url": slowest[0], "sec": slowest[1]} if slowest[0] else None,
            "inflight_limit": self.inflight_limit,
            "adaptive_enabled": self.adaptive_enabled
        }

        summ_path = self.storage.write_summary_json(summary)

        try:
            self._make_charts(summary)
        except Exception as e:
            logging.getLogger("crawler").warning("charts failed: %s", e)

        print("\n📊 Report:")
        print(f"  - pages_ok: {summary['pages_ok']}")
        print(f"  - error_count: {summary['error_count']}")
        print(f"  - non_html_count: {summary['non_html_count']}")
        print(f"  - robots_blocked_count: {summary['robots_blocked_count']}")
        print(f"  - dup_seen: {summary['dup_seen']}")
        print(f"  - dup_insert_ignored: {summary['dup_insert_ignored']}")
        print(f"  - dup_count: {summary['dup_count']}")
        print(f"  - internal_links_unique: {summary['internal_links_unique']}")
        print(f"  - external_links_unique: {summary['external_links_unique']}")
        print(f"  - total_bytes_saved: {summary['total_bytes_saved']}")
        print(f"  - elapsed_total_sec: {summary['elapsed_total_sec']:.3f}")
        print(f"  - pages_per_sec: {summary['pages_per_sec']:.3f}")
        print(f"  - inflight_limit(final): {summary['inflight_limit']}")
        print(f"  - queue_left: {summary['queue_left']}")
        if summary["fastest_fetch"]:
            print(f"  - fastest: {summary['fastest_fetch']['sec']:.3f}s  {summary['fastest_fetch']['url']}")
        if summary["slowest_fetch"]:
            print(f"  - slowest: {summary['slowest_fetch']['sec']:.3f}s  {summary['slowest_fetch']['url']}")

        print(f"\n📝 Summary JSON: {summ_path}")
        print(f"🔗 Graph edges CSV: {self.storage.edges_path}")
        print(f"🧾 Crawl log CSV: {self.storage.csv_path}")
        print("🖼️ Charts saved in:", self.storage.reports_dir)

        if self._pbar:
            self._pbar.close()

    def _make_charts(self, summary: dict):
        rd = self.storage.reports_dir

        # Counts bar
        counts = {
            "ok": summary["pages_ok"],
            "errors": summary["error_count"],
            "non_html": summary["non_html_count"],
            "robots": summary["robots_blocked_count"],
            "dup": summary["dup_count"],
        }
        plt.figure()
        plt.bar(list(counts.keys()), list(counts.values()))
        plt.title("Crawl Counts")
        plt.ylabel("count")
        plt.tight_layout()
        plt.savefig(os.path.join(rd, "counts.png"))
        plt.close()

        # Response time histogram
        times = [t for _, t in self.timings if t is not None]
        if times:
            plt.figure()
            plt.hist(times, bins=30)
            plt.title("Response Time Distribution (s)")
            plt.xlabel("seconds")
            plt.ylabel("pages")
            plt.tight_layout()
            plt.savefig(os.path.join(rd, "times_hist.png"))
            plt.close()

        # Internal vs External UNIQUE links
        plt.figure()
        plt.pie(
            [self.internal_links_unique, self.external_links_unique],
            labels=["internal(unique)", "external(unique)"], autopct="%1.1f%%"
        )
        plt.title("Links: Internal vs External (Unique)")
        plt.tight_layout()
        plt.savefig(os.path.join(rd, "links_pie.png"))
        plt.close()
