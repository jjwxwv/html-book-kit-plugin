# .book-state/ — working state (generated; do not edit by hand)

| Path | What | Written by |
|---|---|---|
| `manifest.json` | committed SHA-256 of every source | `scan_sources.py --commit` |
| `extracted-office/` | pptx/docx → markdown cache, and wrapped copies of text sources with over-long lines (keyed by SHA and extractor version) | `extract_office.py` |
| `extractions/<ch>/*.md` | per-source semantic extraction — the ground truth for all downstream agents, independent of the summary level. Frontmatter (`sha256`, `units`, `pages`/`slides`/`lines`, `extractor`) is stamped by `sync_state.py --stamp` | source-analyst (+ stamp) |
| `unit-sources.json` | for every unit that locates one run of lines or slides: a hash of the part of the file it was read from, and of what the unit says — how the kit proves, after a source edit, which units are untouched (no re-read, no rewrite) | `sync_state.py --stamp` / `--plan` |
| `plan/book-plan.json` | hierarchy, order, what each section `covers` and `merged`, what is `omitted` and why, supplements, id history — one plan for every level | book-architect |
| `plan/reextracted.json` | exists only while a re-extraction left something to decide: for each source that was extracted again, the units that are new, replaced in place or gone, and sections that lost every unit. The unit numbers in the plan were already re-pointed by the script; the entry disappears when the plan accounts for everything | `sync_state.py --stamp` / `--plan` |
| `plan/coverage.json` | every extraction unit → represented / merged / omitted_justified / administrative, **generated from the plan** | `sync_state.py --plan`, `validate_book.py` |
| `plan/slices/ch-<id>.json` | one chapter's brief for its writer and auditor: plan entry, units with priority/keys, extraction files, what to write | `sync_state.py --plan` |
| `drafts/L<level>/ch-<id>.html` | content fragments per chapter, one store per summary level; the first line stamps chapter, level and revision | chapter-writer |
| `drafts/removed/L<level>/ch-<id>.html` | drafts of chapters that left the plan — kept for you, never read by the kit; delete when not needed | `sync_state.py --plan` |
| `drafts/L<level>/inputs.json` | what each draft was written from (fingerprints per section), and what each writer was last handed (`briefed`) — how a stale draft is found | `sync_state.py --plan`, `build_book.py` |
| `audits/audit-<n>.json` | audit report; `status`: pending_approval → approved/declined → applied (or clean; `superseded` once a later report has taken over its open findings). `audit-<n>.part-*.json` exist only while an audit or a recheck runs. A report is about the edition of one level (`level`); each level has its own line of reports | book-auditor parts, merged by `sync_state.py --merge-audit`; status changes by `--set-audit` |
| `audits/gate.json` | the approval gate: `seen` (the plugin's hook ran in this project), `grants` (how often the user typed `/book-kit:apply-fixes`), `used` (approvals spent on fix batches) | the plugin's hook `scripts/gate_hook.py`; spent by `sync_state.py --set-audit approved` |
| `validate-report.json` | latest mechanical validation result (complete lists) | `validate_book.py` |

`book/` (next to this folder) is generated from the drafts by `build_book.py` — never edit it by hand.

State that belongs to removed or moved sources is deleted or remapped by `sync_state.py --sources`
(run by /book-kit:build-book and /book-kit:update-book when the scan reports it). An extraction keeps its
file name for life — it is what the plan references — even when its source is later moved or its chapter
renumbered; the `source:` and `chapter:` lines inside it are what is kept current.

Changing `content.level` in `book.config.json` keeps everything here: the other level's drafts stay in
their store, and /book-kit:update-book writes only the chapters that have no current draft at the new level.

Deleting this folder forces a full rebuild (all sources re-read). Keep it to get incremental updates
and zero re-reads of unchanged sources.
