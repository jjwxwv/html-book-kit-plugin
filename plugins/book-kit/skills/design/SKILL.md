---
name: design
description: Change how the book looks — choose a colour palette, define a custom palette, or request a restyle — then rebuild. Content is never rewritten, so this costs almost no tokens.
disable-model-invocation: true
argument-hint: "[palette name | what you want to look different]"
allowed-tools: Bash(python3 *) Bash(python *) Skill(book-kit:rules)
---

Change the book's appearance. Nothing here touches sources, extractions, the plan or drafts, and no audit follows — the content does not change. Run every script from the project root as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py" ...`.

Request (may be empty): $ARGUMENTS

0. If `book.config.json` is missing here, tell the user to run `/book-kit:init` and stop.
1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/make_palette.py" --list` — it prints the palettes available to this project (built-ins, plus `custom` when `ui.custom_palette` is set) and the current default.
2. Decide from the request:
   - **empty** → show the palette names with their labels, say which one is the default, mention that readers can also switch palettes any time in the book's "Aa" menu (their choice is stored in the browser), ask which palette to make the default or what should look different, and stop.
   - **exactly one of the listed palette names** → set `ui.palette` to it in `book.config.json` (a targeted edit; keep every other key).
   - **anything else** (a colour, a mood, "warmer", "less colourful", a brand colour, a structural change) → delegate `book-kit:book-builder` with the request verbatim. It edits `ui.palette` / `ui.custom_palette` — or, only for an explicitly requested structural restyle, a project-local `templates/` copy — and checks contrast.
3. Run `make_palette.py --check` (must print PASS), `build_book.py`, then `validate_book.py`. If the book was never built (no plan, or no drafts at the configured level yet), skip the build and say the palette applies on the next `/book-kit:build-book`. A validation failure that is not about `ui.*`, `templates.*` or `toc.*` was there before the design change: name its codes and point to `/book-kit:update-book` instead of repairing it here.
4. Report in a few lines: the default palette now in effect, the contrast check result, any `ui.contrast` or `config.palette` warning, and where to look (`book/index.html`).
