---
name: init
description: Set up the current directory as a Claude HTML Book Kit project — creates sources/, .book-state/, book/, book.config.json, the permission rules the kit needs, and a minimal CLAUDE.md. Idempotent; never overwrites existing files.
disable-model-invocation: true
argument-hint: "[book title]"
allowed-tools: Bash(python3 *) Bash(python *)
---

Initialize a book project in the current working directory (run from the folder that should hold the book).

Book title given by the user (may be empty): $ARGUMENTS

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init_project.py"` — append `--title "<title>"` when a title was given. Use `python` instead of `python3` only if `python3` is unavailable. The script prints a JSON summary of what it created, what it kept, which permission rules it added to or removed from `.claude/settings.json`, and any legacy kit files it detected.
2. If the script reports an error, show it and stop.
3. Otherwise summarise in a few lines (Thai if the user writes Thai):
   - which files/folders were created vs kept;
   - the permission rules: Python scripts may run without a prompt; the edit tools are **denied** on `sources/` (the originals are the user's) and on `book/` (only the build script writes it). If `settingsRulesRemoved` is non-empty, say that an older allow rule for `book/` was removed for that reason;
   - if `legacyKitFilesDetected` is non-empty: this looks like a v9.x project-folder kit — `.book-state/` and `book.config.json` stay valid, but the old `CLAUDE.md`, `.claude/agents/`, `.claude/commands/` and `scripts/` duplicate what the plugin provides and should be removed; list the paths it found;
   - if `legacyTemplates` is present: the project's `templates/` is a design override made for an older kit; the build cannot use it — it must be renamed or deleted (the user decides), after which `/book-kit:design` offers palettes and restyling;
   - if `writeRulesIgnored` is non-empty: those `Write(...)` path rules in `.claude/settings.json` are not consulted by Claude Code (only `Edit(...)`/`Read(...)` path rules are) and can be deleted;
   - next steps: put sources in `sources/` following `sources/README.md` (numeric prefixes = chapter structure); in `book.config.json` check the title and choose `content.level` (1 = exam-review summary, 2 = re-composed study summary; default 2); then run `/book-kit:build-book`. Nothing has to be installed; `pip install pypdf` is only worth it when a scan reports that a PDF's page count is unknown. For an existing v10 or v11.0 project: run `/book-kit:update-book` — drafts move into the per-level store, office sources are pre-extracted again and only those that had lost content are read again. Mention that the permission rules apply from the next session (or after the workspace-trust prompt) — if Claude Code asks for permission during the first build, approving is expected.

Do not create sources or edit `book.config.json` beyond the title; do not run the build.
