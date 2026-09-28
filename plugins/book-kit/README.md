# Claude HTML Book Kit v10.0 — plugin edition (`book-kit`)

A Claude Code plugin that turns course sources (`sources/`: PDF / PPTX / DOCX / Markdown) into an accurate, readable **Thai HTML summary book / lecture** with a nested TOC, reading progress, a colorful WCAG-AA-checked light/dark theme, incremental SHA-256 updates, and a strict *report → ask → stop* audit gate (no self-approving fix loops). Five subagents (`source-analyst`, `book-architect`, `chapter-writer`, `book-builder`, `book-auditor`) do the work; you only run commands.

## Install (pick one)

| Way | Command | Loads |
|---|---|---|
| Every session, no marketplace | copy this folder to `~/.claude/skills/book-kit/` | every session, as `book-kit@skills-dir` |
| One session | `claude --plugin-dir /path/to/book-kit` (a `.zip` of the folder also works) | that session only |
| Marketplace (gets updates) | `claude plugin marketplace add /path/to/repo` (or `owner/repo` on GitHub) then `claude plugin install book-kit@html-book-kit` | wherever installed (user / project / local scope) |

Check with `claude plugin validate /path/to/book-kit` or `/plugin` → Installed. Requires Python 3 (`pip install python-pptx python-docx` only for `.pptx`/`.docx` sources).

## Use

```text
mkdir my-course && cd my-course && claude
/book-kit:init "ชื่อหนังสือ"      # scaffold: sources/, book.config.json, permissions, minimal CLAUDE.md
# put sources in sources/ (numeric prefixes = chapter structure — see sources/README.md)
/book-kit:build-book              # extract → plan → write → build → validate → audit → REPORT → ASK → STOP
/book-kit:apply-fixes             # one remediation batch per approval, recheck, stop
/book-kit:update-book             # after editing / adding / removing sources: only what changed
/book-kit:audit-book [chapters]   # audit only, changes nothing
```

Open `book/index.html`. The book project is the directory Claude Code was started in; the plugin never writes into itself.

## Layout

```text
.claude-plugin/plugin.json   manifest (name: book-kit)
skills/rules/                orchestrator rules (ex-CLAUDE.md) — loaded by commands, preloaded into judgment agents
skills/{init,build-book,update-book,audit-book,apply-fixes}/   commands (/book-kit:<name>)
agents/                      5 subagents (book-kit:<name>)
scripts/                     scan_sources · extract_office · prune_state · validate_book · init_project
templates/                   HTML shells + assets (read-only; a project-local templates/ overrides them)
scaffold/                    files copied into a new project by /book-kit:init
```

Full guide (Thai): [README_TH.md](README_TH.md). Version history: [CHANGELOG.md](CHANGELOG.md).
