---
name: audit-book
description: Audit-only pass over the current book. Reports findings and asks for approval; changes nothing.
disable-model-invocation: true
argument-hint: "[chapter ids, e.g. 2 3.1]"
allowed-tools: Bash(python3 *) Bash(python *) Skill(book-kit:rules)
---

Run a standalone audit of the current book. This command never modifies `book/`, drafts, plan, or sources. First load the kit rules: invoke the `book-kit:rules` skill now unless its content is already in this conversation, and follow it strictly. Run every script from the project root as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py" ...`.

Requested scope (empty = whole book): $ARGUMENTS

0. If `book/index.html` or `.book-state/plan/book-plan.json` is missing, tell the user to run `/book-kit:build-book` first and stop.
1. Optionally run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan_sources.py" --status` first; if sources changed since the last commit, warn that the book may be stale and that `/book-kit:update-book` is the right command — then continue only if the user asked for an audit anyway.
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_book.py"` (mechanical layer) so the auditor can read `validate-report.json`.
3. Delegate `book-kit:book-auditor`, mode `full` (or mode `scope` with the specific chapters if the user named them above).
4. **Gate — REPORT → ASK → STOP.** Print audit status, severity counts, prioritized findings, report path. If there are findings, ask exactly one question — whether to apply the fixes (`/book-kit:apply-fixes`) — then END YOUR TURN. If the user declines now or later, set the report's `status` to `"declined"` and change nothing.
