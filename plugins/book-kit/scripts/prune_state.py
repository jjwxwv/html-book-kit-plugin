#!/usr/bin/env python3
"""Delete stale .book-state files after sources were removed.

Agents can Write/Edit files but never delete them, so removing a source file
leaves its extraction behind; validate_book.py then reports it
(`extraction.stale` warning, and any coverage entry still pointing at it
fails as `coverage.stale_ref`). This script is the deletion arm —
/build-book and /update-book run it whenever `scan_sources.py --status`
reports removed files.

Stale =
  * an extraction under .book-state/extractions/ whose frontmatter `source:`
    path no longer exists AND whose `sha256:` matches no current source
    (a renamed-but-not-yet-remapped extraction keeps its sha -> skipped);
  * an extracted-office cache file whose recorded sha256 matches no current
    source (superseded versions of changed .pptx/.docx).

Plan/coverage entries of removed sources remain the architect's job.

Usage (run from the book project root; the project is the current directory,
or pass --root <dir>):
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/prune_state.py"            # delete + print JSON summary
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/prune_state.py" --dry-run  # list only, delete nothing

Refuses to act when sources/ contains no source files at all (protects
against pruning everything after an accidental folder wipe). Exit 0 always.
"""
import argparse
import hashlib
import json
import os
import re
import sys

# Project resolution (plugin edition): see scan_sources.py — the project is the
# current directory (or --root / BOOK_ROOT); globals are assigned by configure().
ROOT = SRC = EXTRACTIONS = OFFICE = None


def resolve_root(explicit=None) -> str:
    return os.path.abspath(explicit or os.environ.get("BOOK_ROOT") or os.getcwd())


def configure(root: str) -> None:
    global ROOT, SRC, EXTRACTIONS, OFFICE
    ROOT = root
    SRC = os.path.join(ROOT, "sources")
    EXTRACTIONS = os.path.join(ROOT, ".book-state", "extractions")
    OFFICE = os.path.join(ROOT, ".book-state", "extracted-office")


def require_book_project(root: str) -> None:
    if os.path.isfile(os.path.join(root, "book.config.json")) or os.path.isdir(os.path.join(root, "sources")):
        return
    print(json.dumps({"error": "not a book project", "root": root,
                      "hint": "run from the project root (needs book.config.json or sources/), "
                              "pass --root <dir>, or run /book-kit:init to create one"},
                     ensure_ascii=False), file=sys.stderr)
    sys.exit(2)
IGNORE_NAMES = {".gitkeep", ".DS_Store", "Thumbs.db"}  # keep in sync with scan_sources.py
IGNORE_EXT = {".tmp", ".part", ".crdownload"}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def walk_sources() -> dict:
    out = {}
    if not os.path.isdir(SRC):
        return out
    for dirpath, dirnames, filenames in os.walk(SRC):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name in IGNORE_NAMES or name.startswith(".") or name.lower() == "readme.md":
                continue
            if os.path.splitext(name)[1].lower() in IGNORE_EXT:
                continue
            full = os.path.join(dirpath, name)
            out[os.path.relpath(full, ROOT).replace(os.sep, "/")] = full
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="list only, delete nothing")
    ap.add_argument("--root", help="book project root (default: current directory or $BOOK_ROOT)")
    args = ap.parse_args()
    root = resolve_root(args.root)
    require_book_project(root)
    configure(root)

    srcs = walk_sources()
    out = {"root": ROOT, "dryRun": args.dry_run, "removedExtractions": [], "removedOfficeCache": [],
           "skippedRenamed": [], "skippedUnparseable": []}
    if not srcs:
        out["refused"] = ("sources/ contains no source files — refusing to prune "
                          "everything; delete .book-state/ manually if this is intentional")
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    src_paths = set(srcs)
    shas = {sha256(p) for p in srcs.values()}

    # --- extractions ---
    if os.path.isdir(EXTRACTIONS):
        for dirpath, _, filenames in os.walk(EXTRACTIONS):
            for name in filenames:
                if not name.endswith(".md"):
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
                with open(full, "r", encoding="utf-8") as f:
                    head = f.read(4000)
                m_src = re.search(r"^source:\s*(.+)$", head, re.M)
                if not m_src:
                    out["skippedUnparseable"].append(rel)
                    continue
                if m_src.group(1).strip() in src_paths:
                    continue
                m_sha = re.search(r"^sha256:\s*([0-9a-fA-F]{64})\b", head, re.M)
                if m_sha and m_sha.group(1).lower() in shas:
                    out["skippedRenamed"].append(rel)  # pending rename remap, not stale
                    continue
                out["removedExtractions"].append(rel)
                if not args.dry_run:
                    os.remove(full)
        if not args.dry_run:  # drop now-empty chapter dirs (keep the root)
            for dirpath, _, _ in os.walk(EXTRACTIONS, topdown=False):
                if dirpath != EXTRACTIONS and not os.listdir(dirpath):
                    os.rmdir(dirpath)

    # --- office cache ---
    if os.path.isdir(OFFICE):
        for name in sorted(os.listdir(OFFICE)):
            if not name.endswith(".md"):
                continue
            full = os.path.join(OFFICE, name)
            rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
            with open(full, "r", encoding="utf-8") as f:
                head = f.read(500)
            m = re.search(r"sha256:\s*([0-9a-fA-F]{64})", head)
            if not m:
                out["skippedUnparseable"].append(rel)
                continue
            if m.group(1).lower() in shas:
                continue
            out["removedOfficeCache"].append(rel)
            if not args.dry_run:
                os.remove(full)

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
