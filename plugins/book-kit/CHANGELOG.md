# Changelog

## v11.6.0 (2026-10-06) — audit fixes: a chapter number never inherits a draft, and numbers are reading order

Result of an audit of v11.5.0 against requirement v2-2 (findings F1–F4 and F6; F5 — a jump to an anchor counts the sections above it as read — is a design decision and was left as it is). Requirements 5 (later changes) and 8 (accuracy) did not pass: three defects sat on one path — removing, moving or renumbering chapters after the book exists — which the tests covered only in its straightforward cases. Plus a change of the agents' models.

### What was wrong, and what enforces it now
- **F1 (high) — a chapter number that was used again got its predecessor's draft.** When a chapter left the plan its draft stayed in the store. A new chapter with the same number (and, naturally, sections `4.1`, `4.2` again) found that file; a draft nothing was recorded for was taken as written from the current inputs, so the plan step listed nothing to write, validation passed with 0 problems and 0 warnings, and the page showed the new chapter's title over the old chapter's text — on `/book-kit:update-book` without any audit, because nothing was written. Now: (a) `sync_state.py --plan` moves the drafts of chapters that are no longer in a plan that passed its checks out of every level's store, to `.book-state/drafts/removed/L<level>/` (`drafts_retired`; kept, never read by the kit); (b) once a level has a ledger (`inputs.json`), a draft with neither an entry nor a briefing is never current: the plan step and the scan list the chapter in mode `full` (the reason is in the slice), the build reports it and validation blocks with `draft.stale` until it has been written. Drafts from before the ledger (no `inputs.json` yet) are adopted as before.
- **F2 (medium) — a renumbering changed numbers but not places.** Swapping the source folders of chapters 3 and 4 left the plan as `[1, 2, 4, 3]`: the table of contents read 1, 2, 4, 3 and validation passed without a warning (`plan.order` looked at sections only). A section the architect asked to have between two others (`renumber_request: ["3.4=3.2", "3.2=3.3", "3.3=3.4"]`, exactly as its rules say) got the number 3.2 and stayed last in the chapter — with a warning that told the architect to request the renumbering it had just requested. Now `renumber()` moves every renumbered chapter and section to the place its new number has; `sync_state.py --plan` keeps chapters in number order (`chapters_sorted` — chapter numbers follow the source folders, their order is never a judgment); `plan.order` also reports chapters out of order.
- **F6 (medium) — deleting a middle chapter and shifting the later ones in one step left the book misnumbered for good.** With `ch2` deleted and `ch3`→`ch2`, `ch4`→`ch3`, `sync_state.py --sources` rightly skipped the renumbering (chapter 2 was still in the plan) and handed over to the architect — whose rules forbid renumbering chapters. After the architect removed chapter 2 nothing tried again: the book stayed 1, 3, 4, validation passed, and the extraction of `sources/ch2/…` said `chapter: "3"`. Now the mismatch is read from the files on every run (`kitlib.chapter_drift`: each extraction's `chapter` against the folder its source is in), so no interrupted run can lose it: as soon as the number is free `sync_state.py --plan` renumbers by itself (`renumbered_from_sources`); until then it warns `plan.chapter_drift` and says which chapter has to leave the plan. The validator puts the same warning before the cross-book auditor. The architect's rules now say: a chapter whose sources are all gone is taken out of the plan; chapters are never renumbered or reordered by an agent.
- **F3 (low) — `--rewrite` planned the whole book again.** The slice said "from the same plan and extractions", the command ran the architect in full mode anyway — Opus tokens and a risk of new section ids for the two cases the READMEs recommend the flag for (switching KaTeX on, a new tone). `--rewrite` now keeps the plan; `--replan` is the flag that also plans again.
- **F4 (low) — a source outside a numbered chapter folder was placed without a word.** `sources/misc/notes.md` got `chapter: null` and nobody was told. The scan lists such files (`unnumbered`), the commands name them, and the validator warns `sources.unnumbered` so the auditor checks where their content went.

### Agents: models and effort
Set in each agent's frontmatter (`model`, `effort`); `pipeline.models` still overrides the model per role.

| Agent | v11.5 | v11.6 |
|---|---|---|
| source-analyst | sonnet | opus · high |
| book-architect | opus | opus · xhigh |
| chapter-writer | sonnet | opus · high |
| book-builder | sonnet | sonnet · high |
| book-auditor | opus | opus · xhigh |

Extraction and writing are the two phases that read and write the most text, so this raises the token cost of a build noticeably. To go back for a role: `"pipeline": {"models": {"analyst": "sonnet", "writer": "sonnet"}}`.

### Behaviour that changed — read this before updating
- **`/book-kit:build-book --rewrite` no longer calls the architect.** Use `--replan` when the plan itself should be made again.
- **Drafts of removed chapters move to `.book-state/drafts/removed/`** on the first update. Delete the folder when you do not need them.
- **A draft the kit has no record of blocks validation** (`draft.stale`) and is listed for a full write. This cannot happen to a draft a writer wrote after a plan step.
- **The plan's chapters are sorted by number** by the plan step; a section renumbered by `renumber_request` moves in the list.
- **New warnings**: `plan.chapter_drift`, `sources.unnumbered`, `plan.order` for chapters. None blocks.

### Migration from v11.5.0
1. Install v11.6 the same way and run `/book-kit:update-book` in each project. No `/book-kit:init`, no schema change, no source is read again because of the update.
2. If a project once had a chapter removed and a **new chapter added under the same number** before this version, check that chapter yourself — no script can tell afterwards which chapter a recorded draft was written for. If it shows the old chapter's text, delete `.book-state/drafts/L<level>/ch-<n>.html` and run `/book-kit:update-book`.
3. A book whose chapter numbers no longer match the source folders is renumbered by the first update, or reported with what has to be done (`plan.chapter_drift`).

### Tests
324 → 349 script checks (`t_v116`, 25 checks: each reproduction case of F1, F2, F6, F4, the `--rewrite`/`--replan` wording and the agents' frontmatter), plus the 28 browser checks. Validated with `claude plugin validate --strict` and the approval hook exercised with typed commands on Claude Code 2.1.291.

## v11.5.0 (2026-10-06) — audit fixes: nothing a run leaves open goes unlisted, and a draft is content only

Result of an audit of v11.4.0 against requirement v2-2 (findings F1–F7 and two smaller points). All nine requirements were met and no finding was rated high. What the audit found were places where work dropped out of sight when a run stopped, and things a script can see that were still left to an auditor's reading.

### What was wrong, and what enforces it now
- **F1 — a unit replaced in place was shown to the architect once, and never again.** When a source changes where it stood, the new unit takes its predecessor's place in the plan by script; whether it still belongs there is the architect's call. The stamp printed that entry, but the record kept only new units and emptied sections: after an interruption a second stamp, the scan and `sync_state.py --plan` all said nothing, and the plan passed. The record now keeps replaced units until they are answered: the scan lists them (`replan`, and the commands delegate the architect when it is present), `--plan` prints them again (`reextracted`, marked `pending`) with the warning `plan.replaced_unreviewed`, and the validator puts the same warning before the cross-book auditor. The record closes when the architect writes `"reextracted_reviewed": ["<extraction>"]` into the plan (a request key like `renumber_request`: the script applies it and takes it out), or when the unit no longer sits where the script put it. It never blocks. An extraction corrected in place for the same source version (an audit fix) needs no review — the source did not move.
- **F2 — `sync_state.py --plan` accepted an invalid `content.level`.** It fell back to level 2, answered `OK` and listed the book for writing; only the validator, after the writers, said `config.level`. The plan step now reports every fatal configuration issue and lists nothing.
- **F3 — `read_ranges` named changed lines one by one.** `["l.13", "l.15", "l.17"]` is now `["l.13-17"]`: runs join across blank lines, never across a line that belongs to a kept unit.
- **F4 — version labels in file headers had been left behind** (`content` skill: v11.3; `kitlib.py`, `build_book.py`, `app.js`: v11.2). Headers carry no version of their own any more; a test checks that no header names another version than `KIT_VERSION`.
- **F5 — an extraction that stopped before its source did was planned and written from.** `--stamp` reported `extraction.truncated`, but the file was stamped, so the next scan offered nothing to read: a chapter was planned and written from notes known to be incomplete, validation blocked afterwards, and the chapter was written a second time. The scan now lists such a source under `extract` with `reason: truncated`, `previous_units` and `resume_after` (`p.20`, `s.7`, `l.240`); the analyst reads on from there and keeps the units it has.
- **F6 — nothing checked what a draft brings along.** A `<script>`, a `<style>`, an inline `style="color:#fff"`, an SVG with `fill="#000000"` all passed without a word; the contrast guarantee covered the stylesheet and the palettes only, and a figure drawn in literal black is invisible on the dark theme. Now: `<script>`, `<style>`, `<link>`, `<iframe>`, `<object>`, `<embed>`, `<base>`, `<meta>`, `<nav>`, `<form>`, `on…=` attributes and `javascript:` links block (`draft.foreign_markup`; a warning for unstamped pre-v11 drafts). A colour written as a literal in a `fill`, `stroke`, `color`, `stop-color`, … attribute or in a `style` attribute is reported (`draft.hard_colour`) — a warning, because a figure may be *about* those colours: the writer gets it in the one repair pass, the auditor judges what remains. CSS variables, `currentColor`, `none`, `inherit`, `transparent` and `url(#…)` are what a draft is expected to use and are not reported; neither is text or a code sample that mentions a colour.
- **F7 — `--rewrite` was a request for one call.** If a writer never wrote (a failure, an interruption), validation passed on the old draft and the next plan step listed nothing. The request is now part of each chapter's briefing: a chapter that still is the file it was when the rewrite was asked for is `draft.stale`, and every later plan step and scan lists it in mode `full` until it has been written — with or without the flag.

### Smaller points
- **Facts the audit merge establishes itself are not doubled.** "No audit part for ch-3" and "the draft changed while the audit ran" were raised anew by every merge *and* carried over from the earlier report. They are marked as the script's own (`by: script`); when the same part is merged again they are either raised once or — no longer true — closed.
- **A planned supplement marked twice** (`data-supplement` on two elements) is reported (`supplement.misplaced`).
- The approval hook was exercised with typed commands in Claude Code 2.1.290 (`claude -p`, not logged in — the event fires before any request): `command_name` arrives as `book-kit:apply-fixes`, the short form `/apply-fixes` resolves to it, a command name inside a sentence is no command. The READMEs say what was observed and what still rests on the documentation.

### Behaviour that changed — read this before updating
- **`/book-kit:build-book --rewrite` cannot be abandoned half-way.** Chapters not yet written again block validation until they are; run any build or update to finish them.
- **A draft with a script, style or navigation element no longer validates.** `/book-kit:update-book` sends the chapter to its writer as a repair.
- **New warnings on books that validated before**: `draft.hard_colour` (literal colours in existing drafts), `plan.replaced_unreviewed`. Neither blocks.
- Unchanged by design: `extraction.locator_gap` (a page or run of lines without a unit) stays a warning for the auditor — blank pages exist, and a block would stop a build on them.

### Migration from v11.4.0
1. Install v11.5 the same way and run `/book-kit:update-book` in each project (`/book-kit:init` is not needed again). No file format under `.book-state/` changed; nothing is read or written again because of the upgrade.
2. An extraction that v11.4 stamped although it stops early is listed as `truncated` by the first scan and read on.
3. Audit reports written by v11.4 keep working; their script-made findings carry no `by` mark and are carried like any other finding until an auditor gives a verdict.

### Verified
- `python3 tests/run_tests.py --browser`: 352 checks pass (324 script checks, 23 of them new, + 28 in headless Chromium), also with Python warnings treated as errors. Two checks that encoded the old behaviour were changed with it: a rewrite holds until it happened; a replaced unit keeps the record open.
- Run against the unmodified v11.4.0 scripts, the new battery fails where it should on F1 (5 of 7 checks; the two that pass are cases v11.4 already handled), F2 and F3, and stops there (the F3 check calls a helper with an argument v11.4 does not have). F5, F6 and F7 were reproduced against v11.4.0 by hand during the audit instead.
- Re-run by hand on v11.5 with hand-played agents, on a project with nested sections (2.2.1), a `.pptx`, a `.docx` and a 25-page PDF: F1 — an in-place edit of the `.docx`: the record survives two stamps, a scan and two plan steps, and is closed by the confirmation key; F3 — the same edit is handed out as `l.13-17`; F5 — the PDF extraction cut to 20 pages is listed again with `resume_after: p.20`, the analyst reads on, the five new units block as `coverage.gap` until the plan covers them, and no chapter is written twice; F6 — literal colours warn (4 found, the `var(--fig-1)` stroke is not among them), a script, a nav and a style element block. On the sample project: F2 — a new project with `content.level: 3` gets `config.level` from the plan step and no slices; F7 — a rewrite of four chapters, two written, then two more: the open ones stay listed and block until they are written.
- `claude plugin validate --strict` (Claude Code 2.1.290) passes for the plugin and the marketplace manifest. The approval hook, loaded with `--plugin-dir` from this version: `/book-kit:audit-book` records `seen` only, `/book-kit:apply-fixes` and `/apply-fixes F1` each record one approval, a sentence that mentions the command records nothing.
- Both preview editions rebuilt: they differ from v11.4 in the version stamp and in the first line of `assets/app.js`, nothing else.
- Not verified, as before: a complete run with real agents in a logged-in session.

## v11.4.0 (2026-10-06) — audit fixes: Office updates get their file, the plan follows a re-extraction by script, an approval is a typed command

Result of an audit of v11.3.0 against requirement v2-2 (findings H1, M1, M2, L1–L3; L4 was an observation and is unchanged). All nine requirements were met on the normal path. The audit reproduced one regression that v11.3 itself had introduced and two places where the kit still left to a prompt what a script can decide.

### What was wrong, and what enforces it now
- **H1 — a changed `.pptx` / `.docx` reached its analyst without the file to open (regression of v11.3, G3).** The scan entry used the key `read` for two things: the path of the pre-extracted copy, and — for a changed source with units proven untouched — the list of ranges still to read. The second overwrote the first (`"read": ["s.2"]`), so the analyst held only the path of a binary it must not open; following its own rule it would write an `# Error` extraction, after which the plan check failed on references to units that no longer existed. The ranges now have their own key, `read_ranges`; `read` is always the file. The same held for text sources read through a wrapped copy. `sync_state.py --stamp` also deletes the pre-extracted copy of the previous version of a source, so a source never has two copies lying in `extracted-office/` (before, they stayed until `--sources` ran).
- **M1 — after a re-extraction the plan's unit numbers were shifted by the architect, unchecked, from a map that was printed once.** The stamp reported `U2 -> U3`, `U4-U5 -> U5-U6` and the architect was asked to rewrite `covers` / `merged` / `omitted` accordingly. If it closed only the reported gap, `sync_state.py --plan` answered `OK` with no warning while a section's slice listed the wrong units; and a run that stopped between the stamp and the architect lost the map (a second stamp printed nothing, both commands then skipped the architect). Now the scripts own it, as they own section ids: `sync_state.py --stamp` re-points every reference itself — units that only moved, and units **replaced in place** (between the same two unchanged neighbours as many old units disappeared as new ones appeared; each new one takes its predecessor's place). References to units without a successor are removed. What needs judgment stays on record in `plan/reextracted.json` until the plan answers it: a unit that is new is a `coverage.gap` whose message says which unit it follows, a section that lost every unit blocks with `plan.section_emptied`. `sync_state.py --plan` runs the same step first, so an interrupted run cannot continue with shifted numbers, and the record prevents a second shift. "Extracted again" is read from the units' own texts, so an extraction corrected in place for the same source version (an audit fix) is covered too: it is reported, and nothing moves.
- **M2 — "one approval = one fix batch" existed only as a sentence in the rules.** `--set-audit approved` → recheck with a finding still open → `pending_approval` → `--set-audit approved` could be repeated without limit and without the user; nothing counted batches. Three mechanical layers now: (1) `/book-kit:apply-fixes` has `disable-model-invocation: true` — Claude Code does not let the model start it; (2) the plugin ships a hook (`hooks/hooks.json` → `scripts/gate_hook.py`) on `UserPromptExpansion`, the event that fires only when the **user types** a command. It records each typed `/book-kit:apply-fixes` in `.book-state/audits/gate.json`; `sync_state.py --set-audit approved` spends one record per batch and refuses without one (`audit.gate`); a report that asks for approval (a merge with findings, a recheck with something still open) voids whatever was typed before the question; (3) one report takes at most `audit.max_fix_batches` batches (default 5; `audit.batches`). An interrupted batch is resumed without a second approval, as before.
- **L1 — the kit's own header lines of a pre-extracted copy counted as content.** Line 1 carries the SHA-256 of the source and so changes with every edit: it was put on the analyst's read list, and a first unit whose locator began at line 1 could never be proven untouched. Header lines are now neither content nor part of a unit's hash (`unit-sources.json` entries are re-recorded once, version 2).
- **L2 — `--rewrite` pointed at a list the plan step never printed.** `sync_state.py --plan --rewrite` lists every chapter in mode `full` (slices and briefing included); the build command calls it.
- **L3 — no Claude Code version was named.** The READMEs say what the kit was checked on (2.1.289), from which version `omitClaudeMd` takes effect (2.1.271) and what the approval gate needs.

### Behaviour that changed — read this before updating
- **A plain-language "yes" no longer starts the fixes.** The approval is the typed command `/book-kit:apply-fixes`; Claude answers a "yes" by pointing to it. The audit of v11.3 had proposed to count user messages with a `UserPromptSubmit` hook. That event also fires when a background subagent reports back (Claude Code hooks reference), so every finished auditor would have counted as a user message. `UserPromptExpansion` does not have that problem, at the price of requiring the command.
- **The gate enforces itself only where the hook is seen to run.** The first typed kit command in a project writes `gate.json` (`seen`). Without it — hooks disabled, a Claude Code without `UserPromptExpansion`, no Python on the hook's shell PATH — `--set-audit approved` and the scan say "not enforced" and the kit behaves as v11.3 did (rules only), with the batch limit still in force. `audit.approval_gate: "off"` switches the check off deliberately.

### Smaller points
- The scan's `audit` block carries `approval` while a report is open (`enforced`, `on_record`, `batches`, `max_batches`).
- `reextracted` entries say what was done to the plan (`plan`) and what is left (`architect`); the gap message of the plan step names each new unit by number and title.
- The project `CLAUDE.md` written by `/book-kit:init` names the command as the only approval.
- Tests that encoded the old behaviour were changed with it: the scan's ranges are checked under `read_ranges`; a unit between two unchanged neighbours is reported as replaced, not as one gone and one new.

### Migration from v11.3.0
1. Install v11.4 the same way and run `/book-kit:update-book` in each project (`/book-kit:init` is not needed again). Nothing is read or written again because of the upgrade. Checked with a project whose state was written by the v11.3.0 scripts: validation PASS before and after, no chapter to write, a pending audit report can be approved (the gate reports "not enforced" until the hook has run once).
2. The project's `CLAUDE.md` from an earlier `init` still says fixes may start "after an explicit, unambiguous approval". It can be left (the script refuses an approval without the command) or changed to name `/book-kit:apply-fixes`.
3. A changed Office source that ended as an `# Error` extraction under v11.3: run `/book-kit:update-book` again — the scan hands the file to an analyst with the correct path (`reason: retry`).
4. A project that went through a re-extraction under v11.3 keeps whatever the architect wrote into its plan; the map of that earlier re-extraction is not recoverable. If in doubt, run `/book-kit:audit-book` for the chapters that draw on the changed source.

### Verified
- `python3 tests/run_tests.py --browser`: 329 checks pass (301 script checks, 38 of them new, + 28 in headless Chromium), also with Python warnings treated as errors. Run block by block against the unmodified v11.3.0 scripts, the new battery fails where it should: H1 0 of 5, L1 0 of 1, M1 and M2 stop at their first assertion about the new behaviour; the few checks that pass there are preconditions that hold in both versions.
- The audit's reproduction cases re-run with hand-played agents: (a) the fixture `deck.pptx` and `notes.docx`, one edit each — both scan entries carry an existing `read` file plus `read_ranges` (`["s.2"]`; three lines), the `.docx` unit that starts at line 1 is kept, the stamp removes the two superseded copies; (b) two lines inserted and one definition changed in a text source that feeds three sections — the plan is re-pointed, `--plan` without any architect action fails on the one new unit and names it, and exactly one section is stale (v11.3: `OK`, three sections stale against the wrong units); (c) the approval loop — an approval without a typed command is refused, one typed command starts one batch, three further attempts in the same turn are refused, the next typed command starts batch 2.
- Both preview editions rebuilt: byte-identical to v11.3 except for the version stamp.
- `claude plugin validate --strict` (Claude Code 2.1.289) passes for the plugin including `hooks/hooks.json`, the marketplace manifest, `skills/` and `agents/`; a hooks file with an unknown event name fails that validation, so the event name is known to this version. The plugin installs from the marketplace; `claude plugin details` lists 8 skills, 5 agents, 1 hook ("no model context cost") and ~794 always-on tokens (v11.3: ~811; the rules skill grew from ~3.1k to ~3.4k tokens on invocation).

### Not verified, and limits of what was added
- **An end-to-end run inside Claude Code** — still the largest open risk, now for five versions. This version adds one more thing that only a real session can confirm: that the hook fires for `/book-kit:apply-fixes`. It was tested with event data built from the hooks reference (and the event schema found in the 2.1.289 binary); whether `command_name` of a plugin command carries the `book-kit:` prefix is not documented, so the script accepts the prefix in either `command_name` or the typed text. If the hook does not fire, the symptom is visible and safe: `audit.gate` after a typed command, or "not enforced".
- The gate is a guard against a loop that starts by accident, not a security boundary: the session may write under `.book-state/`, so a model that deliberately edits `gate.json` is not stopped by it.
- The hook command is POSIX shell (`python3 … || python …`). On Windows without Git Bash and with only PowerShell 5.1 it cannot start; the gate then reports "not enforced", and by the hooks reference Claude Code shows a non-blocking hook error for typed kit commands (not observed here).
- "Replaced in place" is decided by position. If a source swaps one topic for an unrelated one at the same place, the new unit lands in the old unit's section; the architect receives the list (`replaced`) and the auditor is the last check.

## v11.3.0 (2026-10-05) — audit fixes: findings per edition, updates that touch only what changed, settings the writer acts on

Result of an audit of v11.2.0 against requirement v2-2 (findings G1–G8). The requirement was met on the normal path; the audit reproduced eight cases in which the kit reported "done" although it was not, or spent more tokens than documented. Same plugin name and commands; an existing project keeps working and nothing is re-read or rewritten by the upgrade (see Migration).

### What was wrong, and what enforces it now
- **G1 — an open finding about one level's edition was lost or misrouted by an audit of the other level.** With a critical finding pending for the level-2 edition, a full audit at level 1 marked that report `superseded` and the scan then said `clean`, `open: 0` at level 2; a scoped level-1 audit carried the level-2 finding into a level-1 report, where it could be approved and sent to the level-1 writer. An audit examines one edition, so each level now has its own line of reports: the merge carries and supersedes only reports of the same level, `--set-audit` and the scan's `audit` block act on the latest report about the edition of `content.level`, the scan lists open findings of the other edition (`audit.other_levels`), and a part file made for another level than `content.level` counts as no audit.
- **G8 — re-auditing a chapter dropped a finding nobody had answered** when the new auditor did not happen to raise it again. The scan now hands the open findings of each part to the next audit (`audit.prior`), the auditor of that part gives a verdict on each (`prior` in its part file), and only the verdict `fixed` closes one. A finding without a verdict is carried and marked as not re-examined.
- **G6 — an interrupted fix batch left the report `approved`,** a status `/book-kit:apply-fixes` answered with "nothing to apply". The scan says so (`audit.hint`), `--set-audit approved` accepts an approved report (`resumed`), and the command continues with the findings that are still open.
- **G3 — a one-line source edit rewrote every section that drew on that file.** The section fingerprint contained unit numbers and the analyst's wording, and a re-extraction changes both. Now: (a) fingerprint version 2 leaves out the unit number, the locator and flag values — a unit that only moved keeps its sections current; (b) `.book-state/unit-sources.json` records, per unit, a hash of the lines or slides it was read from; for a changed text, `.docx` or `.pptx` source the scan proves which units are untouched (`keep`, with their new position) and which ranges remain to be read (`read`), and the analyst copies the former verbatim; (c) for sources without such proof (PDF) the analyst extracts freshly and then keeps the old wording of units that say the same; (d) `sync_state.py --stamp` prints `reextracted` — kept / moved / new / gone units — which the architect uses to re-point the plan.
- **G4 — settings a writer acts on were invisible to the freshness and validation layer.** Turning KaTeX off left raw TeX on the page with PASS and no warning; changing `book.language` produced `lang="en"` pages with Thai content; switching recall questions changed nothing. Now the ledger records the language each draft was written in (a mismatch lists the chapter for a `full` rewrite and fails `draft.stale`); TeX or Mermaid in a draft while the feature is off blocks (`draft.raw_tex`, `draft.mermaid_off`) and is listed for the writer under `write.form`; a level-1 chapter without recall questions while they are on is listed too (`recall_missing`), and switched off they are hidden by the build at no token cost. A changed `content.audience` / `content.style_notes` rewrites nothing by itself: the scan names the chapters that keep the old style (`level.style_outdated`).
- **G2 — an unread tail of a text source passed in silence** when it was shorter than 2 % of the file (40 lines of a 2040-line file, 120 of 6000). Content lines after the last located line now block from 8 on (`extraction.truncated`) and are put before the auditor from 3 on (`extraction.locator_gap`).
- **G5 — two sources could be given the same extraction path** (`ch5/lecture/slides.md` and `ch5/tutorial/slides.md`; `5.1 notes.md` and `5.1 notes.txt`): two analysts overwrote each other and the build could never pass. Paths are now assigned without clashes (extension, then sub-folder, then a counter); existing paths never change.
- **G7 — a repair could be read as "write the whole chapter":** after a first build every slice still said `"mode": "full"`, and the rules told repairs to take the mode from the slice. The build sets the slice of every current chapter to `"mode": "none"`, and rules and writer define a repair as targeted edits that ignore `write`.

### Smaller points
- `draft.missing` / `draft.level` are routed through `sync_state.py --plan` instead of a guessed mode.
- `--merge-audit` and the recheck judge "a draft changed while the audit ran" only against pages built at the audited level.
- Tests that encoded the old behaviour were changed with it: re-audited parts close old findings only through `prior` verdicts; a book whose language is changed is stale.

### Migration from v11.2.0
1. Install v11.3 the same way and run `/book-kit:update-book` in each project (`/book-kit:init` is not needed again).
2. Ledgers are carried over automatically: each section whose v11.2 fingerprint was current gets its version-2 fingerprint, a section that was stale stays stale. Checked against projects whose state was written by the v11.2.0 scripts: nothing to write, validation PASS before and after.
3. `unit-sources.json` is created on the first `sync_state.py --plan`. Proof of untouched units needs line or slide locators; extractions of text sources made before v11.2 have none and benefit after their next extraction.
4. A draft with TeX or Mermaid while that feature is off now fails validation and is routed to its writer.
5. Pending audit reports stay valid. A report into which v11.2 had already carried findings of another level cannot be separated afterwards — decline it and audit that edition again if in doubt.

### Verified
- `python3 tests/run_tests.py --browser`: 291 checks pass (263 script checks + 28 in headless Chromium), also with Python warnings treated as errors. Every finding above has negative tests built from the audit's reproduction cases (31 new checks).
- The audit's original reproduction scripts, re-run unchanged against v11.3: each now ends in the behaviour described above.
- A dry run of a source edit with hand-played agents (insert two lines, correct one line of a 30-line source that feeds three sections): the scan kept 2 of 3 units, the stamp reported `U1 -> U2`, `U3 -> U4`, and `sync_state.py --plan` listed the two affected sections — the third, whose unit only moved, stayed current.
- Both preview editions rebuilt: byte-identical to v11.2 except for the version stamp.
- `claude plugin validate --strict` (Claude Code 2.1.289) passes for the plugin, the marketplace manifest, `skills/` and `agents/`.
- **Not verified:** an end-to-end run inside Claude Code — still the largest open risk, now for four versions. All prompt changes of this version (analyst: copy kept units verbatim; auditor: verdicts on prior findings; writer: repairs and `form`; orchestrator: passing `audit.prior` and `reextracted`) were checked against the scripts' fields only. Whether an analyst reliably keeps the old wording of unchanged units of a PDF is a property of the model, not of a script. The proof of untouched units trusts the analyst's locators: a unit that summarises content from outside the lines it names is not re-read when only those outside lines change (the changed lines themselves are always read).

## v11.2.0 (2026-10-05) — audit fixes: the gates check what is in the book, not only what the plan says

Result of an audit of v11.1.0 against requirement v2-2 (findings F1–F8). The requirement was met on the normal path; the audit reproduced five ways in which content could be missing or out of date while validation still said PASS. Same plugin name and commands; an existing project keeps working (see Migration).

### What was wrong, and what enforces it now
- **F6 — a section could be a bare heading.** Deleting the whole body of a section that covers four units validated PASS with no warning; a chapter of headings only passed with one warning. The coverage ledger is derived from the plan, so it proves that the plan accounts for every unit — not that a draft contains it. New: `draft.section_empty` (blocking) when a section that covers units has no content of its own under its heading, and the warning `content.section_thin` when it has fewer than 30 characters per covered unit (the densest section of the level-1 sample has 86). Chapter-end summary/recall boxes and navigation do not count as section content. Routed to the writer; `content.section_thin` joins the one cheap pass after a build.
- **F1 — text and Word sources were never checked for having been read to the end.** A 6000-line Markdown file with an extraction that stopped at line 2000 stamped OK. Units of line-numbered files (Markdown, text, HTML, the pre-extracted file of a DOCX) now carry `[l.a-b]` locators; the scan gives the analyst `lines`; `extraction.truncated` blocks when the units stop before the file does, `extraction.locator_gap` reports runs of unlocated lines. A long text file (over 1500 lines or 48 KB) whose extraction has no line locators is reported as `extraction.length_unverified`. The analyst prompt now says how to continue a partial read.
- **F2 — the PDF page check silently did not exist without `pypdf`/`pdfinfo`.** A 45-page PDF read to page 20 validated with zero warnings on a machine without either. `kitlib.pdf_pages_stdlib` reads the count with the standard library (page objects, also inside compressed object streams, cross-checked against a `/Count`); when the two readings disagree or the file is encrypted the count is *unknown* and `extraction.length_unverified` is raised for the auditor, who spends a spot-check on the location after the last locator.
- **F3 — a draft that was written but not yet built adopted whatever the inputs were at build time.** An interrupted run followed by a source edit produced a stale chapter that validated. The fingerprint is now taken when the writer is briefed: `sync_state.py --plan` records what each writer is handed (`briefed` in `inputs.json`); the build gives a rewritten draft *those* inputs, and a draft edited without a briefing (an audit fix) keeps its old fingerprint, so a targeted edit can no longer bring a stale chapter "up to date". `draft.stale` is routed through `sync_state.py --plan`. Renumbering carries the briefings along.
- **F4 — pictures the kit cannot read were visible to nobody.** The extractor counted them, nothing downstream read the count, and the analyst's gap note could become a supplement — invented content standing in for source content. New: the scan lists `unread_visuals` (the commands show it), validation warns `sources.visual_unread` per source for the auditor, the analyst labels such gaps `unread-visual`, and the architect may not plan a supplement for them.
- **F7 — a later audit buried an open one.** With audit 1 pending, an `/book-kit:update-book` audit of other chapters became "latest" and `/book-kit:apply-fixes` saw a clean report. `--merge-audit` now carries every still-open finding that the new audit did not re-examine into the new report (`carried_from`), marks the old report `superseded`, and removes part files of abandoned audits. The scan reports the level and the number of open findings of the latest report.
- **F5 / F8 — Office details.** Endnotes are read (`[en N]`, `### Endnotes`). Numbered lists stay numbered (`1.`), so steps remain recognisable as steps. Lines longer than 1800 characters are re-broken at spaces in the pre-extracted file, and a Markdown/text/HTML source with such lines gets a wrapped copy the analyst reads instead. Extractor version 3; sources that had endnotes or over-long lines go back on the read list once (`office_recovered` / `long_lines`), all others are only re-converted, at no token cost.

### Smaller points
- **Audit bookkeeping is done by script.** `sync_state.py --set-audit approved|declined|pending_approval` is the only way a status changes by hand; it refuses a report made at another `content.level` (`audit.level`). A recheck is a part file (`audit-<n>.part-recheck.json`) that `--merge-audit` applies; the auditor no longer edits the report. The report is `applied` only when no finding is open — findings left out of a partial batch keep it `pending_approval`.
- **A draft that changes while an audit or recheck runs** (draft ≠ the file its page was built from) becomes a critical finding at the merge. Auditors still have the edit tools — they must write their part file — so this is detection, not prevention.
- **`audit.max_source_spot_checks` is a budget again:** shared out (`total // chapters`, at least 1 each) instead of "at least 2 each", which read 24 locations in a 12-chapter book with a budget of 10.
- **Figures on phones:** below 40rem a figure scrolls sideways inside its frame and its drawing keeps a 30rem width; before, a 640-unit drawing was squeezed until its labels were about 7px.
- Locator parsing no longer reads the `s` of `lines 10-40` as a slide number.

### Migration from v11.1.0
1. Install v11.2 the same way and run `/book-kit:update-book` in each project (`/book-kit:init` is not needed again).
2. `.pptx`/`.docx` sources are pre-extracted again at no token cost; an analyst re-reads only those with endnotes or over-long lines, plus text sources with over-long lines.
3. Existing extractions of text sources have no line locators: short files are unaffected, long ones show `extraction.length_unverified` until they are next extracted.
4. A book that contains a heading-only section now fails validation with `draft.section_empty` and is routed to its writer.
5. Pending audit reports stay valid; `inputs.json` gains `briefed` on the next `sync_state.py --plan`.

### Verified
- `python3 tests/run_tests.py --browser`: 260 checks pass (232 script checks + 28 in headless Chromium). Every finding above has a negative test built from the audit's reproduction case.
- `pdf_pages_stdlib` against 18 generated PDFs (1–130 pages; plain, object streams, linearised, merged, page subset, encrypted): 14 exact, 4 encrypted ones reported unknown, none wrong.
- Independent real-browser contrast scan of both rebuilt preview editions (2 levels × 5 pages × 4 palettes × 2 themes, text nodes only — not CSS-generated labels or SVG text): no text below WCAG AA.
- A dry run of the extract phase with real `.docx`, `.pptx`, `.pdf` and a 6000-line `.md` (analysts played by hand): each source that was not read to its end blocked at the stamp, also with `pypdf` and `pdfinfo` made unavailable.
- `claude plugin validate --strict` (Claude Code 2.1.289) passes for the plugin, the marketplace manifest, `skills/` and `agents/`.
- **Not verified:** an end-to-end run inside Claude Code — still the largest open risk; the agent and command prompts changed again and were checked only against the scripts' flags and outputs. Whether the reading tool cuts lines longer than 2000 characters was not confirmed from official documentation; wrapping is harmless either way. Table rows longer than 1800 characters are not wrapped.

## v11.1.0 (2026-10-05) — audit fixes: the evidence chain from source to page is mechanical

Result of an audit of v11.0.0 against requirement v2-2 (findings F1–F16, decision D1). The page layer of v11.0.0 held up; the layer that is supposed to prove the book is complete and current did not. Same plugin name and commands; an existing v10/v11.0 project keeps working (`/book-kit:update-book` migrates its state — see Migration).

### What was wrong, and what enforces it now
- **F1 — Office sources lost content silently.** Equations typed in the Office equation editor, every text box PowerPoint wraps in `mc:AlternateContent` (i.e. every text box that contains an equation — its plain text went too), SmartArt and line breaks never reached the analyst, with no marker. `extract_office.py` is rewritten on the standard library (no `python-pptx` / `python-docx` any more): equations become `[math: …]`, wrapped shapes, SmartArt text, chart data, table cells, text boxes, footnotes, notes, alt text and hidden slides are kept, and what cannot become text is marked in place (`[visual]`, `[picture]`, `[object]`) and counted in the cache header. Caches carry an extractor version; after an upgrade only the sources that actually had dropped content go back on the read list (`office_recovered`).
- **F2 — a page could contain what the plan does not know.** A section left behind by a removed source, a repeated anchor, a heading at the wrong level or with the wrong number all validated PASS. New blocking checks: `draft.orphan_section`, `draft.anchor_dup`, `draft.heading_level`, `draft.heading_number`, `draft.section_order`.
- **F3 — nothing tied an extraction to its source version, or a draft to its inputs.** A source edited after extraction, or an extraction updated without rewriting the chapter, validated PASS, and committing the manifest erased the trace. Now: `extraction.outdated` (the SHA-256 in the extraction ≠ the source), and `draft.stale` — `build_book.py` records for each draft a fingerprint of everything it was written from (per section: title, notes, supplements, the text of every covered unit); a draft older than its inputs blocks, and the scripts name the exact sections to rewrite. The orchestrator no longer maps "changed source → chapters" by reading the plan.
- **F4 — an interrupted run read everything again.** What must be read is decided by the extraction's SHA-256, not by the manifest diff: `scan_sources.py` prints `extract`, the only sources an analyst opens. Hashes, unit counts, page/slide counts are stamped by `sync_state.py --stamp`; agents no longer copy a hash or count units. Long PDFs are persisted range by range behind a `<!-- continue -->` marker; an unfinished extraction blocks and stays on the read list.
- **F5 — one draft set per project.** Drafts live in one store per level (`.book-state/drafts/L1/`, `L2/`). Switching to a level for the first time writes it once; switching back needs no agent; a later source edit rewrites only the stale sections of the level in use.
- **F6 — inserting a chapter in the middle was undefined.** When the user renumbers source chapters, `sync_state.py --sources` derives the shift and rewrites plan ids, supplement ids, draft file names, stamps, anchors, heading numbers, links and their visible numbers, and the ledgers — in every level's store, at zero tokens, without making a draft stale. The architect asks for section renumbering with `renumber_request` instead of editing ids. `book-data.js` carries the id history and `app.js` moves a reader's stored progress to the new ids. Content rule 8: cross-references are links.
- **F7 — tracebacks on malformed state.** Plans are normalised before use (`plan.shape`); `validate_book.py` and `sync_state.py` always end in a JSON report (`validator.crash`, `script.crash`); manifest, ledger and audit files are read defensively. The console report lists at most 40 items per kind plus counts by code; the file is complete.
- **F11 — the coverage ledger could disagree with reality in four ways.** (a) Units are counted from the `## U<n>` headings of the extraction, never from the frontmatter (`extraction.unit_numbering`). (b) The plan is the single source of truth: sections list `covers` and `merged`, the plan lists `omitted`; `coverage.json` is *generated* from it, so ledger and plan cannot disagree, a unit in no list is `coverage.gap`, in two lists `coverage.duplicate`, a bad reference `plan.covers_ref`. (c) An extraction that stops before its source does blocks (`extraction.truncated` — slides counted from the file, PDF pages through `pypdf`/`pdfinfo` when available; a skipped page in the middle is `extraction.locator_gap` for the auditor). (d) Omitting a unit the analyst marked critical/important is put before the auditor (`coverage.priority_omitted`).
- **F12 / F15 — the audit did not scale and never looked at the extraction.** One auditor per chapter, in parallel, reading the *draft* and the chapter slice (a built page repeats the whole TOC: 1.9× the content bytes in the sample, 2.7× in a 12×10 book) plus one cross-book pass; `sync_state.py --merge-audit` builds the report and turns a missing or unreadable part into a critical finding. Each chapter auditor spends part of its source spot-checks on sampling critical units against the source; a mismatch is a finding of the new type `extraction`, which `/book-kit:apply-fixes` routes to the analyst (`fix` mode) — the stale chapters then follow mechanically.
- **F13 — one analyst read a whole chapter's sources.** One analyst per source file, given the path its notes go to (decided by script, so a re-extraction lands where the plan already points), the page/slide count and, for Office files, the pre-extracted markdown.
- **F14 / D1 — "complete at level 1" had no evidence, and the shipped level-1 sample dropped the meaning of a formula's symbols.** The contract stays *the level changes density, never coverage*, with three mechanical proxies (warnings the auditor must judge): every formula callout carries a where-line (`formula.where_missing`); the analyst records `keys` per unit and each must appear in the chapter (`content.key_missing`); a unit flagged `procedure` keeps its numbered steps at every level (`level.steps_missing`) — the writer no longer guesses whether "the procedure itself is examined". Also new: `terms.inconsistent` (one original term rendered two ways), `supplement.misplaced`. Both sample editions now define every symbol.
- **F8 — agents.** The rules are split: `book-kit:rules` (orchestration, commands only) and `book-kit:content` (levels, content rules, ids, coverage; ~1.7k tokens) which is what architect, writer and auditor preload — they no longer read orchestration text addressed to someone else. Writers and auditors get a chapter slice instead of the whole plan. `source-analyst` and `chapter-writer` are back on `sonnet` (the documented assignment; v11.0.0 had set them to `opus` without saying so); `pipeline.models` in `book.config.json` overrides the model per role.
- **F9 — two absolute rules were only prose.** `/book-kit:init` now **denies** the edit tools on `book/` as well as on `sources/` (and removes the old allow rule for `book/`). Analyst, architect, writer and auditor have no shell; only the builder and the orchestrator can run scripts.
- **F10 and smaller UI points.** The primary button's hover no longer brightens a solved colour pair (it measured 4.0–4.2:1 in the light theme; now a ring). A highlighted term inside muted text takes the ink colour. Without JavaScript the page follows the system dark theme.
- **F16 — unsupported files.** `.ppt`, `.doc`, `.xlsx`, … are reported with a conversion hint and are not part of the book; Office lock files (`~$…`) are ignored.

### Scripts
- New `sync_state.py` — `--sources` (remap moved sources, renumber, delete state of removed sources; replaces `prune_state.py`), `--stamp`, `--plan` (plan check, `coverage.json`, `plan/slices/ch-<id>.json`, the write list), `--renumber`, `--merge-audit`.
- `kitlib.py` now holds everything two scripts must agree on (source list, extraction parser, plan normaliser and checks, coverage derivation, draft stores, fingerprints).
- `scan_sources.py --status` prints what to do next (`extract`, `unsupported`, `office.refresh`, `state`, `stamp`, `chapters`, `level.write_full` / `write_delta`, `audit`), so the orchestrator routes from script output and reads no state file.

### Migration from v11.0.0 / v10
1. Install v11.1 the same way; in each project run `/book-kit:init` once (adds the deny rule for `book/`) and then `/book-kit:update-book`.
2. Drafts move into `drafts/L<level>/` automatically. A v11.0 plan has no `omitted` list: its omissions are read from the existing `coverage.json` (warning `plan.legacy_coverage`) until the architect next touches the plan.
3. `.pptx`/`.docx` sources are pre-extracted again at no token cost; only those in which equations, wrapped shapes, SmartArt, text boxes, chart data or footnotes were found are read again by an analyst.
4. `audit.max_source_spot_checks` keeps its meaning (per audit); it is divided among the chapter auditors, at least 2 each.
5. `prune_state.py` is gone; nothing has to be installed for Office files; `pip install pypdf` is optional (PDF page counts).

### Verified
- `python3 tests/run_tests.py --browser`: 220 checks pass (193 script checks + 27 in headless Chromium), also with Python warnings treated as errors. The battery covers each finding above with a negative test (the audit's reproduction cases now fail validation), 21 malformed-state shapes × 4 scripts, the level store, renumbering, the Office and PDF fixtures, and the browser behaviour including the hover ring, the no-JavaScript theme and progress migration.
- A dry run of every command's flow with the real scripts and hand-played agents (build with an interrupted analyst and a plan that forgets units, first switch to level 1 and back, a source edit, inserting a chapter in the middle): each step printed the fields the commands route from.
- Independent real-browser contrast audit of both preview editions (2 levels × 5 pages × 4 palettes × 2 themes): no HTML text below WCAG AA; primary-button hover 4.61–4.73:1 in the light theme (was 4.03–4.20).
- `claude plugin details`: ~0.8k tokens always-on; the content contract preloaded into architect/writer/auditor is ~1.6k tokens (the v11.0 rules skill they preloaded was ~2.9k).
- `claude plugin validate --strict` (Claude Code 2.1.289) passes for the plugin, the marketplace manifest, `skills/` and `agents/`.
- **Not verified:** an end-to-end run inside Claude Code (needs a login). The prompts were rewritten for the script-gated flow and checked against the scripts' flags and outputs by the suite, but they have not been executed; Office fixtures were generated with python-pptx/python-docx plus hand-written Office XML, not exported from Word or PowerPoint.

## v11.0.0 (2026-10-05) — requirement v2-2: summary levels, easy-to-picture writing, zero-token build, new design

Evolves v10.0.0: same plugin name, same commands plus `/book-kit:design`, same state layout. `.book-state/` (manifest, extractions, plan, coverage, audits) and existing drafts remain valid; `book/` is regenerated at zero token cost by the first `/book-kit:update-book`. Two breaking points: a project-local `templates/` override made for v10 no longer builds, and `ui.accent` / `ui.accent2` are ignored (see Migration).

### Requirement v2-2
- **#2 — configurable summary level (new).** `content.level`: `1` = exam-review summary, `2` = re-composed study summary (default; the v10 behaviour). Contract: *the level changes the density of the explanation, never the coverage* — one plan, one coverage map and one supplement list serve both levels, so a level switch rewrites drafts only (zero source reads, no re-planning). Enforcement: each draft's first line stamps its level; `scan_sources.py --status` lists `level.rewrite_chapters`; `build_book.py` refuses mixed levels and writes nothing; `validate_book.py` fails `book.level` / `draft.level`. Level 1 may end each chapter with recall questions (`content.recall_questions`, default on): questions only, each linked to the section that answers it. Non-blocking evidence for the auditor: `level.long_paragraph`, `level.recall_missing`, `chapter.summary_missing`; an omission justified by the level is caught by `coverage.brevity_reason`. New auditor check "level fidelity" and finding type `level`.
- **#3 — easy to picture (new wording).** Content rule 5 and writer rule 3 (concrete before abstract, cause → effect as steps, tables for comparisons, steps for processes, redraw source figures). The analyst flags `abstract` units and names the kind of supplement each gap needs; the architect checks every critical/important concept for a concrete anchor and may request `example` / `analogy` supplements besides `explanation` / `figure`; the auditor checks it separately. New components: `dl.terms`, `ol.steps`, `callout formula`, `callout recall`, figure colours `--fig-1…6` (+ `-soft`).
- #1 and #4–#9 are unchanged requirements; what changed in how the kit meets them is listed below.

### Build is a script now
- New `scripts/build_book.py`: assembles `book/` deterministically — pages, nested TOC, agenda, previous/next, `book-data.js`, `theme.css`, assets — and removes pages of chapters that left the plan. In v10 a model re-emitted every page, so each chapter was generated twice; the build now costs zero tokens, and delta-rebuild logic is gone (only files whose bytes changed are rewritten).
- `book-builder` now owns presentation only (palette, custom palette, template override, UI repairs) and runs on `sonnet`. Validation failures are routed by problem code (table in the rules) instead of "the builder repairs everything".
- Every page records the SHA-256 of the draft it was built from; `validate_book.py` fails `book.stale_page` when a draft changed afterwards.
- The slug in `book-data.js` is reused across rebuilds and title edits (`book.slug` overrides), so readers keep their progress.

### Design (feedback: colours and agenda/TOC)
- Concept: a lecture notebook with highlighter pens and index tabs. Each chapter owns one pen colour (TOC chip, chapter tab header, key-term highlight, progress); each callout type owns one pen and keeps a text label.
- TOC: chapter rows with coloured number chips; the current chapter expanded inside a tinted panel, the others collapsed; current-section marker; read ticks and per-chapter counts; a whole-book progress bar segmented by chapter; filter with an empty state; collapsible on desktop, a drawer with scrim on small screens.
- Agenda (index): one row per chapter with its index tab, per-chapter progress, the full nested section list, and a "continue reading" button.
- Typography: IBM Plex Sans Thai Looped (text) + IBM Plex Sans Thai (headings/UI), bundled as WOFF2 subsets (OFL-1.1, ~150 KB) — the book looks the same offline on every machine.
- Colours are generated: `scripts/make_palette.py` derives every token in OKLCH and solves lightness so the text/background pairs the stylesheet uses meet WCAG AA in both themes (85 pairs per palette and theme), re-verified by the build and the validator (`ui.contrast`). Built-in palettes `notebook`, `vivid`, `ocean`, `sunset`; `ui.custom_palette` in config; a reader-side menu (palette, text size, reset progress).
- UI strings follow `book.language` (`th`, otherwise English); v10 hard-coded Thai.

### More mechanical checks
`supplement.missing` / `supplement.unplanned` (pages ↔ plan: blocking for v11-stamped drafts, warnings for pre-v11 drafts), `plan.supplement_dup`, `plan.supplement_id`, `config.level`, `config.palette`, `config.deprecated`, `config.value`, `book.legacy_build`, `templates.contract`, `templates.palettes`.

### Token discipline
Zero-token build; a level switch reuses extractions and plan; config- or design-only changes rebuild without any agent; `pipeline.max_parallel_agents` (default 6) bounds parallel subagents; all agents set `omitClaudeMd: true` (use `content.style_notes` to steer tone); the rules skill puts the absolute rules first and stays far below the per-skill window Claude Code keeps after compaction.

### Fixed from v10.0.0
- A directory literally named `skills/{rules,init,build-book,update-book,audit-book,apply-fixes}/` shipped in the zip.
- Dead config: `content.audience`, `english_terms_on_first_use`, `supplement_policy`, `figures` were never read. `audience` (and the new `style_notes`) are now read by the writer; the other three left the scaffold.
- Builder and auditor still referred to "CLAUDE.md UI principles"; the validator's stale-extraction hint named the pre-plugin script path.
- The anchor offset was applied twice (`scroll-padding-top` + `scroll-margin-top`), leaving the scrollspy one section behind after a TOC click; the last sections of a page could never become current.
- A section was marked read as soon as its heading entered the viewport; now only once its end has been scrolled past, and never just by opening a page.

### Migration from v10.0.0
1. Install v11 the same way as before.
2. In each book project run `/book-kit:update-book`: nothing is re-read or re-written; the pages are rebuilt with the new design. Existing drafts count as level 2.
3. If the project has a `templates/` folder (a v10 design override) the build stops with `templates.contract` — rename or delete it, then use `/book-kit:design`.
4. Optional keys to add to `book.config.json`: `content.level`, `content.style_notes`, `content.recall_questions`, `ui.palette`, `pipeline.max_parallel_agents` (defaults apply when absent).

### Verified
- `python3 tests/run_tests.py --browser`: 123 checks pass. Script battery: non-project guards, init, level-2 build and validation, idempotent rebuild, slug stability, level switch (refusal of mixed levels, resumability), page freshness, supplements (strict vs pre-v11), level-1 form warnings, config errors and fallbacks, custom palette, English UI, KaTeX/Mermaid injection, removed chapters, placeholder collisions, template-override contract, the v10 coverage/TOC/link/UI/plan checks, the scan/prune lifecycle, and static contracts between templates, stylesheet, script and prompts. Headless Chromium: boot and fonts, theme/palette/text-size persistence, scrollspy and anchor landing, read marks and progress, TOC filter and collapse, copy buttons, index progress and resume, reset, mobile drawer, no horizontal overflow, no console errors.
- `claude plugin validate --strict` (Claude Code 2.1.289) passes for the plugin, the marketplace manifest, `skills/` and `agents/`.
- Colour maths checked against known sRGB ↔ OKLCH anchors; all built-in palettes: 0 failing pairs.
- **Not verified:** an end-to-end run inside Claude Code. The agent and command prompts were rewritten and reviewed but not executed, so the first real build is the test of the level-1 / level-2 writing instructions.

## v10.0.0 (2026-09-28) — plugin edition (installable Claude Code plugin)

The kit is now a Claude Code **plugin** (`book-kit`) instead of a project-folder template. Install it once (user scope, `--plugin-dir`, or a marketplace) and use it in any number of book projects. No schema changes: an existing v9.8 `.book-state/`, `book.config.json`, and `book/` remain valid.

### What moved where
- `CLAUDE.md` → `skills/rules/SKILL.md` (`book-kit:rules`, Claude-only). A plugin's `CLAUDE.md` is never loaded as context, so the orchestrator rules became a skill: every kit command loads it once per conversation (re-invocations are deduplicated by Claude Code), and it is **preloaded** into the three judgment agents (`book-architect`, `chapter-writer`, `book-auditor`) via the agent `skills` field — the same rules those agents received through `CLAUDE.md` in the project-folder form. `source-analyst` and `book-builder` are self-contained and no longer receive the ~2.4k-token rules text (one line each was added to their bodies to keep the two rules they depended on: never touch `sources/`, templates location).
- `.claude/commands/*.md` → `skills/<name>/SKILL.md`, namespaced as `/book-kit:build-book`, `/book-kit:update-book`, `/book-kit:audit-book`, `/book-kit:apply-fixes` (the bare `/build-book` etc. also resolve while no other command uses the name). `build-book`, `update-book`, `audit-book`, and the new `init` are user-invoked only (`disable-model-invocation: true`) — their descriptions cost zero context tokens per turn and Claude can never start a pipeline on its own. `apply-fixes` stays model-invocable so that a typed "yes, apply the fixes" still works; its description restricts invocation to an explicit approval, and the rules skill names it as the only command Claude may start itself. Script calls carry `allowed-tools` for `python3`/`python`.
- `.claude/agents/*.md` → `agents/` (namespaced `book-kit:<name>`; all commands and routing tables use the scoped names). Bodies unchanged except the paths above.
- `scripts/` → `${CLAUDE_PLUGIN_ROOT}/scripts/`. All scripts now resolve the **book project as the current working directory** (`--root <dir>` / `BOOK_ROOT` override) instead of `__file__/..`, and exit 2 with a JSON error when the directory is not a book project (no `book.config.json`/`sources/`). `validate_book.py` resolves templates as `--templates` → project-local `templates/` → plugin `templates/`, reports the choice in `stats.templates`, and warns `templates.missing` if none exists. `extract_office.py` gained argparse (`--root`). Validation, diff, prune, and extraction logic are otherwise byte-for-byte the v9.8 logic.
- `templates/` → `${CLAUDE_PLUGIN_ROOT}/templates/` (read-only; byte-identical to v9.8). A project-local `templates/` overrides it — the builder creates that copy only when asked to persist a restyle, and never writes inside the plugin.
- `book.config.json`, `sources/README.md`, `.book-state/README.md` → `scaffold/`, copied into new projects by `init`.

### New
- `/book-kit:init [title]` + `scripts/init_project.py`: idempotent project scaffolding (folders, `book.config.json`, READMEs, a 5-line `CLAUDE.md` that routes plain-language requests to the kit commands) and a **merge** of the permission rules into `.claude/settings.json` (adds only missing rules, keeps every other key; refuses to touch invalid JSON). Detects legacy v9.x kit files in the folder and lists them for removal. Plugins cannot ship permission rules, which is why this step exists.
- Permission rules fixed while moving them: the v9.x `Write(book/**)`-style path rules were never consulted by Claude Code (only `Edit(...)`/`Read(...)` path rules are, and they cover the Write tool too), so the kit now uses `Edit(book/**)`, `Edit(.book-state/**)`, `Edit(templates/**)`, `Edit(book.config.json)` and denies `Edit(sources/**)`; `init` reports any leftover `Write(...)` rules as ignorable.
- Marketplace file (`.claude-plugin/marketplace.json`, name `html-book-kit`) so the repository installs with `claude plugin marketplace add` + `claude plugin install book-kit@html-book-kit`.

### Verified
- `claude plugin validate` (v2.1.283) passes in `--strict` mode for the plugin, its `skills/` and `agents/` directories, and the marketplace manifest.
- Script battery in a synthetic project: non-book-dir guard (all 5 scripts), init fresh/idempotent/merge/invalid-JSON/legacy/plugin-dir refusal, scan status → commit → changed/renamed/removed diff, office extraction from the project cwd and via `--root` with SHA cache hits, prune (rename-protected, removed extraction + stale office cache), validator PASS on a book built from the plugin templates, template resolution (plugin → project override → `--templates`), placeholder-leak detection, and the `coverage.brevity_reason` regression.

### Migrating a v9.8 project folder
Run `/book-kit:init` inside it (keeps `.book-state/`, `book/`, `book.config.json`; merges the new rules), then delete the now-duplicated `CLAUDE.md`, `.claude/agents/`, `.claude/commands/`, and `scripts/` (keep `templates/` only if you customized it — it becomes the project override). Continue with `/book-kit:update-book`.

## v9.8 (2026-09-13) — requirement v2-1 alignment (concise **but complete**)

No schema changes; drop-in replacement for v9.7 (`.book-state/` remains valid; config, templates, app.js, style.css, settings.json and all other scripts byte-identical). Requirement v2-1's only delta from v2 is req 2, which now appends "แต่ยังคงความครบถ้วนและความสมบูรณ์ของเนื้อหา" — conciseness must not cost completeness/integrity. v9.7 already qualified conciseness with "preserves full meaning"; v9.8 makes the priority order explicit and closes the paths where brevity could still erode coverage.

### Content — the tie-break is now explicit (completeness > brevity)
- CLAUDE.md rule 4 and chapter-writer rule 3 retitled **"Concise but complete"**: conciseness compresses *phrasing*, never removes *substance*; when the two conflict, completeness and integrity win. The ambiguity default for extra examples flips from cut to keep (CLAUDE.md rule 4, writer rule 1: "in doubt, keep the extra").
- Valid `omitted_justified` reasons are now constrained to **semantic** justifications (meaning fully represented elsewhere / administrative / out of teaching scope) in CLAUDE.md coverage accounting and the architect's Priorities rule; "for brevity/length/token saving" is never a valid omission reason, and the architect's doubt default is "represent it".

### Auditor — asymmetric severity, substance-safe fixes
- Check 2: a brevity-justified omission is a finding — `critical` if the unit's meaning is not fully represented elsewhere, otherwise `minor` (relabel with the true semantic reason); every `coverage.brevity_reason` validator warning must be examined.
- Checks 3 & 5: lost meaning always outranks wordiness in severity; wordiness alone is `minor` unless it genuinely obstructs understanding; any bloat/wordiness `suggested_fix` must compress phrasing only, never delete meaning. (The over-detail check itself is unchanged — trimming true duplicates and bloat remains in scope.)

### Validator (mechanical layer)
- New non-blocking heuristic warning `coverage.brevity_reason`: flags `omitted_justified` reasons that cite brevity/length/token-saving (EN + TH keyword regex, deliberately narrow — bare "token"/"short" do not match, so e.g. "tokenization out of scope" passes clean). Warnings feed the auditor exactly like `extraction.error`; PASS/FAIL semantics and exit codes are unchanged.

## v9.7 (2026-09-13) — requirement v2 alignment (concise content, colorful principled UI)

No schema changes; drop-in replacement for v9.6 (`.book-state/` remains valid). One new **optional** config key: `ui.accent2` (gradient partner; the stylesheet default applies when absent). Requirements 1, 3, 4, 6, 7, 8 are unchanged between requirement v1 → v2 and were already covered; the two deltas below are req 2 (+กระชับ) and req 5 (colorful + UI design principles).

### Content — req 2 (concise)
- Conciseness is now first-class and mechanical: CLAUDE.md content rule 4 and chapter-writer rule 3 define it (shortest phrasing preserving full meaning; short sentences/paragraphs ≈ ≤4 sentences; bullets for enumerable items; no filler or restatement). The auditor now flags wordiness as a `clarity` finding, complementing the existing over-detail check.

### UI — req 5 (colorful + design principles)
- `style.css` base theme redesigned: per-hue semantic callout palette (def indigo / note sky / warn amber / example green / summary violet) with tinted backgrounds; indigo→cyan gradient accents on the page progress bar, book progress fill, h2 ticks, and cover; tinted table headers + zebra rows; colored inline code; TOC current-item inset indicator; green read checkmarks; `:focus-visible` outlines; themed `::selection`; thin TOC scrollbar.
- Accessibility verified computationally: every text/background pair meets WCAG AA in **both** themes (46 pairs checked). This also fixes a real defect — the old dark-theme link color was `--accent` on the dark background at ~2.9:1, below AA; dark mode now uses a dedicated `--link` (indigo-300, ~9:1).
- `color-mix()` removed entirely (open nit: browser support) — replaced by explicit per-theme tint variables and rgba, so the theme renders identically on browsers without color-mix support.
- Supplement badge no longer overlaps first-line text in non-callout blocks (open nit): there it is a floated `::before` chip the text wraps around; inside callouts it stays absolutely positioned beside the type label.
- `book.config.json` gains `ui.accent2`; the builder syncs it into `--accent2` exactly like `accent`.
- CLAUDE.md's UI section now states the design-principle contract (hierarchy, AA contrast both themes, spacing scale, focus-visible, reduced-motion); the builder's restyle rules and the auditor's UI check both enforce it.
- All validator/app.js hooks preserved (`#toc`, `#progress`, `#theme-toggle`, `.toc-tree`, `.current`, `.read`, `.book-progress`, `.copy-btn`, callout classes, `var(--fg)/var(--accent)/var(--muted)` for SVG figures); templates and app.js unchanged.

## v9.6 (2026-08-27) — review fixes (placeholder false-positive, scan token cost)

No schema changes; drop-in replacement for v9.5. `.book-state/` remains valid. One check is deliberately narrower (below).

### Validator
- `book.placeholder` matched any `{{UPPERCASE}}` token, so learner content that legitimately teaches such syntax (e.g. a Mustache/Handlebars code sample containing `{{NAME}}`) hard-failed the build — and the builder could not repair it without altering content. The check now matches only the placeholder names actually present in `templates/*.html` (self-maintaining when templates gain new placeholders; falls back to the generic pattern if no templates are readable). Genuinely unfilled shell placeholders fail exactly as before.

### Token discipline
- `scan_sources.py` printed the sha of every source on every run — on large courses that dumped kilobytes of hashes into the orchestrator's context on each `/build-book` / `/update-book`. It now prints shas only for files that need (re)extraction (added / changed / rename targets); unchanged files live in the committed manifest. `source-analyst` doc updated to match.


## v9.5 (2026-08-27) — review fixes (rename path, config-driven lang, guards)

No schema changes; drop-in replacement for v9.4. `.book-state/` remains valid. One behavior change: `ui.lang` now validates against `book.config.json` → `book.language` (default "th") instead of a hardcoded "th" — identical outcome for unmodified configs.

### Command gaps
- **/build-book**: a rename since the last commit had no scripted handling — the CLAUDE.md remap rule applied only implicitly, so an orchestrator that missed it hit an unrepairable `extraction.missing` at validation. Preflight now remaps renames explicitly (same procedure as /update-book step 1) before pruning.
- **/update-book**: "nothing changed" is now defined as added/changed/removed/renamed all 0 — a rename alone no longer risks an early "up to date" exit before its remap and manifest commit.

### Validator
- `ui.lang` reads the expected language from `book.config.json` (`book.language`, default "th"); previously the config field existed but any non-"th" value guaranteed a failure. A missing/unreadable config now warns (`config.unreadable`) and falls back to defaults.
- The `#toc` scanner now tracks an open-tag stack with implied-close healing instead of a bare depth counter: previously one unclosed optional tag (e.g. `<li>` without `</li>`) desynced the counter and leaked the rest of the page's links into the TOC set, silently turning `toc.missing` into a vacuous pass on that page. Link scoping now stays correct even for such markup, and a non-blocking `toc.parse_desync` warning tells the builder to close every TOC tag.

### UI robustness & polish
- app.js: `matchMedia(...).addEventListener` guarded with an `addListener` fallback — on Safari ≤13 the unguarded call threw and killed everything after it (progress bar, TOC, read marks, copy buttons).
- chapter-writer: heading depth is capped at `<h6>` (ids with 5+ dots previously produced invalid `<h7>`+).
- style.css: empty cover subtitle/author no longer render as blank gaps (`:empty {display:none}`).

## v9.4 (2026-08-26) — dotless-TOC fix & diagnostics

No schema changes; `.book-state/` from v9.3 remains valid. One check is intentionally stricter (below), so a v9.3-built book re-validated under v9.4 may newly fail `toc.missing` until its TOC is regenerated.

### Functional bug (verified by tests)
- **Dotless chapters never showed read-marks / scrollspy highlight in the TOC**: the builder linked them as bare `ch-N.html`, but `app.js` keys the ✓ mark, `current` highlight, and state restore on hrefs ending in `#sec-*` — so the entry was counted in whole-book progress yet never marked read. Fixes: the builder now links a dotless chapter as `ch-N.html#sec-N`; `chapter-shell.html` gained a `{{H1_ATTR}}` placeholder so the section anchor is filled onto the `<h1>` (no post-edit hack); `validate_book.py` no longer accepts a bare chapter-page link for a dotless section — every section, dotless included, needs its `#sec-*` link (supersedes the v9.2 allowance).

### Diagnostics & extraction honesty
- `validate_book.py`: duplicate top-level chapter ids now fail with a dedicated `plan.chapter_dup` (previously failed only indirectly via `page_dup` / `page_missing` / `toc.missing`).
- `extract_office.py` (pptx): embedded charts are counted and flagged in the `[visual]` note alongside pictures (previously lost silently, with no gap flag).
- `sources/README.md`: documents that any file named `readme.md` under `sources/` is ignored by scan/validate/prune — rename such a source with a numeric prefix.

### Known limitation (accepted)
- "No agent writes to `sources/`" is enforced by the `Write`/`Edit` deny rules plus the CLAUDE.md policy; the allowed `Bash(python:*)` could technically bypass it. Command-level filtering would break legitimate reads (hashing, office extraction), so this stays a policy rule — keep originals backed up outside the kit if that residual risk matters.

## v9.3 (2026-08-26) — removal-path & gate-lifecycle fixes

No schema changes; drop-in replacement for v9.2. `.book-state/` remains valid.

### Functional bugs (verified by tests)
- **Removed sources bricked the pipeline**: deleting a source left its extraction behind, and `validate_book.py` demands coverage for every unit of every extraction on disk → guaranteed `coverage.gap` FAIL that no agent could repair (agents cannot delete files). New `scripts/prune_state.py` deletes stale extractions and stale office-cache entries (sha-protects pending renames; refuses to run on an empty `sources/`); `/build-book` and `/update-book` invoke it whenever the scan reports removals. `validate_book.py` now classifies stale extractions itself: `extraction.stale` warning, excluded from the coverage-gap sweep, and any coverage entry still referencing one fails as `coverage.stale_ref`.
- **`/apply-fixes` could dead-end**: after a recheck with `still_open` findings the report was set to `status: "applied"`, which the step-0 guard rejects — so typing `/apply-fixes` again (the natural reply to "run another batch?") refused. Recheck now returns the report to `pending_approval` unless everything is fixed; `"applied"` means fully resolved.

### Spec gaps
- **Chapters without subsections** now have a defined convention: exactly one dotless section (id == chapter id), anchored by the builder on the page `<h1>`; the writer emits no heading for it. Mixing a dotless section with dotted siblings is rejected (`plan.dotless_mix`).
- **`audit.max_source_spot_checks`** was dead config — the auditor hardcoded 10. The auditor and CLAUDE.md now read the limit from `book.config.json` (default 10).

### Polish
- style.css: `h6` styled, so depth-5 sections no longer fall back to browser defaults.
- app.js: no copy button on `<pre class="mermaid">` (mermaid replaces the content anyway).
- source-analyst: long PDFs are read in consecutive page ranges with continuous unit numbering.
- /update-book: clarified that a plain rename only needs the extraction's `source:` frontmatter updated (`covers` refs point at extraction paths).

## v9.2 (2026-08-26) — review fixes

No workflow or schema changes; drop-in replacement for v9.1. `.book-state/` remains valid.

- **validate_book.py**: the `toc.missing` check was vacuous — the chapter-page link present in every TOC satisfied all sections on that page, so a missing section link could never fail. Dotted subsections now require their own `#sec-*` link (same-page bare `#sec-*` still accepted; a dotless section id equal to its chapter id may be covered by the chapter link).
- **validate_book.py**: `walk_sources()` now ignores the same temp extensions as `scan_sources.py` (`.tmp`, `.part`, `.crdownload`) — a stray download temp file in `sources/` no longer causes a false `extraction.missing` failure.
- **app.js**: copying from a bare `<pre>` (no inner `<code>`) included the copy button's own label in the copied text; the button is now stripped from a clone before reading.

## v9.1 (2026-08-26) — code-review fixes

No workflow or schema changes; drop-in replacement for v9.0. `.book-state/` from v9.0 remains valid.

### Functional bugs (verified by tests)
- **app.js**: whole-book read progress was never persisted — `Array.prototype.slice.call(Set)` always returns `[]`; now `Array.from(readSet)`. (major)
- **validate_book.py**: void elements (e.g. `<input id="toc-filter">`) desynced the `#toc` depth counter, leaking non-TOC links into `toc_hrefs` and weakening the `toc.missing` check. Fixed via a void-tag set; TOC completeness is now checked on every book page, not only `index.html`.
- **validate_book.py**: the link check mutated `scans` while iterating it → `RuntimeError` whenever a page linked `#frag` into an existing non-plan page. Now iterates a snapshot.

### Pipeline gaps
- **Unreadable sources**: a `units: 0` extraction previously passed validation silently (contradicting "never silently skip"), while a manual `unresolved` entry double-failed. Now: `validate_book.py` emits a non-blocking `extraction.error` warning; the auditor must raise a finding (default `critical`) for each. `CLAUDE.md` failure handling updated to match.
- **extract_office.py (pptx)**: recurses into grouped shapes — text inside groups was silently lost. The picture note now states honestly that PPTX images are not extractable and tells the analyst to flag a gap; `sources/README.md` advises exporting image-heavy decks to PDF.
- **extract_office.py (docx)**: paragraphs and tables are emitted in document order (tables were previously appended at the end, losing their position).
- **/update-book**: a same-SHA rename that changes the chapter folder / numeric prefix now marks both chapters affected and is handed to the architect (still zero re-reads).
- **validate_book.py**: `merged` coverage entries now validate their `into` target; any unfilled `{{PLACEHOLDER}}` left in built pages is a hard failure.

### Spec / UI polish
- **book-builder**: applies `ui.accent` from `book.config.json`; exact `HEAD_EXTRA` snippets for KaTeX (incl. auto-render init — required for `\( \)` to render) and Mermaid; new `{{BOOK_SLUG}}` placeholder in both shells; twisty button gets an `aria-label`.
- **Templates**: theme pre-paint script reads the slug-scoped key (no cross-book theme bleed on shared origins); `#progress` gains `aria-valuemin/max` and a live `aria-valuenow`.
- **chapter-writer**: `<pre class="mermaid">` allowed for flow/graph figures when `mermaid_cdn` is true.
- **CLAUDE.md**: explicit rule — no agent writes to `sources/` by any means, including Bash.
