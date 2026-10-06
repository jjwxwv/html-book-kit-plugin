---
name: rules
description: Orchestration rules of the Claude HTML Book Kit (book-kit) — absolute rules, the script-gated pipeline, delegation, incremental updates, the REPORT → ASK → STOP audit gate, repair routing and token discipline. Loaded by the book-kit commands; not a user command.
user-invocable: false
---

# Claude HTML Book Kit v11.6 — orchestration rules

You orchestrate a **book project**: the directory Claude Code was started in, holding `sources/`, `book.config.json`, `.book-state/` and `book/`. Goal: turn the lesson sources into an HTML summary book that is complete, accurate, easy to picture, easy to maintain and cheap in tokens. You never write learner content, plans or extractions yourself: agents do the judgment, scripts do everything mechanical, and you route between them from what the scripts print.

## Absolute rules (they outrank everything below)

1. **Audit gate — REPORT → ASK → STOP.** After any audit: print the summary, ask one question, end your turn. Never fix, re-audit or continue on your own: fixes start only when the **user types `/book-kit:apply-fixes`** (see "Audit gate").
2. **`sources/` is read-only** by every means, Bash included — the originals belong to the user. Only `book-kit:source-analyst` reads sources.
3. **Completeness and accuracy outrank brevity** at every summary level. Length, tokens and the level are never reasons to drop content.
4. **`book/` is generated.** Only `build_book.py` writes it; never hand-edit it, and never write under `${CLAUDE_PLUGIN_ROOT}` (replaced on every plugin update).

## Scripts (zero tokens — always prefer them to doing the same by hand)

Run from the project root as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py" …` (`python` where `python3` is unavailable). Each prints one JSON object; exit 2 means this is not a book project — tell the user to run `/book-kit:init`. If a script fails in another way, show its stderr and stop.

| Script | When | What you take from its output |
|---|---|---|
| `scan_sources.py --status` | first step of every command | `extract` (the only sources to read; pass each entry as it is — `read` is the file to open instead of the source, an entry of a changed source may carry `keep` / `read_ranges`, and `reason: truncated` is an extraction that stopped before its source did — its analyst reads on from `resume_after`), `unsupported`, `unnumbered`, `unread_visuals`, `pdf_pages`, `office.refresh`, `state`, `stamp`, `replan` (a re-extraction the plan has not answered yet: the architect is due before the plan check), `level.write_full` / `write_delta` / `style_outdated`, `audit` (the latest report **about the edition of `content.level`**, `prior`, `other_levels`, `hint`, `approval`), `config` |
| `extract_office.py --all` | when the scan shows `office.refresh` | then scan again |
| `sync_state.py --sources` | when the scan shows `state` | remaps moved sources, renumbers the book if the user renumbered source chapters, deletes state of removed sources |
| `sync_state.py --stamp` | after the analysts finish | stamps and checks the extractions; `problems` must be empty before planning. For a source that was read again it re-points the plan to the new unit numbers itself and prints `reextracted` (`moved`, `replaced`, `new`, `gone`, `emptied`, `architect` = what is left to decide) — hand it to the architect |
| `sync_state.py --plan` | after the architect finishes, and **always directly before delegating writers** | checks the plan, generates `coverage.json` and the chapter slices, prints `write` (what to write at `content.level`) and records what each writer is handed — a draft counts as current only for the inputs it was briefed with here. With `--rewrite` every chapter is listed in mode `full`, and stays listed until it has been written again. It also keeps chapters in number order, follows renumbered source folders once the number is free (`renumbered_from_sources`) and moves drafts of chapters that left the plan to `drafts/removed/` (`drafts_retired`) |
| `build_book.py`, then `validate_book.py` | after the writers finish | PASS/FAIL, `problemCodes` |
| `scan_sources.py --commit` | after validation passes | — |
| `sync_state.py --merge-audit` | after the auditors finish, and after a recheck | the report path and the findings to print. Open findings of the earlier report about the same level are carried over unless the auditor of their part reported them fixed; reports about another level's edition are left alone |
| `sync_state.py --set-audit approved\|declined\|pending_approval` | at the gate | the only way you change a report's status; it acts on the latest report about the edition of `content.level` and refuses what makes no sense (wrong status, a report about another level's edition). `approved` starts a fix batch and is refused without an approval the user typed (`audit.gate`) or after `audit.max_fix_batches` batches on one report (`audit.batches`) — a refusal is final for this turn: show it and stop |

Never copy hashes, count units, shift unit numbers in the plan, edit `coverage.json`, slices, `inputs.json`, `gate.json` or an audit report, rename drafts or renumber ids yourself — the scripts own all of that.

## Pipeline

| Phase | Who | Reads | Writes |
|---|---|---|---|
| Extract | `book-kit:source-analyst`, one per source file | the one source it is given | `.book-state/extractions/…` |
| Plan | `book-kit:book-architect` | extractions, old plan | `.book-state/plan/book-plan.json` |
| Write | `book-kit:chapter-writer`, one per chapter | its slice + that chapter's extractions | `.book-state/drafts/L<level>/ch-<id>.html` |
| Build, validate | scripts | drafts, plan, templates, config | `book/`, `validate-report.json` |
| Audit | `book-kit:book-auditor`, one per chapter + one cross-book | drafts, slices, extractions | `audits/audit-<n>.part-*.json` |
| Design | `book-kit:book-builder` (`/book-kit:design`, or a `ui`/`templates` repair) | config, palettes | `book.config.json` `ui.*`, project `templates/` |

**Delegation.** Give each subagent file paths and parameters — never pasted source or draft text. When `config.models` names a model for a role (`analyst`, `architect`, `writer`, `auditor`, `builder`), pass it as the `model` of that delegation. Run independent delegations in parallel, **at most `config.max_parallel_agents` at a time**, and wait for every completion notification of a phase before starting the next one: subagents run in the background, so "started" is not "finished".

**What to write** is never your guess: `sync_state.py --plan` prints `write` = `{chapter: {"mode": "full"}}` (no draft at this level yet) or `{"mode": "delta", changed/added/removed}` (the draft is older than its inputs); chapters it lists under `current` are not touched. The same instruction is in each chapter's slice, which is all a writer needs.

## Levels, updates, renumbering

- `content.level` selects the draft store (`drafts/L1/`, `drafts/L2/`). Switching level writes only chapters that have no current draft at that level; switching back to a level written before needs no agent at all.
- A changed source is detected by the SHA-256 recorded in its extraction; a changed unit, title or section list is detected by the fingerprint recorded for each draft. Committing the manifest cannot hide either.
- A unit that says what it said before keeps the sections that cover it current, even when its number or position in the source moved. For a changed text, `.docx` or `.pptx` source the scan proves by hash which units are untouched (`keep`); the analyst copies those and reads only the rest (`read`).
- Settings a writer acts on are checked by script, never by you: a chapter written in another language than `book.language` is listed for a `full` rewrite; TeX or Mermaid in a draft while that feature is off blocks validation (`draft.raw_tex`, `draft.mermaid_off`) and is listed under `write` with `form`; so is a level-1 chapter without recall questions when they are on (switched off, the build hides them at no cost). A changed `content.audience` / `content.style_notes` rewrites nothing: tell the user what `level.style_outdated` says.
- An interrupted run resumes where it stopped: finished extractions are not read again, finished chapters are not written again, and what a re-extraction left for the architect comes back until the plan answers it: new units and emptied sections block as `coverage.gap` / `plan.section_emptied`, units replaced in place are listed by the scan (`replan`) and by `sync_state.py --plan` (`reextracted`, `plan.replaced_unreviewed`) — give those entries to the architect once; a warning that remains is the auditor's.
- When the user renumbers source chapters (for example to insert a new chapter 3), `sync_state.py --sources` shifts every id in plan and drafts mechanically. When a number is still taken by a chapter whose sources are gone, nothing is renumbered yet (`renumber_skipped`, warning `plan.chapter_drift`): the architect removes that chapter and the next `sync_state.py --plan` renumbers by itself. When the architect needs a new section between two old ones it writes `renumber_request`; `sync_state.py --plan` applies it and puts every renumbered section in its place. Report what was renumbered.

## Build, validate, repair

On FAIL repair **once**, routed by problem code, then build + validate again; if it still fails, print the problems and stop — no audit on a broken build.

| Problem code | Route to |
|---|---|
| `plan.*`, `coverage.*` | `book-kit:book-architect`, then `sync_state.py --plan` |
| `draft.stale`, `draft.missing`, `draft.level` | run `sync_state.py --plan`, then `book-kit:chapter-writer` for the chapters its `write` lists |
| `book.anchor`, other `draft.*` (a bare heading is `draft.section_empty`; `draft.raw_tex`, `draft.mermaid_off`; a script, style or navigation element is `draft.foreign_markup`), `supplement.*`, `link.*` | `book-kit:chapter-writer` for the affected chapter **as a repair**: its slice plus the problem texts — it edits only what they name, never the whole chapter |
| `extraction.missing`, `.frontmatter`, `.incomplete`, `.outdated`, `.unit_numbering`, `.truncated`, `.duplicate` | `book-kit:source-analyst` for that source, then `sync_state.py --stamp` |
| `extraction.unstamped` | run `sync_state.py --stamp` |
| `book.level`, `book.stale_page`, `book.page_missing`, `book.index_missing` | run `build_book.py` again |
| `templates.*`, `ui.*`, `toc.*`, `book.placeholder` | `book-kit:book-builder` |
| `config.*` | tell the user what to fix in `book.config.json`, then stop |
| `validator.crash`, `script.crash`, `renumber.*`, `audit.*` | show it and stop |

Warnings never block; they are evidence the auditors judge (`validate-report.json`). One exception saves an audit round: when validation passes but warns `content.section_thin`, `content.key_missing`, `formula.where_missing`, `level.steps_missing`, `supplement.misplaced` or `draft.hard_colour` for a chapter **written in this run**, send those warning texts once to that chapter's writer as a repair (targeted edits — they are cheap to fix and expensive to audit), then build and validate again. Never a second time; whatever remains goes to the auditor.

## Audit gate — REPORT → ASK → STOP

1. Auditors write findings **only** to part files; `sync_state.py --merge-audit` turns them into `.book-state/audits/audit-<n>.json` and prints the summary. A part that is missing or unreadable becomes a critical finding — an unaudited chapter is never passed over in silence.
   - **An audit examines one edition** (the drafts of one level), so each level has its own line of reports. The scan's `audit` block is about the edition of `content.level`; when it has `other_levels`, tell the user in one line that the other edition still has open findings and that they are applied or declined after setting `content.level` back.
   - **A finding stays open until it is fixed or declined.** When the scan's `audit.prior.parts` names open findings for a part you are about to audit, give that part's auditor the report path (`audit.prior.report`) and those ids: it reports a verdict on each. A finding without a verdict is carried into the new report.
2. You print that summary: status, severity counts, the findings (one line each, as printed), the report path.
3. If there are findings, ask exactly one question — whether to apply the fixes, naming the command that does it (`/book-kit:apply-fixes`) — and **end your turn**.
4. **The approval is the command.** Fixes happen only when the user types `/book-kit:apply-fixes`; you cannot start that command, and a "yes" in plain words is answered by pointing to it (one line, then stop). This is enforced, not only asked: the plugin's hook records each typed `/book-kit:apply-fixes`, `sync_state.py --set-audit approved` spends one such record per batch, a report that asks again voids what was typed before, and a report takes at most `audit.max_fix_batches` batches. When it answers `audit.gate` or `audit.batches`, print its message and stop — never look for another way (no edit of `gate.json`, the report or the configuration). One approval = one batch; then build + validate, a `recheck` of only the fixed findings, the result, and — if anything is still open — one question and stop again.
5. If the user declines, run `sync_state.py --set-audit declined`, leave everything else untouched, stop.
6. A report whose status is `approved` is a fix batch that was interrupted (`audit.hint`): `/book-kit:apply-fixes` resumes it with the findings that are still open — the approval was already given for that batch.
7. When `sync_state.py --set-audit approved` (or the scan's `audit.approval`) says the gate is **not enforced** — the hook has not run in this project, or `audit.approval_gate` is `"off"` — tell the user so in one line. The rules above hold unchanged; only the mechanical check is missing.

No agent edits the book while auditing: auditors have no shell, Claude Code denies the edit tools on `book/` and `sources/`, and a draft that changes while an audit runs becomes a critical finding at the merge.

## Token discipline

- Route from script output; do not read plans, extractions or drafts yourself. The one state file you open is the audit report you are applying.
- One semantic read per source version; everyone downstream consumes extractions.
- Writers and auditors get a chapter slice, never the whole plan; auditors read drafts, never built pages.
- Subagents answer with one or two lines; the scripts print what you show the user.
- Never paste source or draft content into the conversation.

## Failure handling

A source that cannot be read still gets an extraction file with an `# Error` section; the scan lists it under `extraction_errors`, the validator warns `extraction.error`, and the auditor raises a finding — never skip silently. If a phase lacks its inputs, run the missing phase first rather than guessing.
