---
name: content
description: Content contract of the Claude HTML Book Kit (book-kit) — summary levels, content rules, hierarchy and ids, how coverage is accounted. Preloaded into the kit's judgment agents (architect, writer, auditor); not a user command.
user-invocable: false
---

# Book-kit content contract

The book is a summary of the lesson sources under `sources/`: complete, accurate, easy to picture. Kit-internal files are English; learner-facing content is written in `book.language` (default `th` — Thai).

Three rules outrank everything below:

1. **Completeness and accuracy outrank brevity** at every summary level. Length, tokens and the level are never reasons to drop content.
2. **`sources/` belongs to the user.** Only the source-analyst reads it (plus the auditor's bounded spot-checks). Everyone else works from the persisted artifacts and, when one is insufficient, reports the exact gap — never guesses, never opens a source.
3. **Never write `book/`.** The build script generates it from the drafts.

## Summary levels (`content.level`)

**The level changes the density of the explanation — never the coverage.** Plan, section ids, supplements and the units each section covers are identical at every level, and every covered unit keeps all its meaning-critical items (content rule 3).

| | Level 1 — review (ทบทวนก่อนสอบ) | Level 2 — study (เรียบเรียงใหม่; default) |
|---|---|---|
| Reader | has studied the material; needs fast, reliable recall of everything examinable | is learning it; must understand from this text alone |
| Form | fact cards: tables, term lists, formula/definition callouts, numbered steps; prose only to orient (paragraphs ≤ 2 sentences) | explanatory prose with lists and callouts, reorganised for teaching, no redundancy |
| Explanation | the one line that makes a fact stick; no build-up | intuition → definition/formula → example |
| Examples | one minimal instance per distinct case, in 1–2 lines | one representative worked example; extras only for a distinct case, exception or failure mode (in doubt, keep) |
| Derivations | result + conditions + the key idea in one line — but every step of a unit flagged `procedure` | step by step where the source teaches them |
| Chapter end | `summary` callout, then `recall` questions when `content.recall_questions` | `summary` callout |

Each level has its own draft store (`.book-state/drafts/L1/`, `L2/`), so both can exist side by side and switching back costs nothing.

## Content rules

1. **Language.** Clear, natural, technically accurate prose in `book.language`. On first use give the original technical term in parentheses, e.g. "การทำให้เป็นบรรทัดฐาน (normalization)". One name per concept in the whole book. `content.audience` and `content.style_notes` set the tone — they never override these rules.
2. **Source defines scope, not order or length.** Reorder for teaching, merge true duplicates across sources, summarise semantically. Never add topics the sources do not teach, except planned supplements (rule 6).
3. **Meaning-critical items always survive**, at every level: definitions, formulas and notation with what each symbol means, conditions, exceptions, process steps and their order, causal relationships, key numbers, and the meaning of important figures/tables. Reword freely; never drop or distort. Three of these are checked mechanically in every chapter:
   - each `keys` term the analyst recorded for a covered unit appears in the chapter;
   - each formula callout has a where-line (`<p class="where">`) saying what its new symbols mean and when it holds;
   - each unit flagged `procedure` keeps its steps as a numbered list.
4. **Concise but complete.** The shortest phrasing that keeps full meaning: short sentences, lists for enumerable items, no filler, no restating. Conciseness compresses *phrasing*, never *substance*.
5. **Easy to picture (เห็นภาพ).** Concrete before abstract: anchor each non-trivial idea in the source's own example, number, figure or scenario; spell cause → effect out as explicit steps; turn comparisons into tables and processes into numbered steps; prefer specific quantities and names over vague words; one idea per sentence with an explicit subject. Redraw the meaning of important source figures as inline SVG.
6. **Supplements are allowed but bounded.** Anything not traceable to a covered unit — an added explanation, example, analogy or figure — is a supplement: requested in the plan (`supplements`, with type and reason) only where a gap genuinely blocks understanding, rendered at every level, wrapped in `data-supplement="<id>"`, and limited to well-established knowledge (soften or omit when unsure). Restructuring covered content (tables, lists, lead, summary, recall questions, where-lines) is not a supplement.
7. **Paraphrase; never transcribe long passages** from the sources.
8. **References are links.** Point to another section or chapter only with a link whose text is the number — `<a href="ch-3.html#sec-3-2">3.2</a>` (same page: `href="#sec-3-2"`). A number in plain prose cannot follow a renumbering.

## Hierarchy and ids

Chapters nest to any depth: `2`, `2.1`, `2.2.1`, … The numeric prefix of source folders/filenames is the primary hierarchy signal; content headings refine it. One page per top-level chapter (`book/ch-2.html`); each section heading carries the anchor `id="sec-2-2-1"` (dots → dashes). The id is also the number the reader sees.

A section keeps its id while its concept survives; a new concept gets the next free number under its parent. **Nobody renumbers by hand** — not in the plan, not in a draft. When numbers must move (the user renumbered source chapters, or a new section belongs between two old ones), the change is listed as `old=new` pairs and a script rewrites plan, drafts, anchors, links and the readers' stored progress in one step.

## Coverage accounting

An extraction lists every unit of its source (`## U1`, `## U2`, …). **The plan is the only place that says what happens to a unit**, and every unit is in exactly one place:

- a section's `covers` — the section teaches it;
- a section's `merged` — a true duplicate whose meaning this section already carries;
- the plan's `omitted` list — left out, with a state (`omitted_justified` or `administrative`) and, for `omitted_justified`, a one-line **semantic** reason: its meaning is fully present elsewhere, or it is outside the teaching scope. Brevity, length, tokens and the summary level are never valid reasons.

A unit in no list is a gap and blocks validation; so does a unit in two lists. The plan accounting for a unit is not the unit being in the book: a section that covers units must hold them under its own heading (a bare heading blocks; very little text for many units is put before the auditor). `plan/coverage.json` and `plan/slices/ch-<id>.json` are generated from the plan by script — no agent writes them.
