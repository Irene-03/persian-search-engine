
#!/usr/bin/env python3
"""
Crawler Repository Test and Analysis Tool

This script provides utilities for:
- Counting files in crawler repository
- Analyzing file extensions
- Validating crawl results against summary data
- Generating repository statistics
"""

import argparse
import json
import sys
from pathlib import Path
from collections import Counter

def count_files(repo_dir: Path, ext_filter=None):
    """
    Count files in repository, optionally filtered by extension.
    
    Args:
        repo_dir (Path): Path to repository directory
        ext_filter (str, optional): File extension to filter by
        
    Returns:
        tuple: (total_count, Counter of extensions)
        
    Example:
        total, extensions = count_files(Path("data/repo"), "html")
        print(f"Found {total} HTML files")
        print("Extensions:", extensions)
    """
    if not repo_dir.exists():
        print(f"ERROR: repo dir not found: {repo_dir}", file=sys.stderr)
        return 0, Counter()

    counter = Counter()
    total = 0
    for p in repo_dir.rglob("*"):
        if p.is_file():
            if ext_filter:
                if p.suffix.lower() != (ext_filter if ext_filter.startswith('.') else '.' + ext_filter.lower()):
                    continue
            total += 1
            counter[p.suffix.lower()] += 1
    return total, counter

def main():
    """
    Main entry point for the repository analysis tool.
    
    Supports:
    - Counting files by extension
    - Filtering by file type
    - Validating against crawl summary
    """
    ap = argparse.ArgumentParser(description="Count saved files in crawler repo directory.")
    ap.add_argument("--repo", required=True, help="Path to repo folder, e.g. data\\basalam_com\\repo")
    ap.add_argument("--ext", default=None, help="Optional extension filter, e.g. html or .html")
    ap.add_argument("--summary", default=None, help="Optional path to reports\\summary.json to compare pages_ok")
    args = ap.parse_args()

    repo_dir = Path(args.repo)
    total, per_ext = count_files(repo_dir, args.ext)

    # Display basic repository information
    print(f"📁 Repo: {repo_dir}")
    if args.ext:
        print(f"🔎 Filtering by extension: {args.ext}")
    print(f"🧮 Total files{' (filtered)' if args.ext else ''}: {total}")

    # Show extension distribution if not filtering
    if not args.ext:
        if per_ext:
            print("🔩 File Extension Distribution:")
            for ext, cnt in per_ext.most_common():
                label = ext if ext else "(no extension)"
                print(f"  - {label}: {cnt}")

    # Compare against crawl summary if provided
    if args.summary:
        summary_path = Path(args.summary)
        if summary_path.exists():
            try:
                # Load and parse summary data
                data = json.loads(summary_path.read_text(encoding="utf-8"))
                pages_ok = data.get("pages_ok")
                non_html = data.get("non_html_count")
                dup = data.get("dup_count")
                
                # Display summary statistics
                print(f"\n📊 Crawl Summary Statistics:")
                print(f"  - Successfully crawled pages: {pages_ok}")
                print(f"  - Non-HTML responses: {non_html}")
                print(f"  - Duplicate URLs: {dup}")
                
                # Validate file counts against crawl statistics
                if pages_ok is not None:
                    if args.ext in (None, "html", ".html"):
                        # Compare HTML files to successful crawls
                        if total == pages_ok:
                            print("✅ HTML file count matches successful crawls")
                        else:
                            print("ℹ️ Note: HTML file count may differ from successful crawls due to:")
                            print("   - Different storage formats")
                            print("   - Applied extension filters")
                            print("   - Partial or incomplete crawls")
                    else:
                        print("ℹ️ Note: Comparing non-HTML files to successful crawls is not meaningful")
            except Exception as e:
                print(f"⚠️ Error reading summary.json: {e}")
        else:
            print(f"⚠️ Summary file not found: {summary_path}")

if __name__ == "__main__":
    main()
