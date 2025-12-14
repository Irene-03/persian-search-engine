import os, csv, json, pathlib, logging
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger(__name__)

@dataclass
class CrawlRecord:
    url: str
    parent_url: Optional[str]
    depth: int
    status: Optional[int]
    content_type: Optional[str]
    size_bytes: Optional[int]
    fetch_sec: Optional[float]
    error: Optional[str]

class Storage:
    def __init__(self, root: str):
        self.root = root
        self.repo_dir = os.path.join(root, 'repository')
        self.meta_dir = os.path.join(root, 'metadata')
        self.reports_dir = os.path.join(root, 'reports')     # ← NEW
        os.makedirs(self.repo_dir, exist_ok=True)
        os.makedirs(self.meta_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)         # ← NEW

        self.csv_path = os.path.join(self.meta_dir, 'crawled.csv')
        self.jsonl_path = os.path.join(self.meta_dir, 'crawled.jsonl')
        self.edges_path = os.path.join(self.reports_dir, 'graph_edges.csv')  # ← NEW

        if not os.path.exists(self.csv_path):
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(['url','parent_url','depth','status','content_type','size_bytes','fetch_sec','error'])

        if not os.path.exists(self.edges_path):
            with open(self.edges_path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(['src','dst'])

    def save_html(self, sha_path: str, content: bytes, max_size: int = 10 * 1024 * 1024):
        """Save HTML content with size limit and buffered IO.
        
        Args:
            sha_path: Path relative to repository root
            content: Raw HTML content
            max_size: Maximum file size in bytes (default: 10MB)
        """
        if len(content) > max_size:
            logger.warning(f"Content too large ({len(content)} bytes), truncating to {max_size}")
            content = content[:max_size]
            
        full = os.path.join(self.repo_dir, sha_path)
        pathlib.Path(os.path.dirname(full)).mkdir(parents=True, exist_ok=True)
        
        with open(full, 'wb', buffering=8192) as f:  # 8KB buffer
            f.write(content)
        return len(content)

    def save_record(self, rec: CrawlRecord):
        d = asdict(rec)
        with open(self.csv_path, 'a', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow([d[k] for k in ['url','parent_url','depth','status','content_type','size_bytes','fetch_sec','error']])
        with open(self.jsonl_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(d, ensure_ascii=False) + '\n')

    # ---- NEW: ثبت یال‌های گراف
    def save_edge(self, src: str, dst: str):
        with open(self.edges_path, 'a', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow([src, dst])

    # ---- NEW: ذخیره خلاصه
    def write_summary_json(self, summary: dict, filename: str = "summary.json"):
        p = os.path.join(self.reports_dir, filename)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        return p
