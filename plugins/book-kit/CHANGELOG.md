# Changelog

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
