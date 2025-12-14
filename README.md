# Web Crawler - Phase 1

A production-ready, multi-threaded web crawler built for academic research purposes. Features include concurrent crawling, JavaScript rendering support, robots.txt compliance, and comprehensive data collection with checkpoint/resume capabilities.

## Features

- ✅ **Multi-threaded Crawling**: Configurable worker threads with adaptive concurrency control
- ✅ **JavaScript Rendering**: Optional Playwright integration for SPA support
- ✅ **Polite Crawling**: Respects robots.txt, implements rate limiting, and includes contact information
- ✅ **Resume Support**: Checkpoint-based resumption for interrupted crawls
- ✅ **Data Collection**: Structured storage of HTML content, metadata, and link graphs
- ✅ **Real-time Control**: Interactive pause/resume/stop via keyboard commands
- ✅ **Monitoring**: Progress bars, performance metrics, and comprehensive logging

## Quick Start

### Local Setup

```bash
# Clone and setup
git clone https://github.com/irene-03/persian-search-engine.git
cd persian-search-engine

# Create virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt

# Run crawler
python src/main.py --seeds https://bama.ir --max-pages 100
```

### Docker Setup

```bash
# Build image
docker build -t web-crawler .

# Run with persistent storage
docker run --rm -v ${PWD}/data:/app/data web-crawler --seeds https://bama.ir
```

## Configuration

Edit `src/config.yaml` to customize crawler behavior:

```yaml
allowed_domain: "bama.ir"
max_pages: 1000
max_depth: 4
request_timeout_sec: 15
enable_render: true  # Enable JavaScript rendering
```

## Output Structure

```
data/
└── bama_ir/
    ├── repository/     # Crawled HTML files (content-addressed)
    ├── metadata/       # CSV/JSONL crawl logs
    ├── reports/        # Summary JSON, graphs, checkpoints
    ├── state/          # SQLite frontier database
    └── logs/           # Application logs
```

## CLI Options

```bash
--seeds URL [URL ...]     # Starting URLs
--max-pages N             # Maximum pages to crawl
--max-depth N             # Maximum link depth
--workers N               # Number of concurrent workers
--data-root PATH          # Data storage directory
--restart                 # Clear state and restart
--verbose                 # Enable debug logging
```

## Project Structure

```
src/
├── bama_crawler/          # Core crawler package
│   ├── db.py             # Frontier & visited URL management
│   ├── fetcher.py        # HTTP client with JS rendering
│   ├── frontier.py       # Main crawler orchestration
│   ├── parser.py         # HTML parsing & link extraction
│   ├── robots.py         # robots.txt compliance
│   ├── storage.py        # Data persistence layer
│   └── utils.py          # Utilities (URL normalization, rate limiting)
├── main.py               # CLI entry point
├── config.yaml           # Default configuration
└── test.py               # Repository analysis tool
```

## Development Notes

This is **Phase 1** of a search engine implementation. Phase 2 will include indexing and retrieval components. The current monorepo structure supports future extension without conflicts.

## License

Academic use only.
