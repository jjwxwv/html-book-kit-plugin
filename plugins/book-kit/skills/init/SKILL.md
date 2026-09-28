---
name: init
description: Set up the current directory as a Claude HTML Book Kit project — creates sources/, .book-state/, book/, book.config.json, the permission rules the kit needs, and a minimal CLAUDE.md. Idempotent; never overwrites existing files.
disable-model-invocation: true
argument-hint: "[book title]"
allowed-tools: Bash(python3 *) Bash(python *)
---

Initialize a book project in the current working directory (run from the folder that should hold the book).

Book title given by the user (may be empty): $ARGUMENTS

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init_project.py"` — append `--title "<title>"` when a title was given. Use `python` instead of `python3` only if `python3` is unavailable. The script prints a JSON summary of what it created, what it kept, which permission rules it merged into `.claude/settings.json`, and any legacy kit files it detected.
2. If the script reports an error, show it and stop.
3. Otherwise, summarize in a few lines (Thai if the user writes Thai):
   - which files/folders were created vs kept;
   - if `legacyKitFilesDetected` is non-empty: this looks like a v9.x project-folder kit — `.book-state/` and `book.config.json` stay valid, but the old `CLAUDE.md`, `.claude/agents/`, `.claude/commands/`, and `scripts/` duplicate what the plugin now provides and should be removed (a project `templates/` may be kept as a design override); list the paths it found;
   - if `writeRulesIgnored` is non-empty: those `Write(...)` path rules in `.claude/settings.json` are not consulted by Claude Code (only `Edit(...)`/`Read(...)` path rules are) and can be deleted;
   - next steps: put sources in `sources/` following `sources/README.md` (numeric prefixes = chapter structure), set the title in `book.config.json` if not done, `pip install python-pptx python-docx` if there are `.pptx`/`.docx` sources, then run `/book-kit:build-book`. Mention that the merged permission rules apply from the next session (or after the workspace-trust prompt) — if Claude Code asks for permission during the first build, approving is expected.
Do not create sources or edit `book.config.json` beyond the title; do not run the build.
