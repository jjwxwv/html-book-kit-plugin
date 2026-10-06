# claude-html-book-kit — plugin distribution

This repository is a Claude Code **plugin marketplace** (`html-book-kit`) that ships one plugin, **`book-kit`** (Claude HTML Book Kit v11.6): five subagents gated by deterministic scripts that turn lesson sources (PDF / PPTX / DOCX / Markdown) into an accurate, easy-to-picture HTML summary book at a configurable **summary level** (1 = exam review, 2 = re-composed study summary; both editions are kept side by side), with SHA-256 freshness checks from source to page, coverage derived from the plan, and a *report → ask → stop* audit gate that a script enforces (fixes start only when you type `/book-kit:apply-fixes`).

```text
.claude-plugin/marketplace.json   marketplace manifest (name: html-book-kit)
plugins/book-kit/                 the plugin — install this folder
preview/level-1, preview/level-2  the same sample book built at both summary levels — open index.html
tests/                            regression suite — python3 tests/run_tests.py [--browser]
```

## Install

| Way | Command | Loads |
|---|---|---|
| Every session, no marketplace | copy `plugins/book-kit` to `~/.claude/skills/book-kit/` | every session, as `book-kit@skills-dir` |
| One session | `claude --plugin-dir ./plugins/book-kit` (or `--plugin-dir book-kit.zip`) | that session only |
| Marketplace (updates) | `claude plugin marketplace add /path/to/this/repo` (or `owner/repo` once pushed to GitHub), then `claude plugin install book-kit@html-book-kit` | wherever installed (user / project / local scope) |

Verify: `claude plugin validate ./plugins/book-kit` from your shell, or `/plugin` → Installed inside a session. Checked on Claude Code 2.1.290 (v11.6: validation and approval hook on 2.1.291); use 2.1.271 or later (the plugin README says what older versions lack). Then, in any folder that should hold a book: `/book-kit:init "ชื่อหนังสือ"` → put sources in `sources/` → choose `content.level` in `book.config.json` → `/book-kit:build-book`.

Requires Python 3 and nothing else (PDF page counts are read with the standard library; `pip install pypdf` is an optional second reader for PDFs it cannot count, such as encrypted ones). The tests need only the standard library (`--browser` additionally needs Playwright + Chromium).

Plugin docs: [plugins/book-kit/README.md](plugins/book-kit/README.md) (EN) · [plugins/book-kit/README_TH.md](plugins/book-kit/README_TH.md) (TH) · [CHANGELOG](plugins/book-kit/CHANGELOG.md).
