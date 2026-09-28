---
name: build-book
description: Full pipeline — extract sources, plan, write Thai chapters, build the HTML book, validate, audit, then stop at the approval gate.
disable-model-invocation: true
allowed-tools: Bash(python3 *) Bash(python *) Skill(book-kit:rules)
---

Build the Thai HTML summary book end-to-end. First load the kit rules: invoke the `book-kit:rules` skill now unless its content is already in this conversation, and follow it strictly — especially the audit gate and token discipline. Run every script from the project root as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py" ...`.

0. **Preflight.** If `book.config.json` is missing here, tell the user this directory is not a book project (run `/book-kit:init`) and stop. Read `book.config.json`. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan_sources.py" --status`. If `sources/` has no source files, explain the expected layout (see `sources/README.md`) and stop. Show a one-line summary: N added / N changed / N unchanged / N removed / N renamed. If renamed > 0, remap each rename now, exactly as in `/book-kit:update-book` step 1: update the `source:` path in that extraction's frontmatter (zero re-reads); if the move changed the chapter folder or the numeric prefix, treat both chapters as affected and hand the move to the architect in step 2. Then, if removed > 0, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/prune_state.py"` so stale extractions don't block validation.
1. **Extract.** For every added/changed `.pptx`/`.docx`, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/extract_office.py" "<path>"` first. Then group added/changed sources by top-level chapter and delegate each group to the `book-kit:source-analyst` subagent (parallel across chapters when independent). Skip unchanged sources that already have extractions. Collect the analysts' unit counts and gap notes.
2. **Plan.** Delegate `book-kit:book-architect` (full mode; pass the extraction file list, existing plan path if present, and analyst gap notes). Result: `book-plan.json` + `coverage.json`. If it reports `gaps_for_analyst`, route exactly those bounded gaps back to `book-kit:source-analyst`, then have the architect finalize. If any coverage entry is `unresolved` because evidence is missing, surface it now.
3. **Write.** For each top-level chapter in the plan, delegate `book-kit:chapter-writer` with its plan slice + the extraction paths its `covers` reference (parallel when possible).
4. **Build.** Delegate `book-kit:book-builder` (full build). It runs `validate_book.py` itself and repairs mechanical failures once. If validation still fails, print the failures and stop (no audit on a broken build).
5. **Commit manifest.** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan_sources.py" --commit`.
6. **Audit.** Delegate `book-kit:book-auditor`, mode `full`.
7. **Gate — REPORT → ASK → STOP.** Print: audit status, severity counts, prioritized findings (one line each), report path, and where to open the book (`book/index.html`). If there are findings, ask exactly: "พบประเด็นตามรายการข้างต้น ต้องการให้แก้ไขหรือไม่? (สั่ง /book-kit:apply-fixes หรือตอบยืนยัน)" — then END YOUR TURN. Do not fix, do not re-audit, do not continue for any reason. If zero findings, congratulate briefly and point to `book/index.html`.
