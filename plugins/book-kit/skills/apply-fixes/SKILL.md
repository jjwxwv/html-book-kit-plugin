---
name: apply-fixes
description: Apply the fixes from the latest pending book audit — one remediation batch per approval, then recheck and stop. Invoke ONLY when the user runs it or has just given an explicit, unambiguous approval to apply the audit's fixes; never on your own initiative.
argument-hint: "[finding ids or severities, e.g. F1 F3 | critical+major]"
allowed-tools: Bash(python3 *) Bash(python *) Skill(book-kit:rules)
---

Apply the latest audit's fixes. Running this command IS the user's explicit approval (or it was invoked right after the user's own unambiguous "yes, apply the fixes"). One approval = one batch; never loop. First load the kit rules: invoke the `book-kit:rules` skill now unless its content is already in this conversation, and follow it strictly. Run every script from the project root as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py" ...`.

Requested scope (empty = all open findings): $ARGUMENTS

0. **Locate & guard.** Find the highest-numbered `.book-state/audits/audit-<n>.json`. If none exists or its `status` is not `"pending_approval"`, explain (nothing to apply / already applied / declined — for a declined audit the user may say "apply audit A<n>" to reopen it explicitly) and stop. Set `status` to `"approved"`.
1. **Optional scope.** If the user named specific finding ids or severities (e.g. "only critical+major"), fix only those; otherwise fix all `open` findings. Sources must not be modified under any circumstance.
2. **Route fixes** by finding type, batched per agent and per chapter:
   - `accuracy | coverage | clarity | supplement` → `book-kit:chapter-writer` (delta mode, exact sections, with the finding text + relevant extraction refs). If a coverage fix changes plan/coverage entries (e.g. an omission was unsafe), have `book-kit:book-architect` patch `book-plan.json`/`coverage.json` first.
   - `consistency` → `book-kit:book-architect` patch (ids/order/terminology decisions) then `book-kit:chapter-writer`/`book-kit:book-builder` as needed.
   - `ui` → `book-kit:book-builder`.
3. **Rebuild affected pages** via `book-kit:book-builder` (delta mode) and run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_book.py"`. Repair mechanical failures once.
4. **Recheck.** Delegate `book-kit:book-auditor`, mode `recheck`, with the list of fixed finding ids. It updates the same report: per-finding `resolution`; top-level `status` becomes `"applied"` when everything is fixed, or returns to `"pending_approval"` while anything is `still_open` or new.
5. **Report & STOP.** Print: fixed / still_open / new-from-fix counts and the report path. If anything is `still_open` or new, list it and ask exactly one question — whether to run another batch — then END YOUR TURN. Do not start a second batch on this approval. (The report is `pending_approval` again, so answering yes **or** running `/book-kit:apply-fixes` starts the next batch.) If everything is fixed, confirm briefly and point to `book/index.html`.
