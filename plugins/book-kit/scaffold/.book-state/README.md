# .book-state/ — working state (generated; do not edit by hand)

| Path | What | Written by |
|---|---|---|
| `manifest.json` | committed SHA-256 of every source | `scan_sources.py --commit` |
| `extracted-office/` | pptx/docx → markdown cache (keyed by SHA) | `extract_office.py` |
| `extractions/<ch>/*.md` | per-source semantic extraction (ground truth for all downstream agents) | source-analyst |
| `plan/book-plan.json` | hierarchy, ordering, dedup, priorities, supplements, stable IDs | book-architect |
| `plan/coverage.json` | every extraction unit → represented / merged / omitted_justified / administrative / unresolved | book-architect |
| `drafts/ch-<id>.html` | Thai content fragments per top-level chapter | chapter-writer |
| `audits/audit-<n>.json` | audit findings; `status`: pending_approval → approved/declined → applied | book-auditor |
| `validate-report.json` | latest mechanical validation result | `validate_book.py` |

Stale files left behind by removed sources are deleted by the plugin script `prune_state.py`
(run automatically by /book-kit:build-book and /book-kit:update-book when the scan reports removals).

Deleting this folder forces a full rebuild (all sources re-read). Keep it to get
incremental updates and zero re-reads of unchanged sources.
