---
name: apply-fixes
description: Apply the fixes from the latest pending book audit — one remediation batch per typed command, then recheck and stop. Typing this command is the user's approval; the model cannot start it.
disable-model-invocation: true
argument-hint: "[finding ids or severities, e.g. F1 F3 | critical+major]"
allowed-tools: Bash(python3 *) Bash(python *) Skill(book-kit:rules)
---

Apply the latest audit's fixes. The user typed this command: that IS the approval, for exactly one batch — the plugin's hook has recorded it and `sync_state.py --set-audit approved` spends it. One approval = one batch; never loop. First load the kit rules: invoke the `book-kit:rules` skill now unless its content is already in this conversation, and follow it strictly. Run every script from the project root as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py" …`.

Requested scope (empty = all open findings): $ARGUMENTS

0. **Locate & guard.** Run `scan_sources.py --status` and read `audit` — it describes the latest report about the edition of `content.level`: `latest` = n, `status`. Status `"approved"` is a batch that was interrupted (`audit.hint`): say so in one line and continue — the approval was already given. For any other status than `"pending_approval"` or `"approved"`, or no report, explain (nothing to apply / already applied / clean / declined — when the user explicitly says "apply audit A<n>" for a declined one, reopen it with `sync_state.py --set-audit pending_approval`; when `audit.other_levels` shows open findings of the other edition, say that they are applied after setting `content.level` back) and stop. Run `sync_state.py --set-audit approved`; if it refuses — the report is about another level's edition, no typed approval is on record (`audit.gate`), or the report already had `audit.max_fix_batches` batches (`audit.batches`) — show its message and stop: never approve in another way. If its `gate` line says "not enforced", repeat that line to the user and continue. Then read `.book-state/audits/audit-<n>.json` (this one file). Take the level L from the report.
1. **Scope.** If the user named finding ids or severities (e.g. "only critical+major"), fix only those; otherwise every finding whose `resolution` is `open` or `still_open`. Sources are never modified.
2. **Route the fixes**, batched per agent and per chapter, in this order:
   1. Type `extraction` (the extraction disagrees with its source) → `book-kit:source-analyst`, mode `fix`: the extraction file, the finding's `source` location, what is wrong. Then run `sync_state.py --stamp`.
   2. Findings that need a plan change — an unsafe omission, a supplement to add or remove, section order, a terminology decision (`coverage`, `supplement`, `consistency`) → `book-kit:book-architect`, delta mode, with the finding texts.
   3. Run `sync_state.py --plan`. Its `write` lists the chapters whose inputs changed through steps 1–2.
   4. `accuracy | coverage | level | clarity | supplement | consistency` findings located in a chapter, and every chapter in `write` → `book-kit:chapter-writer`, one delegation per chapter: its slice plus the finding ids, locations and suggested fixes for that chapter. A chapter that is not in `write` gets a repair only — the writer edits what the findings name, not the chapter.
   5. Type `ui` → `book-kit:book-builder` for palette/template problems; a content-markup problem (a figure without a caption, a table without a header row) goes to the chapter-writer with the other findings of that chapter.
3. **Rebuild.** Run `build_book.py`, then `validate_book.py`. On FAIL apply the rules' repair routing once.
4. **Recheck.** Delegate one `book-kit:book-auditor`, mode `recheck`, audit number n, level L, with the ids of the findings this batch addressed. It writes `audit-<n>.part-recheck.json`; then run `sync_state.py --merge-audit`, which applies the results to the report: per-finding `resolution`; `status` becomes `"applied"` when nothing is open any more, or returns to `"pending_approval"`.
5. **Report & STOP.** Print what that merge printed: fixed / still_open / new-from-fix, what is still open, and the report path. If anything is `still_open` or new, list it and ask exactly one question — whether to run another batch — then END YOUR TURN. Do not start a second batch on this approval — `sync_state.py --set-audit approved` would refuse it: the report is `pending_approval` again and only the user typing `/book-kit:apply-fixes` once more starts the next batch. If everything is fixed, confirm briefly and point to `book/index.html`.
