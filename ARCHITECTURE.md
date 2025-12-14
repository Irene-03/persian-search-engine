# Search Engine Project - Architecture

## Overview

This is a multi-phase academic search engine implementation. Each phase builds upon the previous one while maintaining modularity.

## Phase 1: Web Crawler ✅ (Current)

**Status**: Complete  
**Branch**: `master`  
**Tag**: `v1.0-phase1`

**Components**:
- Multi-threaded web crawler
- JavaScript rendering support
- Robots.txt compliance
- Checkpoint/resume functionality
- Data persistence layer

**Location**: `/src/bama_crawler/`

## Phase 2: Indexer & Search Engine 🚧 (Planned)

**Status**: Not started  
**Planned Branch**: `phase2` or `phase2-indexer`

**Planned Components**:
- Document indexer
- Inverted index builder
- Query processor
- Ranking algorithm
- Search API

**Recommended Structure**:

### Option A: Separate Branch (Recommended)
```
master branch:
  - Phase 1 crawler code (current)

phase2 branch:
  - Phase 1 crawler (as dependency)
  - Phase 2 indexer & search components
```

### Option B: Monorepo Structure
```
project-root/
├── crawler/          # Phase 1 code
├── indexer/          # Phase 2 component 1
├── search-api/       # Phase 2 component 2
├── common/           # Shared utilities
└── docker-compose.yml
```

## Integration Strategy

### How Phase 2 will use Phase 1:

1. **Data Integration**: Phase 2 will read from Phase 1's output:
   - `data/*/repository/` - HTML content
   - `data/*/metadata/` - Crawl metadata
   - `data/*/reports/` - Link graphs

2. **Code Reuse**: Phase 2 can import Phase 1 modules:
   ```python
   from bama_crawler.storage import Storage
   from bama_crawler.parser import extract_links
   ```

3. **Pipeline Approach**:
   ```
   Phase 1 (Crawler) → Data Storage → Phase 2 (Indexer) → Search Index
   ```

## Development Workflow

### Starting Phase 2:

```bash
# Create new branch for phase 2
git checkout -b phase2

# Directory structure
mkdir -p phase2/{indexer,searcher,api}

# Commit phase 2 scaffolding
git add .
git commit -m "Phase 2 scaffolding"
git push -u origin phase2
```

### Merging phases (if needed):

```bash
# Merge phase 2 into master when complete
git checkout master
git merge phase2 --no-ff
git tag -a v2.0-complete -m "Complete search engine implementation"
git push origin master --tags
```

## Best Practices

1. **Keep phases separate**: Use branches or directories
2. **Tag releases**: Tag each phase completion
3. **Document interfaces**: Clear API between phases
4. **Maintain backwards compatibility**: Phase 1 should work standalone
5. **Use Docker Compose**: For multi-service setup in Phase 2

## Questions?

Refer to README.md in each phase directory for specific documentation.
