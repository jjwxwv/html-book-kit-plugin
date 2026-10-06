# Claude HTML Book Kit v11.5 — plugin edition (`book-kit`)

A Claude Code plugin that turns lesson sources (`sources/`: PDF / PPTX / DOCX / Markdown) into an accurate, easy-to-picture **HTML summary book** (Thai by default) with a nested TOC and agenda, reading progress, light/dark themes and AA-checked colour palettes. Five subagents (`source-analyst`, `book-architect`, `chapter-writer`, `book-builder`, `book-auditor`) do the judgment work; scripts do everything mechanical and gate every phase; you only run commands.

## What the kit guarantees mechanically

- **Nothing is read twice, nothing stale survives.** Every extraction records the SHA-256 of the source version it was written from; every draft records a fingerprint of what its writer was handed (taken when the writer is briefed, not at build time). A changed source, unit, title or section list is found by script, and only the affected sections are rewritten: a unit that says what it said before keeps its sections current even when its number or place in the source moved, and for a changed text, `.docx` or `.pptx` source the units whose part of the file is untouched are proven by hash — they are neither read nor written again. (A changed PDF is read again as a whole; how many of its units keep their wording depends on the analyst.)
- **Every unit of every source is accounted for.** Units are counted from the extraction itself; the plan says for each one whether it is covered, merged or omitted (with a reason); the coverage ledger is generated from the plan. A source that was not read to its end blocks, and the next scan hands it back to its analyst to read on — pages (PDF), slides (PPTX) and lines (DOCX, Markdown, text, HTML) are counted by script; where a count is impossible the report says so instead of passing.
- **A page contains exactly what the plan says**, in the plan's shape; pages are byte-identical to their drafts; a section that covers units cannot be a bare heading.
- **What the kit cannot see is said.** Pictures and embedded objects in `.pptx`/`.docx` are counted and reported to you and to the auditor, with the fix (export that file to PDF).
- **Summary levels** — `content.level`: `1` = exam-review summary, `2` = re-composed study summary. The level changes the density of the explanation, never the coverage. Each level has its own draft store and its own line of audit reports, so both editions can exist and switching back costs nothing.
- **The draft fits the configuration.** A chapter written in another language than `book.language`, TeX or Mermaid in a draft while that feature is off, a level-1 chapter without the recall questions that are switched on — each is found by script and sent to the writer; a changed audience or style note rewrites nothing and is reported. A draft is content only: a script, style or navigation element blocks (`draft.foreign_markup`), and a colour written as a literal — which would not follow the theme — is reported (`draft.hard_colour`). A rewrite asked for with `--rewrite` is owed until every chapter was written again.
- **The plan follows a re-extraction by script.** When a source is read again its units are numbered anew; `sync_state.py` re-points every reference in the plan itself (units that only moved, units replaced in place). What needs judgment — units that are new, sections that lost every unit — blocks the plan check until the architect has answered it, also after an interrupted run; a unit replaced in place stays on record (scan `replan`, warning `plan.replaced_unreviewed`) until the architect confirms its place.
- **Report → ask → stop, with a gate that is checked.** Audits never fix anything. The approval is the user typing `/book-kit:apply-fixes` — the model cannot start that command, the plugin's hook records each typed command, and the script that starts a fix batch spends one record per batch and refuses without one (`audit.gate`); a report takes at most `audit.max_fix_batches` batches. A finding stays on the table until it is fixed or you decline it — a later audit carries it over unless its auditor reports it fixed, an audit of the other level's edition does not touch it, and an interrupted fix batch is resumed.

These are guarantees about the *evidence chain*. Whether a sentence is right is judged by the auditor agents, not by a script — see "Known limits" in [README_TH.md](README_TH.md).

## Install (pick one)

| Way | Command | Loads |
|---|---|---|
| Every session, no marketplace | copy this folder to `~/.claude/skills/book-kit/` | every session, as `book-kit@skills-dir` |
| One session | `claude --plugin-dir /path/to/book-kit` (a `.zip` of the folder also works) | that session only |
| Marketplace (gets updates) | `claude plugin marketplace add /path/to/repo` (or `owner/repo` on GitHub) then `claude plugin install book-kit@html-book-kit` | wherever installed (user / project / local scope) |

Check with `claude plugin validate /path/to/book-kit` or `/plugin` → Installed. Requires Python 3 — nothing else.

**Claude Code version.** Validated (`claude plugin validate --strict`), loaded with `--plugin-dir` and from `~/.claude/skills/`, and the approval hook exercised with typed commands, on Claude Code 2.1.290 (marketplace install last checked on 2.1.289). Use 2.1.271 or later so that `omitClaudeMd` takes effect (older versions still work, but every agent additionally loads the project's `CLAUDE.md`). The approval gate relies on the `UserPromptExpansion` hook event; where that event does not exist or hooks are disabled, the kit says that the gate is not enforced and carries on under the prompt rules alone.

 `pip install pypdf` is an optional second PDF reader for files whose page count the kit cannot read itself (the scan says when).

## Use

```text
mkdir my-course && cd my-course && claude
/book-kit:init "ชื่อหนังสือ"      # scaffold: sources/, book.config.json, permissions, minimal CLAUDE.md
# put sources in sources/ (numeric prefixes = chapter structure — see sources/README.md)
# book.config.json: "content": { "level": 1 | 2 }, "ui": { "palette": "notebook" | "vivid" | "ocean" | "sunset" }
/book-kit:build-book              # extract → plan → write → build → validate → audit → REPORT → ASK → STOP
/book-kit:apply-fixes             # typing it IS the approval: one remediation batch, recheck, stop (a plain "yes" starts nothing)
/book-kit:update-book             # after source edits, renumbered chapters, a new content.level, config changes: only what changed
/book-kit:audit-book [chapters]   # audit only, changes nothing
/book-kit:design [palette|wish]   # change colours/look and rebuild; content untouched
```

Open `book/index.html`. Every command can be run again after an interruption; finished extractions and chapters are not repeated. The book project is the directory Claude Code was started in; the plugin never writes into itself, and `book/` is generated — never edit it by hand.

## Configuration (`book.config.json`)

| Key | Default | Meaning |
|---|---|---|
| `book.title`, `subtitle`, `author` | — | cover and page titles |
| `book.language` | `"th"` | language of the content and of the UI strings (`th`; anything else falls back to English UI) |
| `content.level` | `2` | `1` exam review · `2` study |
| `content.audience`, `content.style_notes` | — | who it is for / tone notes the writer follows (never override the content rules) |
| `content.recall_questions` | `true` | level 1 only: end each chapter with recall questions |
| `ui.palette` | `"notebook"` | `notebook`, `vivid`, `ocean`, `sunset`, or `custom` |
| `ui.custom_palette` | — | `{label, base, paper: neutral|warm|cool, chroma: 0.5–1.6, hues: {primary|warn|example|formula|summary|note|recall or c1…c7: hue angle or hex}}` |
| `ui.features.math_katex_cdn`, `mermaid_cdn` | `false` | load KaTeX / Mermaid from a CDN (reader must be online) |
| `pipeline.max_parallel_agents` | `6` | upper bound for parallel subagents |
| `pipeline.models` | — | optional model per role, e.g. `{"writer": "opus"}`; roles `analyst`, `architect`, `writer`, `auditor`, `builder`. Defaults: analyst/writer/builder `sonnet`, architect/auditor `opus` |
| `audit.max_source_spot_checks` | `10` | source locations one audit may open, shared out among the chapter auditors (each keeps at least 1) |
| `audit.max_fix_batches` | `5` | fix batches one audit report may have; after that the script approves no further batch (run `/book-kit:audit-book` for a fresh report that carries what is still open) |
| `audit.approval_gate` | `"auto"` | `auto`: a fix batch needs a typed `/book-kit:apply-fixes` on record (enforced once the plugin's hook has run in the project) · `off`: not checked by script — for machines where hooks cannot run |

## Layout

```text
.claude-plugin/plugin.json   manifest (name: book-kit)
skills/rules/                orchestration rules — loaded by the commands
skills/content/              content contract (levels, content rules, ids, coverage) — preloaded into architect, writer, auditor
skills/{init,build-book,update-book,audit-book,apply-fixes,design}/   commands (/book-kit:<name>)
agents/                      5 subagents (book-kit:<name>)
hooks/hooks.json             the approval gate: runs scripts/gate_hook.py when the user types a kit command
scripts/                     scan_sources · extract_office · sync_state · build_book · validate_book · make_palette · init_project · gate_hook · kitlib
templates/                   page shells, palettes.json, assets (style.css, app.js, fonts) — read-only
scaffold/                    files copied into a new project by /book-kit:init
```

Full guide (Thai): [README_TH.md](README_TH.md). Version history: [CHANGELOG.md](CHANGELOG.md).
