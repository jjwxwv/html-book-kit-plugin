#!/usr/bin/env python3
"""Scaffold a Claude HTML Book Kit project in the current directory (plugin edition).

Idempotent and non-destructive: existing files are never overwritten. Creates
what is missing, merges the permission rules the kit needs into
.claude/settings.json (adds only rules that are absent; other keys untouched),
writes a minimal CLAUDE.md when none exists, and reports legacy v9.x kit files
(project-folder form) that the plugin now supersedes.

Usage (run from the folder that should hold the book, or pass --root <dir>):
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init_project.py" [--title "ชื่อหนังสือ"]

Prints a JSON summary. Exit 0 on success, 2 on a hard error (e.g. an existing
.claude/settings.json that is not valid JSON — it is left untouched).
"""
import argparse
import json
import os
import shutil
import sys

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAFFOLD = os.path.join(PLUGIN_ROOT, "scaffold")
PLACEHOLDER_TITLE = "ตั้งชื่อหนังสือที่นี่"

# Permission rules the pipeline relies on. Path rules use Edit(...) — Claude Code
# consults only Edit/Read path rules (Write(path) rules are accepted but never
# checked, and warn at startup); Edit rules cover the Write tool as well.
ALLOW_RULES = [
    "Bash(python3 *)",
    "Bash(python *)",
    "Bash(pip install *)",
    "Bash(pip3 install *)",
    "Edit(book/**)",
    "Edit(.book-state/**)",
    "Edit(templates/**)",
    "Edit(book.config.json)",
]
DENY_RULES = [
    "Edit(sources/**)",
]

CLAUDE_MD = """# Book project — Claude HTML Book Kit (book-kit plugin)

Sources live in `sources/` (numeric prefixes = chapter structure), the built book in `book/`, working state in `.book-state/`. **Never modify anything under `sources/`** — the originals belong to the user.

Kit commands (user-invoked): `/book-kit:build-book` · `/book-kit:update-book` · `/book-kit:audit-book` · `/book-kit:apply-fixes` · `/book-kit:init`.
When asked in plain language to build, update, or audit the book, point the user to the matching command instead of improvising the pipeline. Audit fixes are applied only through `/book-kit:apply-fixes` or after an explicit, unambiguous approval — never on your own initiative.
"""

DIRS = [
    "sources",
    "book",
    ".book-state",
    ".book-state/extractions",
    ".book-state/plan",
    ".book-state/drafts",
    ".book-state/audits",
    ".claude",
]
GITKEEP_DIRS = ["book", ".book-state/extractions", ".book-state/plan",
                ".book-state/drafts", ".book-state/audits"]
SCAFFOLD_FILES = {  # project-relative path -> scaffold-relative path
    "book.config.json": "book.config.json",
    "sources/README.md": "sources/README.md",
    ".book-state/README.md": ".book-state/README.md",
}
LEGACY_MARKERS = [
    "CLAUDE.md::Claude HTML Book Kit v9",
    ".claude/commands/build-book.md",
    ".claude/commands/update-book.md",
    ".claude/commands/audit-book.md",
    ".claude/commands/apply-fixes.md",
    ".claude/agents/source-analyst.md",
    ".claude/agents/book-architect.md",
    ".claude/agents/chapter-writer.md",
    ".claude/agents/book-builder.md",
    ".claude/agents/book-auditor.md",
    "scripts/scan_sources.py",
    "scripts/extract_office.py",
    "scripts/prune_state.py",
    "scripts/validate_book.py",
]


def detect_legacy(root: str) -> list:
    found = []
    for marker in LEGACY_MARKERS:
        if "::" in marker:
            rel, needle = marker.split("::", 1)
            full = os.path.join(root, rel)
            try:
                with open(full, "r", encoding="utf-8") as f:
                    if needle in f.read(2000):
                        found.append(rel)
            except OSError:
                pass
        elif os.path.isfile(os.path.join(root, marker)):
            found.append(marker)
    return found


def merge_settings(path: str, out: dict) -> None:
    data = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            out["error"] = f"{os.path.relpath(path)} is not valid JSON ({e}); left untouched — fix it, then rerun"
            return
        if not isinstance(data, dict):
            out["error"] = f"{os.path.relpath(path)} must contain a JSON object; left untouched"
            return
    perms = data.setdefault("permissions", {})
    if not isinstance(perms, dict):
        out["error"] = f"{os.path.relpath(path)}: 'permissions' must be an object; left untouched"
        return
    added = []
    for key, rules in (("allow", ALLOW_RULES), ("deny", DENY_RULES)):
        lst = perms.setdefault(key, [])
        if not isinstance(lst, list):
            out["error"] = f"{os.path.relpath(path)}: permissions.{key} must be a list; left untouched"
            return
        for rule in rules:
            if rule not in lst:
                lst.append(rule)
                added.append(f"{key}: {rule}")
    out["settingsRulesAdded"] = added
    out["writeRulesIgnored"] = sorted(
        r for key in ("allow", "deny", "ask") for r in perms.get(key, [])
        if isinstance(r, str) and r.startswith("Write(") and r != "Write")
    existed = os.path.isfile(path)
    if added or not existed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        (out["kept"] if existed else out["created"]).append(os.path.relpath(path, out["root"]))
        if existed:
            out["settingsMerged"] = True
    else:
        out["kept"].append(os.path.relpath(path, out["root"]))


def set_title(config_path: str, title: str, out: dict) -> None:
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        out["titleKept"] = f"book.config.json unreadable ({e}); title not set"
        return
    book = cfg.setdefault("book", {})
    current = (book.get("title") or "").strip()
    if current and current != PLACEHOLDER_TITLE and "book.config.json" not in out["created"]:
        out["titleKept"] = current
        return
    book["title"] = title
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
    out["titleSet"] = title


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="project root (default: current directory or $BOOK_ROOT)")
    ap.add_argument("--title", help="book title to write into book.config.json (only if unset/placeholder)")
    args = ap.parse_args()
    root = os.path.abspath(args.root or os.environ.get("BOOK_ROOT") or os.getcwd())
    out = {"root": root, "created": [], "kept": []}

    if root == os.path.abspath(PLUGIN_ROOT) or root.startswith(os.path.abspath(PLUGIN_ROOT) + os.sep):
        out["error"] = "refusing to scaffold inside the plugin directory — cd to your book folder first"
        print(json.dumps(out, indent=2, ensure_ascii=False), file=sys.stderr)
        return 2

    for d in DIRS:
        full = os.path.join(root, d)
        if os.path.isdir(full):
            continue
        os.makedirs(full, exist_ok=True)
        out["created"].append(d + "/")
    for d in GITKEEP_DIRS:
        keep = os.path.join(root, d, ".gitkeep")
        if not os.path.exists(keep) and not os.listdir(os.path.join(root, d)):
            open(keep, "a").close()

    for rel, src_rel in SCAFFOLD_FILES.items():
        dst = os.path.join(root, rel)
        if os.path.exists(dst):
            out["kept"].append(rel)
            continue
        src = os.path.join(SCAFFOLD, src_rel)
        if not os.path.isfile(src):
            out.setdefault("warnings", []).append(f"scaffold file missing in plugin: {src_rel}")
            continue
        shutil.copyfile(src, dst)
        out["created"].append(rel)

    if args.title:
        set_title(os.path.join(root, "book.config.json"), args.title.strip(), out)

    claude_md = os.path.join(root, "CLAUDE.md")
    if os.path.isfile(claude_md):
        out["kept"].append("CLAUDE.md")
        with open(claude_md, "r", encoding="utf-8") as f:
            if "book-kit" not in f.read():
                out["claudeMdHint"] = ("CLAUDE.md exists and does not mention book-kit — consider adding "
                                       "the kit snippet (see plugin README) so plain-language requests are "
                                       "routed to the /book-kit commands")
    else:
        with open(claude_md, "w", encoding="utf-8") as f:
            f.write(CLAUDE_MD)
        out["created"].append("CLAUDE.md")

    merge_settings(os.path.join(root, ".claude", "settings.json"), out)
    if "error" in out:
        print(json.dumps(out, indent=2, ensure_ascii=False), file=sys.stderr)
        return 2

    legacy = detect_legacy(root)
    if legacy:
        out["legacyKitFilesDetected"] = legacy
    out["next"] = ("put sources in sources/ (see sources/README.md), set the title in book.config.json, "
                   "pip install python-pptx python-docx if you have .pptx/.docx, then run /book-kit:build-book")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
