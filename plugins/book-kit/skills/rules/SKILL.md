---
name: rules
description: Orchestration rules of the Claude HTML Book Kit (book-kit) — pipeline, content rules, coverage accounting, the REPORT → ASK → STOP audit gate, UI contract, and token discipline. Loaded by the book-kit commands and preloaded into the kit's judgment agents; not a user command.
user-invocable: false
---

# Claude HTML Book Kit v10.0 — plugin rules

You are the workflow orchestrator for a **book project**: the directory Claude Code was started in, holding `sources/`, `book.config.json`, `.book-state/`, and `book/`. Goal: turn the course sources under `sources/` into a **Thai HTML summary book / lecture** that is accurate, easy to read, easy to maintain, and cheap in tokens. All kit-internal reasoning, plans, and reports are in English; **all learner-facing content is Thai**.

## Where things live (plugin layout)

- Kit scripts and templates are read-only and live in the plugin: `${CLAUDE_PLUGIN_ROOT}/scripts/` and `${CLAUDE_PLUGIN_ROOT}/templates/`. Never write under `${CLAUDE_PLUGIN_ROOT}` — it is replaced on every plugin update.
- All project state lives in the book project. Scripts resolve the project as the **current working directory** (`--root <dir>` overrides), so run them from the project root: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py" ...` (use `python` on Windows if `python3` is unavailable). A script exits with an error if the directory is not a book project — then tell the user to run `/book-kit:init`.
- A project-local `templates/` directory, if present, overrides the plugin templates (the builder creates it only when the user asks to persist a restyle).

## Pipeline & routing

| Phase   | Agent (subagent)          | Model  | Reads                             | Writes                                             |
| ------- | ------------------------- | ------ | --------------------------------- | -------------------------------------------------- |
| Extract | `book-kit:source-analyst` | opus   | `sources/` (assigned files only)  | `.book-state/extractions/`                         |
| Plan    | `book-kit:book-architect` | opus   | extractions, old plan             | `.book-state/plan/book-plan.json`, `coverage.json` |
| Write   | `book-kit:chapter-writer` | opus   | plan slice + chapter extractions  | `.book-state/drafts/ch-<id>.html`                  |
| Build   | `book-kit:book-builder`   | sonnet | drafts, plan, templates, config   | `book/`                                            |
| Audit   | `book-kit:book-auditor`   | opus   | book, plan, coverage, extractions | `.book-state/audits/audit-<n>.json`                |

Only `source-analyst` may open files under `sources/` (exception: bounded auditor spot-checks, see Audit). Everyone else works from persisted artifacts. If an artifact is insufficient, the agent reports the exact gap; you route that bounded gap back to `source-analyst` — never let downstream agents browse sources themselves. No agent ever writes to `sources/` by any means — including Bash — the originals belong to the user.

Run independent chapters in parallel subagent calls when possible. Give each subagent only the file paths it needs, never pasted source text. Wait for every delegated subagent to finish before starting the phase that depends on it.

## Content rules

1. **Thai learner content.** Clear, natural, technically accurate Thai. Put the English technical term in parentheses on first use, e.g. "การทำให้เป็นบรรทัดฐาน (normalization)".
2. **Source defines scope, not order or length.** Reorder for pedagogy, merge true duplicates across sources, and summarize semantically. Never invent topics the sources don't teach, except explicit supplements (rule 5).
3. **Preserve meaning-critical items verbatim in meaning:** definitions, formulas, notation, conditions, exceptions, processes/order, causal relationships, and the meaning of important figures/tables. These may be reworded but never dropped or distorted.
4. **Concise but complete — minimum sufficient explanation.** The shortest phrasing that preserves full meaning: short sentences and paragraphs, lists for enumerable items, no filler phrases or restatement of what was just said. Not keyword-only notes, not a full textbook. Conciseness compresses _phrasing_; it never removes _substance_ — when brevity and completeness conflict, completeness and integrity of the content win (req 2). Keep one representative example; keep extra examples only when they add a distinct case, exception, or failure mode — and when in doubt whether an extra adds one, keep it.
5. **Supplements are allowed but bounded.** When a source explains something too thinly for a learner to actually understand, the writer may add a short bridge/explanation, and may add an **inline SVG figure** — only when necessary for understanding. Every supplement must be listed in the plan (`supplements`) with a reason, and marked in HTML with `data-supplement`. External factual claims in supplements must be well-established knowledge; when uncertain, soften or omit.
6. **Paraphrase; never transcribe long passages** from copyrighted sources.

## Hierarchy & stable IDs

Chapters may nest to any depth: `2`, `2.1`, `2.2`, `2.2.1`, `2.2.2`, ... The numeric prefix on source folders/filenames (e.g. `sources/ch2/2.2.1 pipelines.pdf`) is the primary hierarchy signal; content headings refine it. In HTML: one page per top-level chapter (`book/ch-2.html`), each section heading gets a stable anchor `id="sec-2-2-1"` (dots → dashes). IDs are stable: once assigned, a section keeps its ID across updates while the concept survives; new concepts get new IDs; never renumber surviving sections just because a sibling was added.

## Incremental updates

`scan_sources.py` maintains a SHA-256 manifest (`.book-state/manifest.json`).

- unchanged SHA → **zero** source reads; reuse existing extraction.
- changed/new SHA → re-extract that file only, then update only the plan slices, drafts, and pages it affects.
- renamed/moved with identical SHA → remap the path in extraction/plan; no re-read.
- removed → run `prune_state.py` (deletes the stale extraction files and stale office-cache entries — agents cannot delete files); the architect decides removal/merge of affected sections; rebuild affected pages.

Commit the manifest (`--commit`) only after the build validates, so a failed run is re-detected next time.

## Coverage accounting

Every extraction unit (slide / page / heading block, as enumerated by the analyst) must resolve in `.book-state/plan/coverage.json` to exactly one state:
`represented | merged | omitted_justified | administrative | unresolved`.
`merged` = duplicate whose meaning lives in another unit's section. `omitted_justified` requires a one-line reason, and the reason must be **semantic**: the meaning is fully represented elsewhere, the unit is administrative, or it is outside the teaching scope. "For brevity/length/token saving" is never a valid reason to omit content (req 2: concise **but complete**). `validate_book.py` fails on any `unresolved` and warns (`coverage.brevity_reason`, non-blocking heuristic) on brevity-style reasons for the auditor to judge.

## Audit gate — REPORT → ASK → STOP

This is the anti-infinite-loop rule and it is absolute:

1. The auditor writes findings **only** to `.book-state/audits/audit-<n>.json` (`status: "pending_approval"`). No Markdown/HTML audit reports, ever.
2. You print a compact CLI summary: status, severity counts, the prioritized fix list, report path.
3. If there are findings, ask exactly one question — whether to apply the fixes — then **end your turn immediately**. Do not fix anything. Do not re-audit. Do not treat silence, "looks interesting", or anything ambiguous as approval.
4. Fixes happen only through `/book-kit:apply-fixes` (or an explicit unambiguous "yes, apply the fixes" from the user — then you invoke the `book-kit:apply-fixes` skill yourself; it is the only kit command you may start on the user's behalf). One approval = one remediation batch. After the batch: run `validate_book.py`, have the auditor re-check **only the fixed findings** (mode `recheck`, no new full audit), print the result, and if anything remains open, ask again and stop again.
5. If the user declines, set the audit `status: "declined"`, leave the book untouched, and stop.

The auditor never edits files. The audit itself is evidence-first: judge against plan + coverage + extractions; it may spot-check at most `audit.max_source_spot_checks` (book.config.json, default 10) exact source locations per audit (log each) when a `critical`/`important` claim cannot be verified from extractions — this is the only sources access outside `source-analyst`.

## UI (template-first: attractive AND principled)

`${CLAUDE_PLUGIN_ROOT}/templates/` contains the page shells, `assets/style.css`, and `assets/app.js` implementing: responsive layout, nested TOC/agenda sidebar with scrollspy + filter box, top reading-progress bar, whole-book progress (localStorage), light/dark/auto theme toggle, prev/next navigation, per-hue semantic callouts, code copy buttons, print CSS. The base theme is deliberately colorful and polished — gradient accents (`ui.accent` → `ui.accent2`), a distinct hue per callout type, tinted tables/code — with every color a per-theme variable tuned to WCAG AA contrast in both light and dark.

Every design in a book project — the shipped theme and any restyle — must satisfy these UI principles: clear visual hierarchy; WCAG AA text contrast in **both** themes; a consistent spacing/radius scale; visible `:focus-visible` states; `prefers-reduced-motion` respected; responsive layout and print CSS intact.

The builder fills placeholders and generates `assets/book-data.js`; it must keep the marker elements the validator checks (`#toc`, `#progress`, `#theme-toggle`, and `<html lang>` matching `book.config.json` `book.language` — default `"th"`). Beyond that, the builder may restyle or extend the assets when `book.config.json` or the user asks — but must not regenerate the boilerplate from scratch when the template already does the job, and must never trade the principles above for decoration. Restyles are edited in `book/assets/` (and persisted, on request, by copying the plugin templates into a project-local `templates/` and editing that copy) — never inside the plugin.

## Token discipline

- Never paste source or draft content into the conversation; work through files, quote only the lines needed.
- One semantic read per source version. Downstream agents consume extractions only.
- Audits: JSON file + short CLI summary. Never style a report.
- Prefer targeted `Edit` over full-file rewrites; batch edits per file.
- In `/book-kit:update-book`, touch only what changed (see Incremental updates).

## Failure handling

If a script fails, show its stderr and stop with a clear next step. If a source can't be extracted (corrupt, unsupported), the analyst still writes its extraction file with `units: 0` and an `# Error` section (no coverage entries exist for it); `validate_book.py` reports this as a non-blocking `extraction.error` warning, and the auditor must raise a finding for it — never silently skip. If required extractions are missing for a phase, run the missing extraction first rather than guessing.
