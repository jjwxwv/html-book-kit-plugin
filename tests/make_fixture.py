#!/usr/bin/env python3
"""Create a throw-away book project from the fixtures (sample book: introductory statistics, Thai).

Used by tests/run_tests.py and to build the preview books. One plan and one set of extractions
serve both summary levels — only the drafts differ, and each level has its own draft store.

  python3 tests/make_fixture.py <dest-dir> [--level 1|2] [--palette NAME] [--build]
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "plugins", "book-kit", "scripts")
FIX = os.path.join(HERE, "fixtures")
TITLE = "สถิติเบื้องต้นสำหรับการวิเคราะห์ข้อมูล"

# source path -> (extraction path relative to .book-state/extractions/, chapter id, unit count)
SOURCES = {
    "sources/ch1/1 intro.md": ("ch1/1-intro.md", "1", 6),
    "sources/ch2/2.1 central.md": ("ch2/2.1-central.md", "2", 5),
    "sources/ch2/2.2 dispersion.md": ("ch2/2.2-dispersion.md", "2", 10),
    "sources/ch2/2.3 review.md": ("ch2/2.3-review.md", "2", 4),
    "sources/ch3/3 probability.md": ("ch3/3-probability.md", "3", 12),
    "sources/ch4/4 normal.md": ("ch4/4-normal.md", "4", 7),
}
# what a real analyst adds to a unit: key terms every faithful chapter contains, and the
# "procedure" flag for units whose steps are themselves the content
UNIT_NOTES = {
    ("ch2/2.1-central.md", 1): {"keys": "mean"},
    ("ch2/2.1-central.md", 2): {"keys": "median"},
    ("ch2/2.1-central.md", 3): {"keys": "mode"},
    ("ch2/2.2-dispersion.md", 3): {"keys": "quartile", "flags": "procedure"},
    ("ch2/2.2-dispersion.md", 7): {"keys": "variance; standard deviation"},
    ("ch3/3-probability.md", 9): {"keys": "conditional probability"},
    ("ch3/3-probability.md", 10): {"keys": "Bayes' theorem"},
    ("ch4/4-normal.md", 1): {"keys": "normal distribution"},
    ("ch4/4-normal.md", 4): {"keys": "z-score"},
}


def run(script, *args, root):
    """Run a kit script against a project; returns CompletedProcess (stdout is JSON for most scripts)."""
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, script), *args, "--root", root],
                          capture_output=True, text=True, encoding="utf-8")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def set_config(root, **changes):
    """set_config(root, level=1, palette="ocean", title=..., raw={"ui": {...}})"""
    path = os.path.join(root, "book.config.json")
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    for key, value in changes.items():
        if key == "level":
            cfg.setdefault("content", {})["level"] = value
        elif key == "palette":
            cfg.setdefault("ui", {})["palette"] = value
        elif key == "raw":
            for section, values in value.items():
                cfg.setdefault(section, {}).update(values)
        else:
            cfg.setdefault("book", {})[key] = value
    write(path, json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")


def drafts_dir(root, level):
    return os.path.join(root, ".book-state", "drafts", f"L{level}")


def copy_drafts(root, level):
    dst = drafts_dir(root, level)
    os.makedirs(dst, exist_ok=True)
    for name in sorted(os.listdir(os.path.join(FIX, "drafts", f"L{level}"))):
        shutil.copyfile(os.path.join(FIX, "drafts", f"L{level}", name), os.path.join(dst, name))


def extraction_text(src, chapter, units, ext, stamped=True):
    body = source_text(src, units)
    lines = ["---", f"source: {src}"]
    if stamped:
        lines.append(f"sha256: {hashlib.sha256(body.encode('utf-8')).hexdigest()}")
    lines.append(f'chapter: "{chapter}"')
    if stamped:
        lines += [f"units: {units}", "extracted: 2026-10-05"]
    lines += ["---", "", "# Overview", "", "Synthetic fixture extraction.", "", "# Units", ""]
    for u in range(1, units + 1):
        note = UNIT_NOTES.get((ext, u), {})
        lines += [f"## U{u} [§{u}] (important) point {u}", f"- teaches: point {u}", "- visual: none"]
        if note.get("flags"):
            lines.append(f"- flags: {note['flags']}")
        if note.get("keys"):
            lines.append(f"- keys: {note['keys']}")
        lines.append("")
    lines += ["# Key verbatim", "", "none", ""]
    return "\n".join(lines)


def source_text(src, units):
    name = os.path.basename(src)
    return f"# {name}\n\n" + "\n".join(f"- point {i} of {name}" for i in range(1, units + 1)) + "\n"


def make_project(dest, level=2, palette=None):
    os.makedirs(dest, exist_ok=True)
    r = run("init_project.py", "--title", TITLE, root=dest)
    if r.returncode != 0:
        raise RuntimeError("init failed: " + r.stderr)
    set_config(dest, level=level, subtitle="สรุปเนื้อหารายวิชา STAT 101",
               author="เรียบเรียงจากเอกสารประกอบการสอน")
    if palette:
        set_config(dest, palette=palette)
    shutil.copyfile(os.path.join(FIX, "plan", "book-plan.json"),
                    os.path.join(dest, ".book-state", "plan", "book-plan.json"))
    for src, (ext, chapter, units) in SOURCES.items():
        write(os.path.join(dest, *src.split("/")), source_text(src, units))
        write(os.path.join(dest, ".book-state", "extractions", *ext.split("/")),
              extraction_text(src, chapter, units, ext))
    copy_drafts(dest, level)
    return dest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dest")
    ap.add_argument("--level", type=int, default=2, choices=(1, 2))
    ap.add_argument("--palette")
    ap.add_argument("--build", action="store_true", help="also run build_book.py and validate_book.py")
    args = ap.parse_args()
    dest = os.path.abspath(args.dest)
    make_project(dest, args.level, args.palette)
    if args.build:
        for script, extra in (("build_book.py", ()), ("validate_book.py", ()), ("scan_sources.py", ("--commit",))):
            r = run(script, *extra, root=dest)
            head = (r.stdout or r.stderr).strip().splitlines()
            print(script, "exit", r.returncode, "|", " ".join(head[:3])[:160])
    print("project:", dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
