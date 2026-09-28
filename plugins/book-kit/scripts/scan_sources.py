#!/usr/bin/env python3
"""Scan sources/ into a SHA-256 manifest and diff against the committed one.

Usage (run from the book project root; the project is the current directory,
or pass --root <dir>):
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan_sources.py" --status   # diff vs committed manifest (no write)
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan_sources.py" --commit   # write .book-state/manifest.json

Diff categories: added, changed, removed, renamed (same SHA, new path), unchanged.
Prints a JSON summary to stdout; shas are listed only for files that need
(re)extraction (added / changed / rename targets) — unchanged files are in
the committed manifest. Exit 0 always (informational).
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

# Project resolution (plugin edition): the book project is the current working
# directory (Claude Code runs Bash in the project), overridable with --root or
# BOOK_ROOT. The script itself lives in the plugin, so __file__ is never the
# project. Module globals are assigned by configure() before any work.
ROOT = SRC = MANIFEST = None


def resolve_root(explicit=None) -> str:
    return os.path.abspath(explicit or os.environ.get("BOOK_ROOT") or os.getcwd())


def configure(root: str) -> None:
    global ROOT, SRC, MANIFEST
    ROOT = root
    SRC = os.path.join(ROOT, "sources")
    MANIFEST = os.path.join(ROOT, ".book-state", "manifest.json")


def require_book_project(root: str) -> None:
    """Exit 2 unless root looks like a book project (protects against running
    in the wrong directory, e.g. after a stray `cd`)."""
    if os.path.isfile(os.path.join(root, "book.config.json")) or os.path.isdir(os.path.join(root, "sources")):
        return
    print(json.dumps({"error": "not a book project",
                      "root": root,
                      "hint": "run from the project root (needs book.config.json or sources/), "
                              "pass --root <dir>, or run /book-kit:init to create one"},
                     ensure_ascii=False), file=sys.stderr)
    sys.exit(2)
IGNORE_NAMES = {".gitkeep", ".DS_Store", "Thumbs.db"}
IGNORE_EXT = {".tmp", ".part", ".crdownload"}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan() -> dict:
    files = {}
    if not os.path.isdir(SRC):
        return files
    for dirpath, dirnames, filenames in os.walk(SRC):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in sorted(filenames):
            if name in IGNORE_NAMES or name.startswith(".") or name.lower() == "readme.md":
                continue
            if os.path.splitext(name)[1].lower() in IGNORE_EXT:
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
            st = os.stat(full)
            files[rel] = {"sha256": sha256(full), "size": st.st_size}
    return files


def load_manifest() -> dict:
    if os.path.isfile(MANIFEST):
        try:
            with open(MANIFEST, "r", encoding="utf-8") as f:
                return json.load(f).get("files", {})
        except (json.JSONDecodeError, OSError) as e:
            print(f"warning: could not read manifest ({e}); treating all as new", file=sys.stderr)
    return {}


def diff(old: dict, new: dict) -> dict:
    added, changed, removed, renamed, unchanged = [], [], [], [], []
    old_by_sha = {}
    for p, meta in old.items():
        old_by_sha.setdefault(meta["sha256"], []).append(p)
    consumed_old = set()
    for p, meta in sorted(new.items()):
        if p in old:
            consumed_old.add(p)
            if old[p]["sha256"] == meta["sha256"]:
                unchanged.append(p)
            else:
                changed.append(p)
        else:
            candidates = [q for q in old_by_sha.get(meta["sha256"], [])
                          if q not in new and q not in consumed_old]
            if candidates:
                src = candidates[0]
                consumed_old.add(src)
                renamed.append({"from": src, "to": p})
            else:
                added.append(p)
    removed = sorted(p for p in old if p not in consumed_old)
    return {"added": added, "changed": changed, "removed": removed,
            "renamed": renamed, "unchanged": unchanged}


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true", help="diff only, no write")
    g.add_argument("--commit", action="store_true", help="write manifest")
    ap.add_argument("--root", help="book project root (default: current directory or $BOOK_ROOT)")
    args = ap.parse_args()
    root = resolve_root(args.root)
    require_book_project(root)
    configure(root)

    new = scan()
    old = load_manifest()
    d = diff(old, new)
    # shas only for files that need (re)extraction — unchanged files are in
    # the committed manifest, and dumping every sha into the orchestrator's
    # context on each run wastes tokens (v9.6)
    need = set(d["added"]) | set(d["changed"]) | {r["to"] for r in d["renamed"]}
    out = {
        "sourceCount": len(new),
        "summary": {k: len(v) for k, v in d.items()},
        "diff": {k: v for k, v in d.items() if k != "unchanged"},
        "shas": {p: new[p]["sha256"] for p in sorted(need)},
    }

    if args.commit:
        os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
        with open(MANIFEST, "w", encoding="utf-8") as f:
            json.dump({"committed": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "files": new}, f, indent=2, ensure_ascii=False)
        out["committed"] = True

    if not new:
        out["note"] = "no source files found under sources/ — see sources/README.md for the expected layout"
    out["root"] = ROOT
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
