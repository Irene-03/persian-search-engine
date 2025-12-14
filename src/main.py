#!/usr/bin/env python3
"""
Web Crawler Main Module

This module serves as the entry point for the web crawler application.
It handles configuration, command-line arguments, logging setup, and
crawler initialization and execution.
"""

import argparse
import logging
import os
import yaml
import sys
from bama_crawler.frontier import Crawler

def parse_args():
    """Parse command-line arguments for the crawler.
    
    Returns:
        argparse.Namespace: Parsed command-line arguments including:
            - config: Path to configuration file (default: config.yaml)
            - seeds: List of seed URLs to start crawling from
            - max-pages: Maximum number of pages to crawl
            - max-depth: Maximum depth of crawling
            - workers: Number of concurrent crawler workers
            - data-root: Root directory for storing crawler data
            - verbose: Enable verbose logging
            - restart: Clear previous state and restart crawling
    """
    ap = argparse.ArgumentParser(description='Web Crawler')
    ap.add_argument('--config', default='config.yaml')
    ap.add_argument('--seeds', nargs='+')
    ap.add_argument('--max-pages', type=int)
    ap.add_argument('--max-depth', type=int)
    ap.add_argument('--workers', type=int)
    ap.add_argument('--data-root', default='data')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--restart', action='store_true')
    return ap.parse_args()

def load_config(path):
    """Load crawler configuration from YAML file.
    
    Searches both the provided path (relative to current working directory)
    and the `src/` directory so the CLI works whether executed from the
    project root or inside `src`.
    """
    candidates = [path]
    if not os.path.isabs(path):
        candidates.append(os.path.join(os.path.dirname(__file__), path))

    for candidate in candidates:
        if os.path.exists(candidate):
            with open(candidate, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)

    raise FileNotFoundError(f"Config file not found in: {candidates}")

def setup_logging(verbose: bool, data_root: str):
    """Configure logging for the crawler.
    
    Sets up logging to both console and file, with level based on verbosity.
    
    Args:
        verbose (bool): If True, set logging level to DEBUG; otherwise INFO
        data_root (str): Directory where log files will be stored
    """
    os.makedirs(os.path.join(data_root, 'logs'), exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(os.path.join(data_root, 'logs', 'crawler.log'), mode='a', encoding='utf-8')
        ]
    )

def main():
    """Main entry point for the crawler application."""
    # Parse arguments and load configuration
    args = parse_args()
    cfg = load_config(args.config)

    # Override configuration with command-line arguments if provided
    if args.max_pages: cfg['max_pages'] = args.max_pages
    if args.max_depth: cfg['max_depth'] = args.max_depth
    if args.workers:   cfg['workers']   = args.workers

    # Setup data directory based on allowed domain
    allowed = cfg['allowed_domain']
    if isinstance(allowed, list):
        primary = allowed[0]  # Use first domain as primary if multiple allowed
    else:
        primary = allowed
    domain_dir_name = primary.strip().lower().replace('.', '_')
    data_root = os.path.join(args.data_root, domain_dir_name)
    os.makedirs(data_root, exist_ok=True)

    setup_logging(args.verbose, data_root)

    # Handle restart mode: clear state while keeping repository data
    checkpoint = os.path.join(data_root, 'checkpoint.json')
    db_path    = os.path.join(data_root, 'crawl.db')
    frontier_csv = os.path.join(data_root, 'metadata', 'crawled.csv')

    if args.restart:
        # Clear state files (frontier, seen URLs, checkpoint)
        for p in [checkpoint, db_path, frontier_csv]:
            try:
                if os.path.isfile(p): os.remove(p)
            except: pass
        print("🔁 RESTART (state cleared, data kept)")
    else:
        print("⏸️ RESUME (continue previous crawl if state exists)")

    print(f"📂 Data directory: {data_root}")

    # Initialize and run crawler
    seeds = args.seeds or cfg.get('seeds') or [f"https://{primary}/"]
    crawler = Crawler(cfg, data_root=data_root)
    crawler.seed(seeds)  # Seeds are ignored if resuming previous crawl
    crawler.run(workers=cfg.get('workers', 8))

if __name__ == '__main__':
    main()
