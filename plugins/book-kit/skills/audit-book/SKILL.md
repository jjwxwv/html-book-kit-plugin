---
name: audit-book
description: Audit-only pass over the current book. Reports findings and asks for approval; changes nothing.
disable-model-invocation: true
argument-hint: "[chapter ids, e.g. 2 3]"
allowed-tools: Bash(python3 *) Bash(python *) Skill(book-kit:rules)
---

Run a standalone audit of the current book. This command never modifies `book/`, drafts, the plan, or sources. First load the kit rules: invoke the `book-kit:rules` skill now unless its content is already in this conversation, and follow it strictly. Run every script from the project root as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py" …`.

Requested chapters (empty = whole book): $ARGUMENTS

0. Run `scan_sources.py --status`. If `plan` is false or `level.book_exists` is false, tell the user to run `/book-kit:build-book` first and stop.
1. If the scan shows work waiting — `extract` not empty, `state`, `stamp`, `replan`, or anything in `level.write_full` / `level.write_delta` — the book is behind its sources or its configured level: say so and recommend `/book-kit:update-book`. Continue only if the user asked for an audit anyway.
2. Run `validate_book.py` (the mechanical layer the auditors read). If it FAILs, the pages do not match the drafts, the plan or the sources: show `problemCodes`, tell the user to run `/book-kit:update-book`, and stop — auditing a book that does not validate wastes tokens.
3. Chapters to audit = the ids the user named above, else every id in `chapters`. Take `audit.next` (= n) and `audit.spot_checks_per_chapter` from the scan. Delegate one `book-kit:book-auditor` per chapter (mode `chapter`, n, level `config.level`, the chapter id, the spot-check budget) and one in mode `cross`, in parallel within `config.max_parallel_agents`. Where the scan's `audit.prior.parts` lists ids for a part you audit (`ch-<id>`, `cross`), add the report path (`audit.prior.report`) and those ids to that auditor's brief — an open finding is re-examined, never dropped. When all have finished, run `sync_state.py --merge-audit --mode full --expect <chapter ids> cross` (`--mode scope` when the user named chapters).
4. **Gate — REPORT → ASK → STOP.** Print what the merge printed: status, severity counts, the findings one line each, the report path. If there are findings, ask exactly one question — whether to apply the fixes, which the user approves by typing `/book-kit:apply-fixes` — then END YOUR TURN. If the user declines now or later, run `sync_state.py --set-audit declined` and change nothing else.
