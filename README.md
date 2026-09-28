# claude-html-book-kit — plugin distribution

This repository is a Claude Code **plugin marketplace** (`html-book-kit`) that ships one plugin, **`book-kit`** (Claude HTML Book Kit v10.0): a 5-agent pipeline that turns course sources (PDF / PPTX / DOCX / Markdown) into an accurate, readable Thai HTML book with incremental SHA-256 updates and a strict *report → ask → stop* audit gate.

```text
.claude-plugin/marketplace.json   marketplace manifest (name: html-book-kit)
plugins/book-kit/                 the plugin — install this folder
```

## Install

| Way | Command | Loads |
|---|---|---|
| Every session, no marketplace | copy `plugins/book-kit` to `~/.claude/skills/book-kit/` | every session, as `book-kit@skills-dir` |
| One session | `claude --plugin-dir ./plugins/book-kit` (or `--plugin-dir book-kit.zip`) | that session only |
| Marketplace (updates) | `claude plugin marketplace add /path/to/this/repo` (or `owner/repo` once pushed to GitHub), then `claude plugin install book-kit@html-book-kit` | wherever installed (user / project / local scope) |

Verify: `claude plugin validate ./plugins/book-kit` from your shell, or `/plugin` → Installed inside a session. Then, in any folder that should hold a book: `/book-kit:init "ชื่อหนังสือ"` → put sources in `sources/` → `/book-kit:build-book`.

Requires Python 3; `pip install python-pptx python-docx` only for `.pptx`/`.docx` sources.

Plugin docs: [plugins/book-kit/README.md](plugins/book-kit/README.md) (EN) · [plugins/book-kit/README_TH.md](plugins/book-kit/README_TH.md) (TH) · [CHANGELOG](plugins/book-kit/CHANGELOG.md).
