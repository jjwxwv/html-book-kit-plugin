#!/usr/bin/env python3
"""Shared helpers for the book-kit scripts.

One place for everything two or more scripts must agree on: project resolution, effective
configuration, the list of source files, how an extraction file is parsed, how a plan is read
and turned into the coverage ledger, the per-level draft store and the input fingerprints that
tell a fresh draft from a stale one. Imported by the other scripts; not run directly.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
import zlib

KIT_VERSION = "11.5.0"
TEMPLATE_CONTRACT = "11"
# Version of the .pptx/.docx pre-extractor. 2 = equations, SmartArt text, shapes wrapped in
# mc:AlternateContent, text boxes, chart data and line breaks are kept (v11.0 dropped them).
# 3 = endnotes, numbered lists as "1." items, lines longer than LONG_LINE wrapped; text sources
# with such lines get a wrapped copy too.
OFFICE_EXTRACTOR = 3
# what each extractor version reads that the one before it dropped (header fields of the cache)
RECOVERED_SINCE = {2: ("equations", "smartart", "wrapped", "textboxes", "charts", "footnotes"),
                   3: ("endnotes", "longlines")}

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_TEMPLATES = os.path.join(PLUGIN_ROOT, "templates")

# Summary levels (requirement v2-2 #2). The level changes the density of the explanation only —
# never the plan, the coverage or the supplement list.
LEVELS = {1: {"key": "review"}, 2: {"key": "study"}}
DEFAULT_LEVEL = 2
LEGACY_DRAFT_LEVEL = 2          # drafts written before v11 carry no stamp; v10 wrote level 2
DRAFT_STAMP_RE = re.compile(r'<!--\s*book-kit:draft\s+chapter="([^"]*)"\s+level="(\d+)"(?:\s+rev="(\d+)")?\s*-->')
PALETTE_NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,31}")
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-\[\]]{0,63}")
AGENT_ROLES = ("analyst", "architect", "writer", "auditor", "builder")

# ----------------------------------------------------------------------------- sources
IGNORE_NAMES = {".gitkeep", ".DS_Store", "Thumbs.db", "desktop.ini"}
IGNORE_EXT = {".tmp", ".part", ".crdownload"}
OFFICE_EXT = {".pptx", ".docx"}
TEXT_EXT = {".md", ".markdown", ".txt", ".html", ".htm"}
# The reading tool returns a limited number of lines and characters per call. A line longer than
# LONG_LINE is wrapped at about WRAP_AT in the pre-extracted copy the analyst reads; a text file
# beyond LONG_TEXT_* cannot be taken in with one read, so its extraction must carry line locators.
LONG_LINE, WRAP_AT = 1800, 1000
LONG_TEXT_LINES, LONG_TEXT_BYTES = 1500, 48000
SUPPORTED_EXT = {".pdf", ".md", ".markdown", ".txt", ".html", ".htm", ".pptx", ".docx",
                 ".png", ".jpg", ".jpeg", ".webp", ".gif"}
UNSUPPORTED_HINTS = {
    ".ppt": "save it as .pptx, or export it to PDF", ".pps": "save it as .pptx, or export it to PDF",
    ".doc": "save it as .docx, or export it to PDF", ".rtf": "save it as .docx, or export it to PDF",
    ".odt": "export it to PDF or .docx", ".odp": "export it to PDF or .pptx",
    ".key": "export it to PDF", ".pages": "export it to PDF",
    ".xls": "export the sheets that matter to PDF", ".xlsx": "export the sheets that matter to PDF",
}
CONTINUE_MARK = "<!-- continue -->"      # an extraction that is still being written ends with this line


def resolve_root(explicit=None):
    return os.path.abspath(explicit or os.environ.get("BOOK_ROOT") or os.getcwd())


def require_book_project(root):
    """Exit 2 unless root looks like a book project (protects against a stray cd)."""
    if os.path.isfile(os.path.join(root, "book.config.json")) or os.path.isdir(os.path.join(root, "sources")):
        return
    print(json.dumps({"error": "not a book project", "root": root,
                      "hint": "run from the project root (needs book.config.json or sources/), "
                              "pass --root <dir>, or run /book-kit:init to create one"},
                     ensure_ascii=False), file=sys.stderr)
    sys.exit(2)


def resolve_templates(root, explicit=None):
    """--templates, else a project-local templates/ override, else the plugin templates."""
    if explicit:
        return os.path.abspath(explicit)
    local = os.path.join(root, "templates")
    return local if os.path.isdir(local) else PLUGIN_TEMPLATES


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def walk_sources(root):
    """({project-relative path: absolute path} of supported source files,
        [{"path", "hint"}] of files the kit cannot read).

    Skipped silently: dot-files, Office lock files (~$name.docx), partial downloads and any
    readme.md (reserved for notes about the folder)."""
    src = os.path.join(root, "sources")
    sources, unsupported = {}, []
    if not os.path.isdir(src):
        return sources, unsupported
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name in IGNORE_NAMES or name.startswith(".") or name.startswith("~$") or name.lower() == "readme.md":
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in IGNORE_EXT:
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if ext in SUPPORTED_EXT:
                sources[rel] = full
            else:
                unsupported.append({"path": rel, "hint": UNSUPPORTED_HINTS.get(
                    ext, "convert it to PDF or Markdown")})
    return sources, unsupported


_CHAPTER_KEY_RE = re.compile(r"^(?:chapter|ch|week|lecture|lec|unit|บทที่|บท)?[\s._-]*0*(\d+)", re.I)


def source_chapter(rel):
    """Chapter number a source path announces: its first folder under sources/ ("ch3 - x",
    "03 x", "3"), or the file's own numeric prefix when it sits directly in sources/."""
    parts = rel.replace("\\", "/").split("/")
    if parts and parts[0] == "sources":
        parts = parts[1:]
    if not parts:
        return None
    head = parts[0] if len(parts) > 1 else os.path.splitext(parts[0])[0]
    m = _CHAPTER_KEY_RE.match(head.strip())
    return m.group(1) if m else None


def pdf_page_count(path):
    """Page count of a PDF, or None when no reliable reader is available (pypdf / pdfinfo)."""
    for mod in ("pypdf", "PyPDF2"):
        try:
            reader_cls = __import__(mod, fromlist=["PdfReader"]).PdfReader
        except Exception:
            continue
        try:
            return len(reader_cls(path, strict=False).pages)
        except Exception:
            break
    try:
        out = subprocess.run(["pdfinfo", path], capture_output=True, text=True, timeout=30)
        m = re.search(r"^Pages:\s*(\d+)", out.stdout or "", re.M)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return pdf_pages_stdlib(path)


def pdf_pages_stdlib(path, limit=256 << 20):
    """Page count read from the PDF itself with the standard library, for machines without pypdf
    or pdfinfo. Two independent readings must agree — the number of /Type /Page objects (also
    inside compressed object streams) and a /Count in the file — otherwise None: an unknown
    count is reported (extraction.length_unverified), never guessed."""
    try:
        if os.path.getsize(path) > limit:
            return None
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if re.search(rb"/Encrypt\s+\d+\s+\d+\s+R|/Encrypt\s*<<", data):
        return None
    blobs, pos = [data], 0
    while True:
        i = data.find(b"/ObjStm", pos)
        if i < 0:
            break
        s = data.find(b"stream", i)
        e = data.find(b"endstream", s) if s >= 0 else -1
        if s < 0 or e < 0:
            break
        raw = data[s + 6:e]
        raw = raw[2:] if raw.startswith(b"\r\n") else raw[1:] if raw[:1] in (b"\n", b"\r") else raw
        try:
            blobs.append(zlib.decompressobj().decompress(raw))
        except zlib.error:
            pass
        pos = e
    blob = b"\n".join(blobs)
    leaves = len(re.findall(rb"/Type\s*/Page(?![A-Za-z])", blob))
    counts = {int(c) for c in re.findall(rb"/Count\s+(\d+)", blob)}
    return leaves if leaves and leaves in counts else None


def read_target(root, rel, sha):
    """The file an analyst opens for a source: its pre-extracted copy when there is one (always for
    .pptx/.docx, for a text source only when it has over-long lines), else the source itself
    (None for an office file that was not pre-extracted). Line locators count lines of this file."""
    ext = os.path.splitext(rel)[1].lower()
    cache = office_cache_path(root, sha) if sha else ""
    if cache and os.path.isfile(cache) and (ext in OFFICE_EXT or ext in TEXT_EXT):
        return cache
    return None if ext in OFFICE_EXT else os.path.join(root, *rel.split("/"))


def text_shape(path):
    """(number of the last non-blank line, set of non-blank line numbers, longest line, bytes) of a
    text file; (None, set(), 0, 0) when it cannot be read."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except (OSError, TypeError):
        return None, set(), 0, 0
    filled, longest = set(), 0
    for n, line in enumerate(data.decode("utf-8", "replace").split("\n"), 1):
        if line.strip():
            filled.add(n)
            longest = max(longest, len(line))
    return (max(filled) if filled else 0), filled, longest, len(data)


def office_cache_path(root, sha):
    return os.path.join(root, ".book-state", "extracted-office", sha[:12] + ".md")


def office_cache_info(root, sha):
    """Header fields of the pre-extracted markdown of a .pptx/.docx (None when not extracted).
    v11.0 caches have no "extractor" field and count as extractor 1."""
    try:
        with open(office_cache_path(root, sha), "r", encoding="utf-8") as f:
            head = f.read(800)
    except OSError:
        return None
    m = re.match(r"\s*<!--(.*?)-->", head, re.S)
    info = {"extractor": 1}
    if not m:
        return info
    for part in m.group(1).split("|"):
        key, _, value = part.strip().partition(":")
        key, value = key.strip().lower(), value.strip()
        if not key:
            continue
        info[key] = int(value) if re.fullmatch(r"\d+", value) and key != "sha256" else value
    return info


# ----------------------------------------------------------------------------- configuration
def load_config(root):
    """(raw_dict, error_or_None). A missing/unreadable config yields {} plus the reason."""
    path = os.path.join(root, "book.config.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}, "book.config.json not found"
    except (OSError, ValueError) as e:
        return {}, f"book.config.json not readable ({e})"
    if not isinstance(raw, dict):
        return {}, "book.config.json must contain a JSON object"
    return raw, None


def _obj(d, key):
    v = d.get(key) if isinstance(d, dict) else None
    return v if isinstance(v, dict) else {}


def effective_config(raw):
    """(cfg, issues). cfg has every key the kit reads, defaults applied.
    issues: [{"code", "detail", "fatal"}] — fatal ones must stop a build."""
    issues = []
    book, content, ui, pipeline, audit = (_obj(raw, k) for k in ("book", "content", "ui", "pipeline", "audit"))
    feats = _obj(ui, "features")

    lv = content.get("level", DEFAULT_LEVEL)
    level = None
    if isinstance(lv, bool):
        pass
    elif isinstance(lv, int) and lv in LEVELS:
        level = lv
    elif isinstance(lv, float) and lv.is_integer() and int(lv) in LEVELS:
        level = int(lv)
    elif isinstance(lv, str) and lv.strip().isdigit() and int(lv.strip()) in LEVELS:
        level = int(lv.strip())
    if level is None:
        issues.append({"code": "config.level", "fatal": True,
                       "detail": f"content.level must be 1 (review) or 2 (study); got {lv!r}"})
        level = DEFAULT_LEVEL

    def _int(obj, section, key, default, lo, hi):
        v = obj.get(key, default)
        if isinstance(v, bool) or not isinstance(v, int) or not (lo <= v <= hi):
            issues.append({"code": "config.value", "fatal": False,
                           "detail": f"{section}.{key} must be an integer {lo}..{hi}; got {v!r} — using {default}"})
            return default
        return v

    palette = ui.get("palette")
    if palette is not None and not (isinstance(palette, str) and PALETTE_NAME_RE.fullmatch(palette)):
        issues.append({"code": "config.palette", "fatal": False,
                       "detail": f"ui.palette must be a palette name; got {palette!r} — using the default palette"})
        palette = None
    custom = ui.get("custom_palette")
    if custom is not None and not isinstance(custom, dict):
        issues.append({"code": "config.palette", "fatal": False,
                       "detail": "ui.custom_palette must be an object — ignored"})
        custom = None
    for dead in ("accent", "accent2"):
        if dead in ui:
            issues.append({"code": "config.deprecated", "fatal": False,
                           "detail": f"ui.{dead} is ignored since v11 — set ui.palette or ui.custom_palette "
                                     "(see /book-kit:design)"})

    # optional per-role model override, passed by the orchestrator when it delegates
    models = {}
    raw_models = pipeline.get("models")
    if raw_models is not None and not isinstance(raw_models, dict):
        issues.append({"code": "config.value", "fatal": False,
                       "detail": "pipeline.models must be an object such as {\"writer\": \"opus\"} — ignored"})
        raw_models = None
    for role, value in (raw_models or {}).items():
        if role not in AGENT_ROLES or not isinstance(value, str) or not MODEL_RE.fullmatch(value.strip()):
            issues.append({"code": "config.value", "fatal": False,
                           "detail": f"pipeline.models.{role}={value!r} ignored — roles are "
                                     f"{', '.join(AGENT_ROLES)}; values are a model alias or id"})
            continue
        models[role] = value.strip()

    # how an approval of audit fixes is recorded: "auto" — by the plugin's hook when the user types
    # /book-kit:apply-fixes (enforced as soon as the hook is seen to run in this project); "off" — not
    # checked by script (the rules still apply)
    gate = audit.get("approval_gate", "auto")
    if gate not in ("auto", "off"):
        issues.append({"code": "config.value", "fatal": False,
                       "detail": f"audit.approval_gate must be \"auto\" or \"off\"; got {gate!r} — using \"auto\""})
        gate = "auto"

    cfg = {
        "book": {
            "title": str(book.get("title") or "").strip() or "Untitled",
            "subtitle": str(book.get("subtitle") or "").strip(),
            "author": str(book.get("author") or "").strip(),
            "language": str(book.get("language") or "th").strip() or "th",
            "slug": str(book.get("slug") or "").strip(),
        },
        "content": {
            "level": level,
            "audience": str(content.get("audience") or "").strip(),
            "style_notes": str(content.get("style_notes") or "").strip(),
            "recall_questions": content.get("recall_questions", True) is not False,
        },
        "ui": {
            "palette": palette,
            "custom_palette": custom,
            "features": {"math_katex_cdn": feats.get("math_katex_cdn") is True,
                         "mermaid_cdn": feats.get("mermaid_cdn") is True},
        },
        "pipeline": {"max_parallel_agents": _int(pipeline, "pipeline", "max_parallel_agents", 6, 1, 20),
                     "models": models},
        "audit": {"max_source_spot_checks": _int(audit, "audit", "max_source_spot_checks", 10, 0, 200),
                  "max_fix_batches": _int(audit, "audit", "max_fix_batches", 5, 1, 50),
                  "approval_gate": gate},
    }
    return cfg, issues


# ----------------------------------------------------------------------------- extractions
PRIORITIES = ("critical", "important", "supporting", "illustrative", "redundant", "administrative")
_UNIT_RE = re.compile(r"^##\s+U(\d+)\b(.*)$")
_PRIORITY_RE = re.compile(r"\((%s)\)" % "|".join(PRIORITIES), re.I)
_LOCATOR_RE = re.compile(r"\[([^\]]*)\]")
_LOC_NUM_RE = re.compile(r"(?<![A-Za-z])(?:pages?|pp?|slides?|sl|s|หน้า|สไลด์)\s*\.?\s*(\d+)(?:\s*[-–—]\s*(?:pp?\.?|s\.?)?\s*(\d+))?", re.I)
_LOC_LINE_RE = re.compile(r"(?<![A-Za-z])(?:lines?|ll?|บรรทัด)\s*\.?\s*(\d+)(?:\s*[-–—]\s*(?:ll?\.?)?\s*(\d+))?", re.I)
_FM_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):\s?(.*)$")
_SHA_RE = re.compile(r"[0-9a-fA-F]{64}")
FM_ORDER = ["source", "sha256", "chapter", "units", "pages", "slides", "lines", "extractor", "extracted"]


def split_frontmatter(text):
    """([[key, value], ...] in file order, body) for a '---' fenced block of 'key: value' lines;
    (None, text) when the file has no such block."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, min(len(lines), 80)):
        if lines[i].strip() == "---":
            fields = []
            for ln in lines[1:i]:
                m = _FM_KEY_RE.match(ln)
                fields.append([m.group(1), m.group(2)] if m else [None, ln])
            return fields, "\n".join(lines[i + 1:])
    return None, text


def join_frontmatter(fields, body):
    out = ["---"]
    for key, value in fields:
        out.append(value if key is None else f"{key}: {value}".rstrip())
    out.append("---")
    return "\n".join(out) + "\n" + body


def _fm_int(value):
    m = re.match(r"\s*(\d+)", value or "")
    return int(m.group(1)) if m else None


def _locator_numbers(raw, pattern=_LOC_NUM_RE, span=5000):
    nums = set()
    for a, b in pattern.findall(raw or ""):
        lo, hi = int(a), int(b) if b else int(a)
        if lo <= hi and hi - lo <= span:
            nums.update(range(lo, hi + 1))
    return nums


def parse_extraction(path, rel=""):
    """Everything the scripts need to know about one extraction file.

    The body is the truth for the units: they are counted from the "## U<n>" headings, never
    taken from the frontmatter. Each unit: {"n", "locator" (set of page/slide numbers),
    "line_locator" (set of line numbers of the file the analyst read), "priority", "flags" (set),
    "keys" (list), "text"}."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    fields, body = split_frontmatter(text)
    fm = {}
    if fields is not None:
        for key, value in fields:
            if key and key not in fm:
                fm[key] = value
    else:                                   # tolerate a file without fences: read the head
        for key in ("source", "sha256", "chapter", "units", "pages", "slides", "lines", "extractor"):
            m = re.search(r"^%s:\s*(.+)$" % key, text[:4000], re.M)
            if m:
                fm[key] = m.group(1)
    sha = _SHA_RE.search(fm.get("sha256", ""))
    info = {
        "path": path, "rel": rel,
        "source": fm.get("source", "").strip(),
        "sha256": sha.group(0).lower() if sha else "",
        "chapter": fm.get("chapter", "").strip().strip("\"'"),
        "units_field": _fm_int(fm.get("units")),
        "pages": _fm_int(fm.get("pages")), "slides": _fm_int(fm.get("slides")),
        "lines": _fm_int(fm.get("lines")), "extractor": _fm_int(fm.get("extractor")),
        "has_frontmatter": fields is not None,
        "error": bool(re.search(r"^#\s*Error\b", text, re.M)),
        "incomplete": CONTINUE_MARK in text,
        "units": {}, "order": [], "duplicates": [],
    }
    current = None
    for line in body.split("\n"):
        m = _UNIT_RE.match(line)
        if m:
            n, rest = int(m.group(1)), m.group(2)
            loc = _LOCATOR_RE.search(rest)
            pr = _PRIORITY_RE.search(rest)
            current = {"n": n, "locator": _locator_numbers(loc.group(1)) if loc else set(),
                       "line_locator": _locator_numbers(loc.group(1), _LOC_LINE_RE, 400000) if loc else set(),
                       "priority": pr.group(1).lower() if pr else "", "flags": set(), "keys": [],
                       "lines": [line.rstrip()]}
            info["order"].append(n)
            if n in info["units"]:
                info["duplicates"].append(n)
            info["units"][n] = current
            continue
        if line.startswith("# "):           # "# Key verbatim", "# Gaps", ... end the unit list
            current = None
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped == CONTINUE_MARK:
            continue
        current["lines"].append(line.rstrip())
        low = stripped.lower()
        if low.startswith("- flags:"):
            for tok in re.split(r"[|,;\s]+", stripped[8:]):
                tok = tok.strip().lower()
                if tok and tok != "none":
                    current["flags"].add(tok.split("=")[0])
        elif low.startswith("- keys:"):
            current["keys"] = [k.strip() for k in stripped[7:].split(";") if k.strip()][:8]
    for u in info["units"].values():
        lines = u.pop("lines")
        u["text"] = "\n".join(lines).strip()
        u["fp_text"] = unit_fp_text(lines, u["flags"])
    nums = sorted(info["units"])
    info["count"] = len(nums)
    info["numbering_ok"] = not info["duplicates"] and nums == list(range(1, len(nums) + 1))
    return info


_UNIT_HEAD_RE = re.compile(r"^##\s+U\d+\b\s*(?:\[[^\]]*\])?\s*")


def unit_fp_text(lines, flags=()):
    """What a unit says, without what merely locates it: the unit number and the locator are left
    out and a flags line counts by its flag names only (their values refer to other unit numbers).
    A unit that only moved — lines inserted above it, another unit added before it — keeps this text,
    so the sections that cover it are not rewritten."""
    out = [_UNIT_HEAD_RE.sub("", lines[0]).strip()] if lines else []
    for line in lines[1:]:
        if line.strip().lower().startswith("- flags:"):
            line = "- flags: " + " | ".join(sorted(flags))
        out.append(line.rstrip())
    return "\n".join(out).strip()


def extraction_index(root):
    """{path relative to .book-state/extractions/: parse_extraction(...)}."""
    base = os.path.join(root, ".book-state", "extractions")
    idx = {}
    if not os.path.isdir(base):
        return idx
    for dirpath, _, filenames in os.walk(base):
        for name in sorted(filenames):
            if not name.endswith(".md") or ".part-" in name:
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, base).replace(os.sep, "/")
            idx[rel] = parse_extraction(full, rel)
    return idx


def update_frontmatter(path, updates, remove=()):
    """Set (or add) frontmatter keys of an extraction file; returns True when the file changed."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    fields, body = split_frontmatter(text)
    if fields is None:
        fields, body = [], text if text.startswith("\n") else "\n" + text
    fields = [f for f in fields if f[0] not in remove]
    for key, value in updates.items():
        for f in fields:
            if f[0] == key:
                f[1] = str(value)
                break
        else:
            fields.append([key, str(value)])
    fields.sort(key=lambda f: FM_ORDER.index(f[0]) if f[0] in FM_ORDER else len(FM_ORDER))
    new = join_frontmatter(fields, body)
    if new == text:
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    return True


def source_size(root, source_rel, sha, parsed=None):
    """("pages"|"slides"|None, count|None) of a source, from mechanical evidence only."""
    ext = os.path.splitext(source_rel)[1].lower()
    if ext == ".pdf":
        return "pages", pdf_page_count(os.path.join(root, *source_rel.split("/")))
    if ext == ".pptx":
        info = office_cache_info(root, sha) if sha else None
        n = info.get("slides") if info else None
        return "slides", n if isinstance(n, int) else None
    if ext == ".docx" or ext in TEXT_EXT:
        return "lines", text_shape(read_target(root, source_rel, sha))[0]
    return None, None


# Content lines after the last line any unit locates: from TAIL_BLOCK on the source was not read to
# its end (blocking); a few (TAIL_WARN..) are put before the auditor. Fewer is a closing line.
TAIL_BLOCK, TAIL_WARN = 8, 3


def _check_length(root, epath, e, problems, warnings):
    """Was the source read to its end? Pages and slides are counted mechanically and compared with
    the units' locators; text and .docx sources are compared by the line numbers of the file the
    analyst read. What cannot be checked is said (extraction.length_unverified), never passed."""
    kind, size = source_size(root, e["source"], e["sha256"], e)
    if not kind:
        return
    if kind != "lines":
        size = size if size is not None else e.get(kind)
        what = "page" if kind == "pages" else "slide"
        if not size:
            if kind == "pages":
                warnings.append({"code": "extraction.length_unverified",
                                 "detail": f"{epath}: the page count of {e['source']} could not be determined "
                                           "(pip install pypdf) — it is not checked that the source was read to its "
                                           "last page; auditor must judge"})
            return
        located = set()
        for u in e["units"].values():
            located |= u["locator"]
        if not located:
            warnings.append({"code": "extraction.locator_missing",
                             "detail": f"{epath}: no unit carries a [{what[0]}.N] locator — "
                                       f"cannot check that all {size} {what}s were read"})
            return
        top = max(located)
        if top < size:
            problems.append({"code": "extraction.truncated",
                             "detail": f"{epath}: units stop at {what} {top} but {e['source']} has "
                                       f"{size} {what}s — read the rest"})
        gaps = sorted(set(range(1, min(top, size) + 1)) - located)
        if gaps:
            warnings.append({"code": "extraction.locator_gap",
                             "detail": f"{epath}: no unit for {what}(s) {_ranges(gaps)} of {e['source']} — "
                                       "auditor must judge (blank or skipped?)"})
        return
    target = read_target(root, e["source"], e["sha256"])
    last, filled, longest, nbytes = text_shape(target)
    if not last:
        return
    shown = os.path.relpath(target, root).replace(os.sep, "/")
    located = set()
    for u in e["units"].values():
        located |= u["line_locator"]
    long_file = last > LONG_TEXT_LINES or nbytes > LONG_TEXT_BYTES
    if not located:
        if long_file:
            warnings.append({"code": "extraction.length_unverified",
                             "detail": f"{epath}: {shown} has {last} lines ({nbytes // 1024} KB) — more than one read "
                                       "returns — and no unit carries a [l.a-b] line locator, so it is not checked that "
                                       "the source was read to its end; auditor must judge"})
        return
    top = max(located)
    tail = sorted(n for n in filled if n > top)          # content lines after the last located one
    if last - top > max(5, last // 50) or len(tail) >= TAIL_BLOCK:
        problems.append({"code": "extraction.truncated",
                         "detail": f"{epath}: units stop at line {top} but {shown} has {last} lines "
                                   f"({len(tail)} of them with content after line {top}) — read the rest"})
    elif len(tail) >= TAIL_WARN:
        warnings.append({"code": "extraction.locator_gap",
                         "detail": f"{epath}: no unit for the last line(s) {tail[0]}–{tail[-1]} of {shown} — "
                                   "auditor must judge (skipped?)"})
    runs, run = [], []
    for n in sorted(x for x in filled if x <= top):
        if n in located:
            if len(run) >= 8:
                runs.append(run)
            run = []
        else:
            run.append(n)
    if len(run) >= 8:
        runs.append(run)
    if runs:
        spans = ", ".join(f"{r[0]}–{r[-1]}" for r in runs[:12]) + (" …" if len(runs) > 12 else "")
        warnings.append({"code": "extraction.locator_gap",
                         "detail": f"{epath}: no unit for line(s) {spans} of {shown} — auditor must judge (skipped?)"})


def truncated_after(root, e):
    """Where the units of a stamped extraction stop when its source goes on after that —
    "p.20", "s.7" or "l.240" — else None. The same evidence as extraction.truncated, for the scan:
    such a source is handed to its analyst again instead of being planned and written from."""
    if not e.get("sha256") or e.get("incomplete") or e.get("error") or not e.get("count"):
        return None
    problems = []
    try:
        _check_length(root, e.get("rel") or "", e, problems, [])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not any(p["code"] == "extraction.truncated" for p in problems):
        return None
    kind = source_size(root, e["source"], e["sha256"], e)[0]
    located = set()
    for u in e["units"].values():
        located |= u["line_locator"] if kind == "lines" else u["locator"]
    if not located:
        return None
    return {"pages": "p.", "slides": "s.", "lines": "l."}[kind] + str(max(located))


def check_extractions(root, sources, ext_idx, unsupported=()):
    """(problems, warnings, stale, shas). stale = extraction paths whose source is gone.
    Blocking: a source without an extraction, a missing 'source:', an unstamped, unfinished or
    outdated extraction, broken unit numbering, an extraction that stops before the source does."""
    problems, warnings = [], []
    shas = {}

    def sha_of(rel):
        if rel not in shas:
            try:
                shas[rel] = file_sha256(sources[rel])
            except OSError:
                shas[rel] = ""
        return shas[rel]

    for u in unsupported:
        warnings.append({"code": "sources.unsupported",
                         "detail": f"{u['path']} is not a format the kit reads — {u['hint']}; it is not part of the book"})
    current_shas = None
    stale = set()
    by_source = {}
    for epath, e in sorted(ext_idx.items()):
        if not e["source"]:
            problems.append({"code": "extraction.frontmatter", "detail": f"{epath}: missing 'source:' in frontmatter"})
            continue
        if e["source"] in by_source:
            problems.append({"code": "extraction.duplicate",
                             "detail": f"{epath} and {by_source[e['source']]} both claim {e['source']!r}"})
        by_source.setdefault(e["source"], epath)
        if e["source"] not in sources:
            if current_shas is None:
                current_shas = {sha_of(r) for r in sources}
            if e["sha256"] and e["sha256"] in current_shas:
                warnings.append({"code": "extraction.rename_pending",
                                 "detail": f"{epath}: source moved — run sync_state.py --sources to remap it"})
                continue
            stale.add(epath)
            warnings.append({"code": "extraction.stale",
                             "detail": f"{epath}: source {e['source']!r} no longer exists — "
                                       "sync_state.py --sources deletes stale state"})
            continue
        if e["incomplete"]:
            problems.append({"code": "extraction.incomplete",
                             "detail": f"{epath}: still ends with {CONTINUE_MARK} — the extraction was interrupted"})
            continue
        if not e["sha256"]:
            problems.append({"code": "extraction.unstamped",
                             "detail": f"{epath}: no sha256 — run sync_state.py --stamp"})
        elif e["sha256"] != sha_of(e["source"]):
            problems.append({"code": "extraction.outdated",
                             "detail": f"{epath}: written from another version of {e['source']} "
                                       "(sha256 differs) — re-extract this source"})
        if e["error"] or e["count"] == 0:
            warnings.append({"code": "extraction.error",
                             "detail": f"{epath}: source not (fully) extracted — coverage unknown; "
                                       "auditor must raise a finding"})
            continue
        if not e["numbering_ok"]:
            nums = sorted(e["units"])
            missing = sorted(set(range(1, (nums[-1] if nums else 0) + 1)) - set(nums))
            problems.append({"code": "extraction.unit_numbering",
                             "detail": f"{epath}: units must be U1..U{len(nums)} without gaps or repeats "
                                       f"(missing {missing[:8]}, repeated {sorted(set(e['duplicates']))[:8]})"})
        _check_length(root, epath, e, problems, warnings)
    for rel in sorted(sources):
        if rel not in by_source:
            problems.append({"code": "extraction.missing", "detail": f"no extraction found for {rel}"})
        if os.path.splitext(rel)[1].lower() in OFFICE_EXT:
            info = office_cache_info(root, sha_of(rel)) or {}
            pics, ole = (info.get(k) if isinstance(info.get(k), int) else 0 for k in ("pictures", "ole"))
            if pics or ole:
                warnings.append({"code": "sources.visual_unread",
                                 "detail": f"{rel} (extraction {by_source.get(rel, 'pending')}): {pics} picture(s) and "
                                           f"{ole} embedded object(s) cannot be read from "
                                           "this file — what they show is not in the book unless the text says it; "
                                           "export the file to PDF and put that in sources/ to include them; "
                                           "auditor must judge"})
    return problems, warnings, stale, shas


def _ranges(nums, prefix=""):
    out, start, prev = [], None, None

    def close():
        out.append(f"{prefix}{start}" if start == prev else f"{prefix}{start}–{prefix}{prev}")
    for n in nums:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            close()
            start = prev = n
    if start is not None:
        close()
    return ", ".join(out[:12]) + (" …" if len(out) > 12 else "")


# ----------------------------------------------------------------------------- plan
BREVITY_REASON_RE = re.compile("|".join([
    r"brevity", r"concis", r"shorten", r"too long", r"for length",
    r"reduce length", r"keep(?:ing)?\b[^.]{0,24}\bshort\b", r"kept short",
    r"save space", r"save tokens", r"token (?:budget|limit|cost)",
    r"word count", r"page limit",
    r"\blevel[\s-]?1\b", r"review (?:level|edition|mode|summary)", r"summary level",
    r"กระชับ", r"ยาวเกิน", r"ลดความยาว",
    r"เพื่อประหยัด", r"ประหยัดโทเค็น", r"ประหยัดพื้นที่",
    r"ระดับ\s*1", r"ฉบับทบทวน",
]), re.IGNORECASE)
OMIT_STATES = ("omitted_justified", "administrative", "unresolved")
VALID_STATES = {"represented", "merged"} | set(OMIT_STATES)
_REF_RE = re.compile(r"ext:(.+?)#U(\d+)(?:\s*[-–]\s*U?(\d+))?")
_ID_RE = re.compile(r"\d+(?:\.\d+)*")


def anchor(section_id):
    return "sec-" + str(section_id).replace(".", "-")


def plan_path(root):
    return os.path.join(root, ".book-state", "plan", "book-plan.json")


def load_plan(root):
    """(plan_or_None, error_or_None)."""
    try:
        with open(plan_path(root), "r", encoding="utf-8") as f:
            plan = json.load(f)
    except FileNotFoundError:
        return None, "missing file: .book-state/plan/book-plan.json"
    except (OSError, ValueError) as e:
        return None, f"invalid JSON in .book-state/plan/book-plan.json: {e}"
    if not isinstance(plan, dict):
        return None, ".book-state/plan/book-plan.json must contain a JSON object"
    return plan, None


def plan_chapter_ids(plan):
    chs = (plan or {}).get("chapters") if isinstance(plan, dict) else None
    return [str(ch.get("id", "")) for ch in (chs if isinstance(chs, list) else []) if isinstance(ch, dict)]


def _id_text(value):
    if isinstance(value, bool) or isinstance(value, (dict, list)) or value is None:
        return ""
    return str(value).strip()


def _str_list(value, problems, where):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        problems.append({"code": "plan.shape", "detail": f"{where} must be a list of strings"})
        return []
    out = []
    for v in value:
        if isinstance(v, str):
            out.append(v)
        else:
            problems.append({"code": "plan.shape", "detail": f"{where}: {v!r} is not a string"})
    return out


def normalize_plan(plan):
    """(normalised plan, shape problems). Never raises: whatever an agent wrote, the scripts get
    lists of dicts with string fields, and every malformed piece becomes a plan.shape problem."""
    problems = []
    out = {"chapters": [], "omitted": [], "has_omitted": False, "idHistory": [], "renumber_request": []}
    if not isinstance(plan, dict):
        problems.append({"code": "plan.shape", "detail": "book-plan.json must contain a JSON object"})
        return out, problems
    chapters = plan.get("chapters")
    if not isinstance(chapters, list):
        problems.append({"code": "plan.shape", "detail": "'chapters' must be a list"})
        chapters = []
    for i, ch in enumerate(chapters):
        if not isinstance(ch, dict):
            problems.append({"code": "plan.shape", "detail": f"chapters[{i}] must be an object"})
            continue
        cid = _id_text(ch.get("id"))
        raw_secs = ch.get("sections")
        if raw_secs is None:
            raw_secs = []
        if not isinstance(raw_secs, list):
            problems.append({"code": "plan.shape", "detail": f"chapter {cid!r}: 'sections' must be a list"})
            raw_secs = []
        secs = []
        for j, s in enumerate(raw_secs):
            if not isinstance(s, dict):
                problems.append({"code": "plan.shape", "detail": f"chapter {cid!r}: sections[{j}] must be an object"})
                continue
            sid = _id_text(s.get("id"))
            raw_supp = s.get("supplements")
            if raw_supp is None:
                raw_supp = []
            if not isinstance(raw_supp, list):
                problems.append({"code": "plan.shape", "detail": f"section {sid!r}: 'supplements' must be a list"})
                raw_supp = []
            supps = []
            for sp in raw_supp:
                if not isinstance(sp, dict):
                    problems.append({"code": "plan.shape", "detail": f"section {sid!r}: a supplement is not an object"})
                    continue
                supps.append({"id": _id_text(sp.get("id")), "type": str(sp.get("type") or ""),
                              "reason": str(sp.get("reason") or "")})
            secs.append({"id": sid, "title": str(s.get("title_th") or s.get("title") or "").strip(),
                         "priority": str(s.get("priority") or ""), "notes": str(s.get("notes") or ""),
                         "covers": _str_list(s.get("covers"), problems, f"section {sid!r}: covers"),
                         "merged": _str_list(s.get("merged"), problems, f"section {sid!r}: merged"),
                         "supplements": supps})
        out["chapters"].append({"id": cid, "title": str(ch.get("title_th") or ch.get("title") or "").strip(),
                                "page": str(ch.get("page") or (f"ch-{cid}.html" if cid else "")), "sections": secs})
    omitted = plan.get("omitted")
    if omitted is not None:
        out["has_omitted"] = True
        if not isinstance(omitted, list):
            problems.append({"code": "plan.shape", "detail": "'omitted' must be a list"})
            omitted = []
        for e in omitted:
            if isinstance(e, str):
                e = {"ref": e}
            if not isinstance(e, dict):
                problems.append({"code": "plan.shape", "detail": f"omitted: {e!r} is not an object"})
                continue
            out["omitted"].append({"ref": str(e.get("ref") or ""), "state": str(e.get("state") or "omitted_justified"),
                                   "reason": str(e.get("reason") or "")})
    history = plan.get("idHistory")
    for h in history if isinstance(history, list) else []:
        m = h.get("map") if isinstance(h, dict) else None
        if isinstance(m, dict) and m:
            out["idHistory"].append({"map": {str(k): str(v) for k, v in m.items()}})
    req = plan.get("renumber_request")
    if isinstance(req, dict):
        req = [f"{k}={v}" for k, v in req.items()]
    out["renumber_request"] = [str(x) for x in req] if isinstance(req, list) else []
    return out, problems


def expand_ref(ref):
    """'ext:ch2/2.1-intro.md#U1-U4' (or '#U1-4', '#U3') -> ('ch2/2.1-intro.md', [1, 2, 3, 4])."""
    m = _REF_RE.fullmatch((ref or "").strip())
    if not m:
        raise ValueError(f"bad unit ref {ref!r} (expected ext:<extraction path>#U<n> or #U<a>-U<b>)")
    a, b = int(m.group(2)), int(m.group(3) or m.group(2))
    if b < a or b - a > 5000:
        raise ValueError(f"bad unit range in {ref!r}")
    return m.group(1), list(range(a, b + 1))


def derive_coverage(plan, ext_idx, stale=(), legacy=None):
    """The coverage ledger, derived from the plan alone.

    The plan is the single source of truth: sections list the units they teach ("covers") and the
    duplicates folded into them ("merged"); "omitted" lists every unit left out, with its reason.
    Whatever is in no list is a gap. Returns (ledger, problems, warnings, by_section) with
    ledger = {unit ref: {"state", ...}} and by_section = {section id: [(extraction, unit, state)]}.

    legacy: the hand-written coverage.json of a v11.0 project; used only while the plan has no
    "omitted" list, to carry its omissions and merges over."""
    problems, warnings = [], []
    ledger, by_section, owner = {}, {}, {}
    section_ids = {s["id"] for ch in plan["chapters"] for s in ch["sections"]}

    def assign(epath, n, entry, where):
        key = f"ext:{epath}#U{n}"
        if key in ledger:
            if owner[key] != where:
                problems.append({"code": "coverage.duplicate",
                                 "detail": f"{key} is assigned twice ({owner[key]} and {where}) — "
                                           "every unit resolves to exactly one state"})
            return
        ledger[key], owner[key] = entry, where
        if "section" in entry or "into" in entry:
            by_section.setdefault(entry.get("section") or entry.get("into"), []).append((epath, n, entry["state"]))

    def units_of(ref, where):
        try:
            epath, nums = expand_ref(ref)
        except ValueError as e:
            problems.append({"code": "plan.covers_ref", "detail": f"{where}: {e}"})
            return None, []
        e = ext_idx.get(epath)
        if e is None:
            problems.append({"code": "plan.covers_ref", "detail": f"{where}: {ref} — extraction not found"})
            return None, []
        if epath in stale:
            problems.append({"code": "coverage.stale_ref",
                             "detail": f"{where}: {ref} references removed source {e['source']!r}"})
            return None, []
        bad = [n for n in nums if n not in e["units"]]
        if bad:
            problems.append({"code": "plan.covers_ref",
                             "detail": f"{where}: {ref} — unit(s) {_ranges(bad, 'U')} do not exist "
                                       f"(the extraction has U1..U{e['count']})"})
        return epath, [n for n in nums if n in e["units"]]

    for ch in plan["chapters"]:
        for s in ch["sections"]:
            where = f"section {s['id']}"
            for ref in s["covers"]:
                epath, nums = units_of(ref, where)
                for n in nums:
                    assign(epath, n, {"state": "represented", "section": s["id"]}, where)
            for ref in s["merged"]:
                epath, nums = units_of(ref, where)
                for n in nums:
                    assign(epath, n, {"state": "merged", "into": s["id"]}, where + " (merged)")

    omitted = list(plan["omitted"])
    if not plan["has_omitted"] and isinstance(legacy, dict):
        carried = 0
        for ref, entry in legacy.items():
            if not isinstance(entry, dict) or ref in ledger:
                continue
            state = entry.get("state")
            if state in OMIT_STATES:
                omitted.append({"ref": ref, "state": state, "reason": str(entry.get("reason") or "")})
                carried += 1
            elif state == "merged" and entry.get("into") in section_ids:
                try:
                    epath, nums = expand_ref(ref)
                except ValueError:
                    continue
                if epath in ext_idx and epath not in stale:
                    for n in nums:
                        if n in ext_idx[epath]["units"]:
                            assign(epath, n, {"state": "merged", "into": entry["into"]}, f"section {entry['into']} (merged)")
                            carried += 1
        warnings.append({"code": "plan.legacy_coverage",
                         "detail": f"the plan has no 'omitted' list (v11.0 plan) — {carried} omission/merge entries "
                                   "were carried over from coverage.json; the architect adds 'omitted' on its next run"})
    unresolved = 0
    for e in omitted:
        where = "omitted"
        if e["state"] not in OMIT_STATES:
            problems.append({"code": "coverage.state", "detail": f"omitted {e['ref']}: invalid state {e['state']!r}"})
            continue
        epath, nums = units_of(e["ref"], where)
        if e["state"] == "omitted_justified":
            if not e["reason"].strip():
                problems.append({"code": "coverage.reason", "detail": f"{e['ref']}: omitted_justified without reason"})
            elif BREVITY_REASON_RE.search(e["reason"]):
                warnings.append({"code": "coverage.brevity_reason",
                                 "detail": f"{e['ref']}: omission reason cites brevity/length/summary level "
                                           f"({e['reason']!r}) — not a valid justification "
                                           "(concise but complete; the level never changes coverage); "
                                           "auditor must judge"})
        for n in nums:
            entry = {"state": e["state"]}
            if e["reason"].strip():
                entry["reason"] = e["reason"].strip()
            assign(epath, n, entry, where)
            unit = ext_idx[epath]["units"][n]
            if e["state"] == "unresolved":
                unresolved += 1
            elif unit["priority"] in ("critical", "important"):
                warnings.append({"code": "coverage.priority_omitted",
                                 "detail": f"ext:{epath}#U{n} is marked ({unit['priority']}) by the analyst but is "
                                           f"{e['state']} — auditor must judge whether its meaning is lost"})
    if unresolved:
        problems.append({"code": "coverage.unresolved", "detail": f"{unresolved} unit(s) unresolved"})
    for epath, e in sorted(ext_idx.items()):
        if epath in stale or e["incomplete"] or e["source"] == "":
            continue
        missing = [n for n in sorted(e["units"]) if f"ext:{epath}#U{n}" not in ledger]
        if missing:
            problems.append({"code": "coverage.gap",
                             "detail": f"ext:{epath}: unit(s) {_ranges(missing, 'U')} not accounted for — list each "
                                       "in a section's covers/merged or in the plan's omitted"})
    return dict(sorted(ledger.items())), problems, warnings, by_section


# ----------------------------------------------------------------------------- drafts (one store per level)
def drafts_root(root):
    return os.path.join(root, ".book-state", "drafts")


def drafts_dir(root, level):
    return os.path.join(drafts_root(root), f"L{level}")


def draft_path(root, chapter_id, level):
    return os.path.join(drafts_dir(root, level), f"ch-{chapter_id}.html")


def draft_info(path):
    """Level stamp + content hash of a draft. Unstamped (pre-v11) drafts count as level 2."""
    info = {"exists": False, "stamped": False, "level": None, "chapter": None, "rev": None, "sha": None}
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return info
    info["exists"] = True
    info["sha"] = hashlib.sha256(data).hexdigest()
    m = DRAFT_STAMP_RE.search(data[:800].decode("utf-8", "replace"))
    if m:
        info.update(stamped=True, chapter=m.group(1), level=int(m.group(2)),
                    rev=int(m.group(3)) if m.group(3) else None)
    else:
        info["level"] = LEGACY_DRAFT_LEVEL
    return info


def migrate_layout(root):
    """v11.0 kept one draft set in .book-state/drafts/; v11.1 keeps one per level in
    drafts/L<level>/. Moves each old draft into the folder of the level it was written at
    (lossless, idempotent). Returns the moves made."""
    base = drafts_root(root)
    moved = []
    if not os.path.isdir(base):
        return moved
    for name in sorted(os.listdir(base)):
        full = os.path.join(base, name)
        if not (os.path.isfile(full) and re.fullmatch(r"ch-[\w.-]+\.html", name)):
            continue
        level = draft_info(full)["level"]
        level = level if level in LEVELS else LEGACY_DRAFT_LEVEL
        dst = os.path.join(drafts_dir(root, level), name)
        if os.path.exists(dst):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(full, dst)
        moved.append(f"drafts/{name} -> drafts/L{level}/{name}")
    return moved


def ledger_path(root, level):
    return os.path.join(drafts_dir(root, level), "inputs.json")


def load_ledger(root, level):
    """{chapter id: {"draft_sha", "sections": {id: fingerprint}, "order": [ids]}} written by
    build_book.py: what each draft of this level was written from."""
    try:
        with open(ledger_path(root, level), "r", encoding="utf-8") as f:
            data = json.load(f)
        chapters = data.get("chapters") if isinstance(data, dict) else None
        return {str(k): v for k, v in chapters.items() if isinstance(v, dict)} if isinstance(chapters, dict) else {}
    except (OSError, ValueError):
        return {}


def load_briefed(root, level):
    """{chapter id: {"before", "sections", "order"}} written by sync_state.py --plan: the inputs each
    writer was handed, and the SHA-256 the draft had at that moment (None: no draft yet). A draft
    that has changed since its briefing was written from exactly these inputs."""
    try:
        with open(ledger_path(root, level), "r", encoding="utf-8") as f:
            data = json.load(f)
        briefed = data.get("briefed") if isinstance(data, dict) else None
        return {str(k): v for k, v in briefed.items()
                if isinstance(v, dict) and isinstance(v.get("sections"), dict)} if isinstance(briefed, dict) else {}
    except (OSError, ValueError):
        return {}


def save_ledger(root, level, chapters, briefed=None):
    path = ledger_path(root, level)
    if briefed is None:
        briefed = load_briefed(root, level)
    data = json.dumps({"kit": KIT_VERSION, "level": level, "chapters": chapters, "briefed": briefed},
                      ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    try:
        with open(path, "r", encoding="utf-8") as f:
            if f.read() == data:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(data)
    return True


FP_VERSION = 2


def chapter_inputs(chapter, ext_idx, version=FP_VERSION):
    """Fingerprint of everything a writer turns into a chapter draft, per section: its title,
    priority, notes, supplement requests and the text of every unit it covers or merges.
    Section ids are left out on purpose, so renumbering a section does not make its draft stale —
    and so are unit numbers and locators (fingerprint version 2): a unit that only moved inside its
    source after an edit elsewhere keeps its fingerprint. version=1 is the v11.1/v11.2 formula,
    kept to carry existing ledgers over."""
    sections = {}
    for s in chapter["sections"]:
        units = []
        for kind, refs in (("c", s["covers"]), ("m", s["merged"])):
            for ref in refs:
                try:
                    epath, nums = expand_ref(ref)
                except ValueError:
                    units.append([kind, ref, 0, None] if version == 1 else [kind, ref, None])
                    continue
                e = ext_idx.get(epath)
                for n in nums:
                    u = e["units"].get(n) if e else None
                    if version == 1:
                        units.append([kind, epath, n, u["text"] if u else None])
                    else:
                        units.append([kind, epath, u["fp_text"] if u else None])
        units.sort(key=lambda x: tuple("" if v is None else v for v in x))
        blob = json.dumps([s["title"], s["priority"], s["notes"], units,
                           [[x["type"], x["reason"]] for x in s["supplements"]]],
                          ensure_ascii=False, sort_keys=True)
        sections[s["id"]] = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return {"sections": sections, "order": [s["id"] for s in chapter["sections"]]}


def upgrade_inputs(recorded, chapter, ext_idx):
    """A ledger entry or briefing written by v11.1/v11.2 holds version-1 fingerprints. Each section
    whose old fingerprint still equals the old formula applied to today's inputs was current, and
    gets today's version-2 fingerprint; a section that was already stale keeps its old value and
    so stays stale. Entries of the current version are returned unchanged."""
    if not isinstance(recorded, dict) or recorded.get("fp") == FP_VERSION:
        return recorded
    rs = recorded.get("sections") if isinstance(recorded.get("sections"), dict) else {}
    old, new = chapter_inputs(chapter, ext_idx, 1)["sections"], chapter_inputs(chapter, ext_idx)["sections"]
    out = dict(recorded)
    out["sections"] = {sid: (new[sid] if sid in old and old[sid] == fp else fp) for sid, fp in rs.items()}
    out["fp"] = FP_VERSION
    return out


def writer_config(root):
    """The settings of book.config.json a writer acts on, besides the level: the language it writes
    in, a fingerprint of audience + style notes, and what the page can render."""
    raw, _ = load_config(root)
    cfg, _ = effective_config(raw)
    style = json.dumps([cfg["content"]["audience"], cfg["content"]["style_notes"]], ensure_ascii=False)
    return {"lang": cfg["book"]["language"], "style": hashlib.sha256(style.encode("utf-8")).hexdigest()[:12],
            "katex": cfg["ui"]["features"]["math_katex_cdn"], "mermaid": cfg["ui"]["features"]["mermaid_cdn"],
            "recall": cfg["content"]["recall_questions"]}


_TEX_RE = re.compile(r"\\\((?:(?!\\\().){1,2000}?\\\)|\\\[(?:(?!\\\[).){1,4000}?\\\]", re.S)
_CODE_RE = re.compile(r"<(pre|code)\b(?![^>]*\bclass=\"[^\"]*\bmermaid\b)[^>]*>.*?</\1>", re.S | re.I)
_MERMAID_RE = re.compile(r"<pre\b[^>]*\bclass=\"[^\"]*\bmermaid\b", re.I)
_RECALL_RE = re.compile(r"<div\b[^>]*\bclass=\"[^\"]*\bcallout\b[^\"]*\brecall\b|<div\b[^>]*\bclass=\"[^\"]*\brecall\b[^\"]*\bcallout\b", re.I)


def draft_form_issues(text, wcfg, level):
    """What a draft contains that the configuration no longer supports — found in the draft itself,
    so it does not matter when or why the setting changed:
    raw_tex         \\( … \\) / \\[ … \\] although ui.features.math_katex_cdn is off (shown as raw source)
    mermaid_off     a <pre class="mermaid"> although ui.features.mermaid_cdn is off (shown as raw source)
    recall_missing  level 1 with content.recall_questions but no recall box"""
    issues = []
    prose = _CODE_RE.sub(" ", text or "")
    if not wcfg["katex"] and _TEX_RE.search(prose):
        issues.append("raw_tex")
    if not wcfg["mermaid"] and _MERMAID_RE.search(text or ""):
        issues.append("mermaid_off")
    if level == 1 and wcfg["recall"] and not _RECALL_RE.search(text or ""):
        issues.append("recall_missing")
    return issues


# What a draft may not bring along. The build owns scripts, styles and navigation; and the book's
# colours are generated per palette and theme, so a colour written into a draft (an SVG fill, an
# inline style) is the one colour that does not follow them — black ink on the dark theme.
_FOREIGN_TAG_RE = re.compile(r"<\s*(script|style|link|iframe|object|embed|base|meta|nav|form)\b", re.I)
_EVENT_ATTR_RE = re.compile(r"<[a-zA-Z][^<>]*?\s(on[a-z]{3,})\s*=", re.S)
_JS_HREF_RE = re.compile(r"\b(?:href|src|xlink:href)\s*=\s*[\"']\s*javascript:", re.I)
_NAMED_COLOURS = frozenset((
    "aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown "
    "burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan "
    "darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred "
    "darksalmon darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink "
    "deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold "
    "goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki lavender lavenderblush "
    "lawngreen lemonchiffon lightblue lightcoral lightcyan lightgoldenrodyellow lightgray lightgreen lightgrey "
    "lightpink lightsalmon lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue lightyellow "
    "lime limegreen linen magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen "
    "mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin "
    "navajowhite navy oldlace olive olivedrab orange orangered orchid palegoldenrod palegreen paleturquoise "
    "palevioletred papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red rosybrown royalblue "
    "saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue slateblue slategray slategrey snow "
    "springgreen steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen"
).split())
_COLOUR_LITERAL_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\s*\(", re.I)
_COLOUR_ATTR_RE = re.compile(r"\s(fill|stroke|color|stop-color|flood-color|lighting-color|bgcolor)\s*=\s*"
                             r"(?:\"([^\"]*)\"|'([^']*)')", re.I)
_STYLE_ATTR_RE = re.compile(r"\sstyle\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.I)
_COLOUR_PROP_RE = re.compile(r"(?:^|;)\s*(color|background(?:-color)?|fill|stroke|stop-color|flood-color|"
                             r"border(?:-(?:top|right|bottom|left|block|inline)(?:-(?:start|end))?)?(?:-color)?|"
                             r"outline(?:-color)?|text-decoration(?:-color)?|box-shadow|text-shadow|caret-color)"
                             r"\s*:\s*([^;]*)", re.I)


def _hard_colour(value):
    """The colour literal in an attribute or declaration value, or "" when the value follows the
    theme (a CSS variable, currentColor, none, a gradient reference, …)."""
    m = _COLOUR_LITERAL_RE.search(value or "")
    if m:
        return m.group(0).rstrip("( ")
    for word in re.findall(r"[A-Za-z]+", re.sub(r"var\([^)]*\)|url\([^)]*\)", " ", value or "")):
        if word.lower() in _NAMED_COLOURS:
            return word
    return ""


def draft_markup_issues(text):
    """{"foreign": [what], "colours": [what]} — markup a draft must not carry (found in the draft
    itself, comments left out): elements and attributes the build owns or that run code, and
    colours written as literals instead of the theme's CSS variables."""
    text = re.sub(r"<!--.*?-->", " ", text or "", flags=re.S)
    foreign, colours = [], []

    def note(bucket, what):
        if what not in bucket:
            bucket.append(what)

    for m in _FOREIGN_TAG_RE.finditer(text):
        note(foreign, f"<{m.group(1).lower()}>")
    for m in _EVENT_ATTR_RE.finditer(text):
        note(foreign, f"{m.group(1).lower()}= attribute")
    if _JS_HREF_RE.search(text):
        note(foreign, "javascript: link")
    for tag in re.finditer(r"<[a-zA-Z][^<>]*>", text):          # attributes only — never text, never code samples
        tag = tag.group(0)
        for m in _COLOUR_ATTR_RE.finditer(tag):
            value = m.group(2) if m.group(2) is not None else m.group(3)
            if _hard_colour(value):
                note(colours, f'{m.group(1).lower()}="{value.strip()[:40]}"')
        for m in _STYLE_ATTR_RE.finditer(tag):
            style = m.group(1) if m.group(1) is not None else m.group(2)
            for d in _COLOUR_PROP_RE.finditer(style or ""):
                if _hard_colour(d.group(2)):
                    note(colours, f"style {d.group(1).lower()}: {d.group(2).strip()[:40]}")
    return {"foreign": foreign, "colours": colours}


def compare_inputs(recorded, current, lang=None):
    """None when a draft's recorded inputs equal the current ones, else what moved. A draft that
    was written in another language than book.language is stale as a whole ("language")."""
    rs = recorded.get("sections") if isinstance(recorded.get("sections"), dict) else {}
    ro = recorded.get("order") if isinstance(recorded.get("order"), list) else list(rs)
    cs, co = current["sections"], current["order"]
    changed = [sid for sid in co if sid in rs and rs[sid] != cs[sid]]
    added = [sid for sid in co if sid not in rs]
    removed = [sid for sid in ro if sid not in cs]
    reordered = [s for s in ro if s in cs] != [s for s in co if s in rs]
    was = recorded.get("lang")
    language = f"{was} -> {lang}" if lang and isinstance(was, str) and was and was != lang else ""
    if not (changed or added or removed or reordered or language):
        return None
    out = {"changed": changed, "added": added, "removed": removed, "reordered": reordered}
    if language:
        out["language"] = language
    return out


def inputs_diff(recorded, chapter, ext_idx, lang=None):
    """compare_inputs for a ledger entry or briefing of any fingerprint version."""
    return compare_inputs(upgrade_inputs(recorded, chapter, ext_idx), chapter_inputs(chapter, ext_idx), lang)


def draft_provenance(entry, brief, sha):
    """(recorded inputs or None, whether the briefing was used) for a draft with this SHA-256.

    What a draft was written from is known in three ways: the ledger entry, while the draft is
    still the file that entry describes; the briefing, once the draft has changed since
    sync_state.py --plan handed its writer those inputs; and — for a draft edited without a
    briefing (an audit fix, a repair) — the old entry, because a targeted edit does not bring the
    rest of the chapter up to date. None: nothing is recorded (a draft from before the ledger)."""
    if entry is not None and not (isinstance(entry.get("sections"), dict) and entry["sections"]):
        entry = None                                   # unreadable entry: as if there were none
    if entry and entry.get("draft_sha") == sha:
        return entry, False
    if brief and brief.get("before") != sha:
        return brief, True
    return entry, False


def _entry(recorded, sha, chapter, ext_idx, wcfg):
    """A ledger entry in the current format from whatever was recorded (None: nothing was, so the
    draft is taken as written from the current inputs and settings)."""
    if recorded is None:
        recorded = dict(chapter_inputs(chapter, ext_idx), fp=FP_VERSION)
    recorded = upgrade_inputs(recorded, chapter, ext_idx)
    secs = recorded.get("sections") if isinstance(recorded.get("sections"), dict) else {}
    order = recorded.get("order") if isinstance(recorded.get("order"), list) else list(secs)
    return {"draft_sha": sha, "sections": dict(secs), "order": list(order), "fp": FP_VERSION,
            "lang": recorded.get("lang") if isinstance(recorded.get("lang"), str) and recorded.get("lang") else wcfg["lang"],
            "style": recorded.get("style") if isinstance(recorded.get("style"), str) and recorded.get("style") else wcfg["style"]}


def settle_ledger(root, plan, ext_idx, level):
    """Bring the ledger of one level up to date with the drafts on disk and return
    (ledger, briefed, stale): each existing draft gets an entry that says what it was written
    from (see draft_provenance; a draft nothing is recorded for is taken as written from the
    current inputs), used briefings are dropped, and stale = {chapter id: what moved} for drafts
    older than their inputs. Called by build_book.py and sync_state.py — never by a status scan."""
    ledger, briefed = load_ledger(root, level), load_briefed(root, level)
    wcfg = writer_config(root)
    new, stale, ids = {}, {}, set()
    for ch in plan["chapters"]:
        cid = ch["id"]
        if not re.fullmatch(r"\d+", cid) or cid in ids:
            continue
        ids.add(cid)
        info = draft_info(draft_path(root, cid, level))
        if not info["exists"] or info["level"] != level:
            continue
        recorded, used = draft_provenance(ledger.get(cid), briefed.get(cid), info["sha"])
        if used:
            briefed.pop(cid, None)
        new[cid] = _entry(recorded, info["sha"], ch, ext_idx, wcfg)
        diff = compare_inputs(new[cid], chapter_inputs(ch, ext_idx), wcfg["lang"])
        if diff:
            stale[cid] = diff
    briefed = {cid: b for cid, b in briefed.items() if cid in ids}
    save_ledger(root, level, new, briefed)
    return new, briefed, stale


REWRITE_REASON = "--rewrite: write the whole chapter again from the same plan and extractions"


def rewrite_pending(brief, sha):
    """True while a chapter that the user asked to have written again (build-book --rewrite) still
    is the file it was when that was asked. The request is part of the briefing, so it survives an
    interrupted run and a writer that never wrote — like every other reason to write."""
    return bool(isinstance(brief, dict) and brief.get("rewrite") and sha and brief.get("before") == sha)


def write_plan(root, plan, ext_idx, level):
    """What the writers have to do at this level, per chapter (read-only):
    {"mode": "full"} no draft yet, the draft is in another language than book.language, or the user
    asked for a rewrite that has not happened yet (rewrite_pending) ·
    {"mode": "delta", changed/added/removed/reordered, form} the draft is older than its inputs, or
    contains what the configuration no longer supports (see draft_form_issues) ·
    {"mode": "none"} the draft is current."""
    ledger, briefed = load_ledger(root, level), load_briefed(root, level)
    wcfg = writer_config(root)
    out = {}
    for ch in plan["chapters"]:
        cid = ch["id"]
        if not re.fullmatch(r"\d+", cid):
            continue
        path = draft_path(root, cid, level)
        info = draft_info(path)
        if not info["exists"] or info["level"] != level:
            out[cid] = {"mode": "full"}
            continue
        if rewrite_pending(briefed.get(cid), info["sha"]):
            out[cid] = {"mode": "full", "reason": REWRITE_REASON, "rewrite": True}
            continue
        recorded, _ = draft_provenance(ledger.get(cid), briefed.get(cid), info["sha"])
        diff = inputs_diff(recorded, ch, ext_idx, wcfg["lang"]) if recorded else None
        if diff and diff.get("language"):
            out[cid] = {"mode": "full", "reason": f"book.language changed ({diff['language']}) — write the chapter again in the new language"}
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                form = draft_form_issues(f.read(), wcfg, level)
        except OSError:
            form = []
        if diff or form:
            item = dict({"mode": "delta"}, **(diff or {"changed": [], "added": [], "removed": [], "reordered": False}))
            if form:
                item["form"] = form
            out[cid] = item
        else:
            out[cid] = {"mode": "none"}
    return out


def style_outdated(root, plan, level):
    """Chapters whose draft was written under other content.audience / content.style_notes than the
    current ones. Not stale — tone is not content — but the user is told, and decides."""
    ledger, style = load_ledger(root, level), writer_config(root)["style"]
    return [ch["id"] for ch in plan["chapters"]
            if isinstance(ledger.get(ch["id"]), dict) and ledger[ch["id"]].get("style") not in (None, "", style)
            and draft_info(draft_path(root, ch["id"], level))["exists"]]


def brief_writers(root, plan, ext_idx, level, write):
    """Record what each writer in `write` is being handed (see load_briefed)."""
    ledger, briefed = load_ledger(root, level), load_briefed(root, level)
    wcfg = writer_config(root)
    for ch in plan["chapters"]:
        cid = ch["id"]
        mode = write.get(cid, {}).get("mode")
        if mode in ("full", "delta"):
            info = draft_info(draft_path(root, cid, level))
            briefed[cid] = dict(chapter_inputs(ch, ext_idx), before=info["sha"] if info["exists"] else None,
                                fp=FP_VERSION, lang=wcfg["lang"], style=wcfg["style"])
            if write[cid].get("rewrite") and info["exists"]:
                briefed[cid]["rewrite"] = True
        elif mode == "none":
            briefed.pop(cid, None)
    save_ledger(root, level, ledger, briefed)


# ----------------------------------------------------------------------------- audits, text
def audits_dir(root):
    return os.path.join(root, ".book-state", "audits")


def audit_numbers(root):
    """(highest merged report number, highest number seen in any audit file name)."""
    merged = seen = 0
    try:
        names = os.listdir(audits_dir(root))
    except OSError:
        names = []
    for name in names:
        m = re.fullmatch(r"audit-(\d+)(\.part-[\w.-]+)?\.json", name)
        if m:
            seen = max(seen, int(m.group(1)))
            if not m.group(2):
                merged = max(merged, int(m.group(1)))
    return merged, seen


OPEN_AUDIT = ("pending_approval", "approved")


def gate_path(root):
    return os.path.join(audits_dir(root), "gate.json")


def load_gate(root):
    """{"seen": time of the last hook call, "grants": approvals the user typed, "used": approvals
    spent} — written by scripts/gate_hook.py (the plugin's UserPromptExpansion hook), which runs
    only when the USER types a kit command. No "seen": the hook has never run in this project."""
    try:
        with open(gate_path(root), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {"seen": data.get("seen") if isinstance(data.get("seen"), str) else None}
    for key in ("grants", "used"):
        v = data.get(key)
        out[key] = v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0
    return out


def save_gate(root, gate):
    os.makedirs(audits_dir(root), exist_ok=True)
    with open(gate_path(root), "w", encoding="utf-8") as f:
        json.dump(gate, f, ensure_ascii=False, indent=1)
        f.write("\n")


def finding_part(f):
    """The audit part a finding belongs to: recorded at merge time, else derived from its location."""
    if isinstance(f.get("part"), str) and f["part"]:
        return f["part"]
    mo = re.search(r"(?<![\w-])ch-(\d+)", str(f.get("location") or ""))
    return f"ch-{mo.group(1)}" if mo else "cross"


def finding_open(f):
    return isinstance(f, dict) and f.get("resolution") in (None, "open", "still_open")


def audit_reports(root):
    """[(n, report or None)] of the merged reports, ascending; None for an unreadable file."""
    out = []
    try:
        names = os.listdir(audits_dir(root))
    except OSError:
        names = []
    for name in names:
        m = re.fullmatch(r"audit-(\d+)\.json", name)
        if not m:
            continue
        try:
            with open(os.path.join(audits_dir(root), name), "r", encoding="utf-8") as f:
                rep = json.load(f)
        except (OSError, ValueError):
            rep = None
        out.append((int(m.group(1)), rep if isinstance(rep, dict) else None))
    return sorted(out, key=lambda x: x[0])


def audit_latest(root, level):
    """(n, report) of the latest report about the edition of this level, or (0, None). An audit
    examines one edition — the drafts of one level — so each level has its own line of reports;
    a report without a level (older kits) counts for every level."""
    mine = [(n, r) for n, r in audit_reports(root) if r is None or r.get("level") in (None, level)]
    return mine[-1] if mine else (0, None)


def audit_overview(root, level):
    """What a command needs to know about audits: the latest report of the configured level
    (latest/status/open), the number of the next audit, open findings per part of that report
    (prior — handed to the auditors of those parts), and open reports of other levels."""
    _, seen = audit_numbers(root)
    out = {"latest": 0, "next": seen + 1}
    n, rep = audit_latest(root, level)
    if n:
        out["latest"] = n
        out["status"] = rep.get("status") if rep else "unreadable"
        if rep:
            findings = [f for f in rep.get("findings") or [] if finding_open(f)]
            out["level"], out["open"] = rep.get("level"), len(findings)
            if rep.get("status") in OPEN_AUDIT and findings:
                parts = {}
                for f in findings:
                    parts.setdefault(finding_part(f), []).append(str(f.get("id", "?")))
                out["prior"] = {"report": f".book-state/audits/audit-{n}.json", "parts": parts}
            if rep.get("status") == "approved":
                out["hint"] = ("a fix batch was approved but did not finish — /book-kit:apply-fixes resumes it "
                               "with the findings that are still open")
    others = {}
    for m, r in audit_reports(root):
        lv = r.get("level") if r else None
        if r and lv not in (None, level) and r.get("status") in OPEN_AUDIT:
            k = sum(1 for f in r.get("findings") or [] if finding_open(f))
            if k:
                others[str(lv)] = {"latest": m, "status": r.get("status"), "open": k}
    if others:
        out["other_levels"] = others
        out["other_levels_note"] = ("open findings about another level's edition stay with that level — set "
                                    "content.level back to apply or decline them")
    return out


def norm_text(s):
    """Lower-cased text with every run of punctuation/space collapsed to one space — the form in
    which a unit's key terms are looked up in a chapter."""
    out = []
    for ch in unicodedata.normalize("NFKC", s or "").lower():
        out.append(ch if (ch.isalnum() or unicodedata.category(ch).startswith("M")) else " ")
    return " ".join("".join(out).split())


def remap_id(sid, mapping):
    """Apply a renumbering map to a dotted id: the longest mapped prefix (on a dot boundary) wins."""
    best = None
    for old in mapping:
        if sid == old or sid.startswith(old + "."):
            if best is None or len(old) > len(best):
                best = old
    return mapping[best] + sid[len(best):] if best is not None else sid


# ----------------------------------------------------------------------------- sources vs state
def source_shas(sources):
    out = {}
    for rel, full in sources.items():
        try:
            out[rel] = file_sha256(full)
        except OSError:
            out[rel] = ""
    return out


def pending_renames(shas, ext_idx):
    """[(extraction path, old source path, new source path)] — a source was moved or renamed without
    a content change: an extraction names a path that is gone, and its sha256 matches a source that
    has no extraction of its own."""
    claimed = {e["source"] for e in ext_idx.values()}
    free = {}
    for rel, sha in sorted(shas.items()):
        if rel not in claimed and sha:
            free.setdefault(sha, []).append(rel)
    out = []
    for epath, e in sorted(ext_idx.items()):
        if e["source"] and e["source"] not in shas and e["sha256"] and free.get(e["sha256"]):
            out.append((epath, e["source"], free[e["sha256"]].pop(0)))
    return out


def suggest_renumber(plan, ext_idx, renames, shas):
    """({old chapter id: new chapter id}, reason it was not derived or None).

    When the user renumbers whole source chapters (ch3 -> ch4 to make room for a new ch3) the book
    follows mechanically. A map is derived only when every moved file of a chapter went to the same
    new chapter, nothing of the chapter stayed behind and no target collides with a chapter that
    stays."""
    moves = {}
    for _, old, new in renames:
        a, b = source_chapter(old), source_chapter(new)
        if a and b and a != b:
            moves.setdefault(a, set()).add(b)
    plan_ids = [ch["id"] for ch in plan["chapters"]]
    moves = {a: bs for a, bs in moves.items() if a in plan_ids}
    if not moves:
        return {}, None
    mapping = {}
    for a, bs in moves.items():
        if len(bs) != 1:
            return {}, f"the sources of chapter {a} moved to several chapters ({', '.join(sorted(bs))})"
        mapping[a] = next(iter(bs))
    moved = {old for _, old, _ in renames}
    for e in ext_idx.values():
        if e["source"] in shas and e["source"] not in moved and e["chapter"] in mapping \
                and source_chapter(e["source"]) == e["chapter"]:
            return {}, f"only part of chapter {e['chapter']} moved ({e['source']} stayed)"
    targets = list(mapping.values())
    if len(set(targets)) != len(targets):
        return {}, "two chapters moved to the same number"
    for b in targets:
        if b in plan_ids and b not in mapping:
            return {}, f"chapter {b} already exists and is not moving"
    return mapping, None


def _slug(text):
    out = "".join(c if (c.isalnum() or c in "._" or unicodedata.category(c).startswith("M")) else "-"
                  for c in unicodedata.normalize("NFC", text.strip()))
    return re.sub(r"-{2,}", "-", out).strip("-")


def extraction_path_for(rel, taken=()):
    """Where the extraction of a source belongs — decided here, not by an agent, so a source that
    is extracted again lands on the path the plan already references:
    sources/ch2/2.1 deck.pptx -> ch2/2.1-deck.pptx.md   (Markdown/text sources drop the extension).

    taken: extraction paths that already belong to another source. Two sources must never share a
    path (the second analyst would overwrite the first), so a clash is resolved here: first by
    keeping the extension (2.1-notes.txt.md), then by the sub-folders (lecture-slides.pdf.md),
    then by a counter."""
    parts = rel.replace("\\", "/").split("/")
    name = parts[-1]
    stem, ext = os.path.splitext(name)
    slug = _slug(stem) or "source"
    full = slug + ext.lower()
    base = full if ext.lower() not in (".md", ".markdown", ".txt") else slug
    chapter = source_chapter(rel)
    folder = f"ch{chapter}" if chapter else "misc"
    inner = parts[1:-1] if parts and parts[0] == "sources" else parts[:-1]
    sub = _slug("-".join(inner[1:] if chapter and len(inner) > 0 else inner))
    candidates = [base] + ([f"{sub}-{base}"] if sub else []) + [full] + ([f"{sub}-{full}"] if sub else [])
    for cand in candidates:
        path = f"{folder}/{cand}.md"
        if path not in taken:
            return path
    i = 2
    while f"{folder}/{full}-{i}.md" in taken:
        i += 1
    return f"{folder}/{full}-{i}.md"


# ----------------------------------------------------------------------------- unit sources
# For every unit that locates one run of lines (text, .docx) or slides (.pptx), the kit remembers a
# hash of exactly that part of the file the analyst read. When the source changes, the units whose
# part is still in the new file, byte for byte, are proven unchanged without any model: the analyst
# copies them and reads only the rest, and the sections that cover them are not rewritten.
def unit_sources_path(root):
    return os.path.join(root, ".book-state", "unit-sources.json")


def load_unit_sources(root):
    try:
        with open(unit_sources_path(root), "r", encoding="utf-8") as f:
            data = json.load(f)
        ext = data.get("extractions") if isinstance(data, dict) else None
        return {k: v for k, v in ext.items() if isinstance(v, dict)} if isinstance(ext, dict) else {}
    except (OSError, ValueError):
        return {}


def _digest(text, n=16):
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:n]


UNIT_SOURCES_VERSION = 2          # 2: the kit's own header lines of a pre-extracted copy are not content
_KIT_HEADER_RE = re.compile(r"<!--\s*source:.*\bsha256:|>\s*extractor notes:|#\s+(?:DOCX|PPTX) extraction:")


def kit_header_lines(lines):
    """Numbers of the lines extract_office.py itself writes at the top of a pre-extracted copy (the
    comment with the source's SHA-256, the extractor notes, the title). They change with every
    version of the source and are nothing an analyst has to read or a unit could be about."""
    return {n for n, line in enumerate(lines[:8], 1) if _KIT_HEADER_RE.match(line)}


def source_blocks(root, source_rel, sha):
    """(kind, {index: digest}, set of indices with content) of the file an analyst reads for a
    source: "l" — the lines of a text source or of the pre-extracted markdown of a .docx;
    "s" — the slides of the pre-extracted markdown of a .pptx (the "## Slide N" heading itself is
    left out, so a slide that only moved keeps its digest). (None, {}, set()) for everything else."""
    ext = os.path.splitext(source_rel)[1].lower()
    if ext not in OFFICE_EXT and ext not in TEXT_EXT:
        return None, {}, set()
    target = read_target(root, source_rel, sha)
    try:
        with open(target, "rb") as f:
            lines = f.read().decode("utf-8", "replace").split("\n")
    except (OSError, TypeError):
        return None, {}, set()
    if ext == ".pptx":
        slides, cur = {}, None
        for line in lines:
            m = re.match(r"##\s+Slide\s+(\d+)\b", line)
            if m:
                cur = int(m.group(1))
                slides[cur] = []
            elif cur is not None:
                slides[cur].append(line.rstrip())
        return "s", {n: _digest("\n".join(body).strip()) for n, body in slides.items()}, set(slides)
    own = os.path.abspath(target) != os.path.abspath(os.path.join(root, *source_rel.split("/")))
    header = kit_header_lines(lines) if own else set()
    blocks = {n: _digest("" if n in header else line.rstrip(), 10) for n, line in enumerate(lines, 1)}
    return "l", blocks, {n for n, line in enumerate(lines, 1) if line.strip() and n not in header}


def _unit_range(unit, kind):
    nums = unit["line_locator"] if kind == "l" else unit["locator"]
    if not nums or max(nums) - min(nums) + 1 != len(nums):
        return None
    return min(nums), max(nums)


def refresh_unit_sources(root, sources, shas, ext_idx):
    """Record, for every extraction that is current with its source, what each unit was read from
    and a digest of what it says. Entries of extractions that wait for a re-extraction are kept —
    they are what the new version is compared with. Zero tokens; called by sync_state.py."""
    store, changed = load_unit_sources(root), False
    for epath in [k for k in store if k not in ext_idx]:
        del store[epath]
        changed = True
    for epath, e in ext_idx.items():
        src = e["source"]
        if src not in sources or not e["sha256"] or e["sha256"] != shas.get(src) or e["incomplete"]:
            continue
        fp = {str(n): _digest(u["fp_text"], 12) for n, u in e["units"].items()}
        old = store.get(epath)
        if old and old.get("sha256") == e["sha256"] and old.get("fp") == fp and old.get("v") == UNIT_SOURCES_VERSION:
            continue
        kind, blocks, _ = source_blocks(root, src, e["sha256"])
        units = {}
        for n, u in e["units"].items():
            r = _unit_range(u, kind) if kind else None
            if r and all(i in blocks for i in range(r[0], r[1] + 1)):
                units[str(n)] = [r[0], r[1], _digest("".join(blocks[i] for i in range(r[0], r[1] + 1))), blocks[r[0]]]
        store[epath] = {"sha256": e["sha256"], "kind": kind, "units": units, "fp": fp, "v": UNIT_SOURCES_VERSION}
        changed = True
    if changed:
        os.makedirs(os.path.dirname(unit_sources_path(root)), exist_ok=True)
        with open(unit_sources_path(root), "w", encoding="utf-8") as f:
            json.dump({"kit": KIT_VERSION, "extractions": dict(sorted(store.items()))}, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
    return store


def unchanged_units(root, source_rel, new_sha, entry):
    """Which units of the previous extraction are proven unchanged in the new version of a source:
    {"keep": [{"unit": 3, "at": "l.12-42"}], "read_ranges": ["l.1-11", "l.43-60"]} — the part each
    kept unit was read from is in the new file byte for byte ("at": where it is now); "read_ranges"
    is everything else that has content. None when nothing can be proven (a PDF, no line/slide
    locators, or nothing kept). The key is not "read": that one names the FILE an analyst opens."""
    if not isinstance(entry, dict) or not isinstance(entry.get("units"), dict) or not entry.get("kind"):
        return None
    kind, blocks, filled = source_blocks(root, source_rel, new_sha)
    if kind != entry["kind"] or not blocks:
        return None
    starts = {}
    for i, d in blocks.items():
        starts.setdefault(d, []).append(i)
    keep, covered, cursor = [], set(), 0
    for n, rec in sorted(entry["units"].items(), key=lambda kv: (kv[1][0] if isinstance(kv[1], list) and kv[1] else 0)):
        if not (isinstance(rec, list) and len(rec) == 4):
            continue
        a, b, digest, first = rec
        length = b - a + 1
        for start in sorted(starts.get(first, [])):
            if start <= cursor:
                continue
            rng = range(start, start + length)
            if all(i in blocks for i in rng) and _digest("".join(blocks[i] for i in rng)) == digest:
                keep.append({"unit": int(n), "at": f"{kind}.{start}" + (f"-{start + length - 1}" if length > 1 else "")})
                covered.update(rng)
                cursor = start + length - 1
                break
    if not keep:
        return None
    rest = sorted(i for i in filled if i not in covered)
    return {"keep": sorted(keep, key=lambda k: k["unit"]),
            "read_ranges": [f"{kind}.{x}" for x in _all_ranges(rest, bridge=lambda i: i not in filled and i not in covered)]}


def _all_ranges(nums, bridge=None):
    """[5, 7, 9, 13] -> ["5", "7", "9", "13"]; with bridge (index -> bool) two numbers also join
    when everything between them may be bridged — blank lines that belong to no kept unit — so a
    changed passage is one range ("5-9") instead of one entry per line."""
    out, start, prev = [], None, None
    for n in nums:
        if start is None:
            start = prev = n
        elif n == prev + 1 or (bridge and all(bridge(i) for i in range(prev + 1, n))):
            prev = n
        else:
            out.append(f"{start}-{prev}" if prev != start else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}-{prev}" if prev != start else str(start))
    return out


def unit_map(old_entry, e):
    """How the units of a re-extracted source relate to the units of the previous extraction:
    {"kept": [(old, new)] — say exactly what they said (matched in order);
     "replaced": [(old, new)] — changed in place: between the same two kept neighbours exactly as
                 many old units disappeared as new ones appeared, so each new one takes the place
                 of the old one (and inherits its place in the plan);
     "new": [n] — new units without a predecessor; "gone": [o] — old units without a successor}."""
    old = old_entry.get("fp") if isinstance(old_entry, dict) and isinstance(old_entry.get("fp"), dict) else {}
    old_nums = sorted(int(o) for o in old if str(o).isdigit())
    kept, used, last = [], set(), 0
    for n in sorted(e["units"]):
        d = _digest(e["units"][n]["fp_text"], 12)
        match = next((o for o in old_nums if o > last and old[str(o)] == d and o not in used), None)
        if match is not None:
            kept.append((match, n))
            used.add(match)
            last = match
    kept_new = {n for _, n in kept}
    replaced, new_units, gone = [], [], []
    bounds = [(0, 0)] + kept + [(float("inf"), float("inf"))]
    for (o_lo, n_lo), (o_hi, n_hi) in zip(bounds, bounds[1:]):
        g = [o for o in old_nums if o_lo < o < o_hi and o not in used]
        nw = [n for n in sorted(e["units"]) if n_lo < n < n_hi and n not in kept_new]
        if g and len(g) == len(nw):
            replaced += list(zip(g, nw))
        else:
            gone += g
            new_units += nw
    return {"kept": kept, "replaced": replaced, "new": new_units, "gone": gone}


def _unit_runs(pairs):
    """[(old, new)] -> ["U3-U9 -> U4-U10", ...] for the pairs whose number changed."""
    out, run = [], None
    for o, n in list(pairs) + [(None, None)]:
        if run and o is not None and o == run[1] + 1 and n == run[3] + 1:
            run[1], run[3] = o, n
            continue
        if run and run[0] != run[2]:
            out.append((f"U{run[0]}-U{run[1]}" if run[1] != run[0] else f"U{run[0]}") + " -> "
                       + (f"U{run[2]}-U{run[3]}" if run[3] != run[2] else f"U{run[2]}"))
        run = [o, o, n, n] if o is not None else None
    return out


def reextraction_report(old_entry, e):
    """After a source was extracted again: what happened to its units — {"units", "kept", "moved":
    ["U3-U9 -> U4-U10"] (the same content under new numbers), "replaced": ["U3 -> U4"] (content
    changed in place), "new": [7], "gone": [12]}. sync_state.py applies "moved" and "replaced" to
    the plan itself; "new" and "gone" are what the architect decides about."""
    m = unit_map(old_entry, e)
    return {"units": len(e["units"]), "kept": len(m["kept"]), "moved": _unit_runs(m["kept"]),
            "replaced": [f"U{o} -> U{n}" for o, n in m["replaced"]], "new": m["new"], "gone": m["gone"]}


def office_recovered(info, since=1):
    """How much content the current office extractor reads that extractor version `since` dropped."""
    return sum(info.get(k, 0) for version, keys in RECOVERED_SINCE.items() if version > since
               for k in keys if isinstance(info.get(k, 0), int))


def extraction_needs(root, sources, shas, ext_idx):
    """What still has to be read. Returns a dict:
    extract   [{"path", "reason", "chapter", "extraction", "read", "pages"|"slides"|"lines"}]  sources without
              a current extraction (reason: new | changed | incomplete | truncated | retry | office_recovered |
              long_lines). A "truncated" entry carries "resume_after" — where its units stop.
              "read" is the file to open instead of the source (a pre-extracted copy); a changed source
              may also carry "keep" and "read_ranges" (see unchanged_units) — two keys, never one
    unread_visuals  .pptx/.docx with pictures or embedded objects the kit cannot read
    errors    sources whose extraction records a read error
    unstamped extractions waiting for sync_state.py --stamp
    refresh   .pptx/.docx whose pre-extraction is missing or was made by an older extractor
    renames   pending same-content moves; stale: extractions whose source is gone"""
    by_source = {}
    for epath, e in ext_idx.items():
        by_source.setdefault(e["source"], e)
    renames = pending_renames(shas, ext_idx)
    renamed_to = {new for _, _, new in renames}
    out = {"extract": [], "errors": [], "unstamped": [], "refresh": [], "renames": renames, "stale": [],
           "unread_visuals": []}
    all_shas = set(shas.values())
    for epath, e in sorted(ext_idx.items()):
        if e["source"] and e["source"] not in shas and not (e["sha256"] and e["sha256"] in all_shas):
            out["stale"].append(epath)
    taken = set(ext_idx)                    # extraction paths in use: no two sources may share one
    unit_store = load_unit_sources(root)
    for rel in sorted(sources):
        ext = os.path.splitext(rel)[1].lower()
        sha = shas[rel]
        pre = ext in OFFICE_EXT          # needs a pre-extracted copy: office files, long-lined text files
        if ext in TEXT_EXT and sha:
            pre = text_shape(sources[rel])[2] > LONG_LINE
        cache = office_cache_info(root, sha) if pre and sha else None
        if pre and (cache is None or cache.get("extractor", 1) < OFFICE_EXTRACTOR):
            out["refresh"].append(rel)
        if ext in OFFICE_EXT and cache and (cache.get("pictures") or cache.get("ole")):
            out["unread_visuals"].append({"path": rel, "pictures": cache.get("pictures", 0), "objects": cache.get("ole", 0)})
        e = by_source.get(rel)
        reason = None
        if e is None:
            if rel in renamed_to:
                continue
            reason = "new"
        elif e["incomplete"]:
            reason = "incomplete"
        elif not e["sha256"]:
            out["unstamped"].append(e["rel"])
            continue
        elif e["sha256"] != sha:
            reason = "changed"
        elif truncated_after(root, e):
            # stamped, but the units stop before the source does (an analyst that gave up, a run
            # that stopped at "problems remain"): the rest is still to be read — never planned around
            reason = "truncated"
        elif e["error"] or e["count"] == 0:
            # the same unreadable file is not tried again — unless its pre-extraction works now
            if ext in OFFICE_EXT and cache and cache.get("extractor", 1) >= OFFICE_EXTRACTOR:
                reason = "retry"
            else:
                out["errors"].append(rel)
                continue
        elif pre and (e["extractor"] or 1) < OFFICE_EXTRACTOR and cache \
                and cache.get("extractor", 1) >= OFFICE_EXTRACTOR and office_recovered(cache, e["extractor"] or 1) > 0:
            # read before the kit kept this content (or before it wrapped lines the reading tool may cut)
            reason = "office_recovered" if ext in OFFICE_EXT else "long_lines"
        if reason:
            epath = e["rel"] if e else extraction_path_for(rel, taken)
            taken.add(epath)
            item = {"path": rel, "reason": reason, "chapter": source_chapter(rel),
                    "extraction": ".book-state/extractions/" + epath}
            if ext == ".pdf":
                item["pages"] = pdf_page_count(sources[rel])
            elif pre and cache and cache.get("extractor", 1) >= OFFICE_EXTRACTOR:
                # the analyst opens the pre-extracted copy, never the binary (or the over-long lines)
                item["read"] = ".book-state/extracted-office/" + sha[:12] + ".md"
                if isinstance(cache.get("slides"), int):
                    item["slides"] = cache["slides"]
            if ext == ".docx" or ext in TEXT_EXT:
                n = text_shape(read_target(root, rel, sha))[0]
                if n:
                    item["lines"] = n
            if reason == "truncated":
                # same source version: the notes at this path are right as far as they go
                item["previous_units"] = e["count"]
                item["resume_after"] = truncated_after(root, e)
            if reason == "changed" and e["count"] and not e["error"]:
                # the extraction at this path was written from the previous version of the source
                item["previous_units"] = e["count"]
                old = unit_store.get(e["rel"])
                same = unchanged_units(root, rel, sha, old) if old and old.get("sha256") == e["sha256"] else None
                if same:
                    item.update(same)
            out["extract"].append(item)
    return out


def replan_path(root):
    return os.path.join(root, ".book-state", "plan", "reextracted.json")


def load_replan(root):
    """{extraction path: record} — what a re-extraction left for the architect and the plan has not
    answered yet (written by sync_state.py; see apply_reextractions there)."""
    try:
        with open(replan_path(root), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    ext = data.get("extractions") if isinstance(data, dict) else None
    return {k: v for k, v in ext.items() if isinstance(v, dict)} if isinstance(ext, dict) else {}


def replan_open(root, ext_idx, plan=None):
    """The open part of that record, for the scan and the validator: [{"extraction", "new": [n],
    "replaced": ["U2 -> U2 (section 4.2)"], "emptied": [ids]}] for extractions that still are the
    version the record was made for. With the (normalised) plan, what the plan has answered since
    — a new unit that is listed now, an emptied section that has units again — is left out."""
    out = []
    placed, filled = set(), set()
    ids = [s["id"] for ch in (plan or {}).get("chapters", []) for s in ch["sections"]]
    for ch in (plan or {}).get("chapters", []):
        for s in ch["sections"]:
            for ref in s["covers"] + s["merged"]:
                try:
                    path, nums = expand_ref(ref)
                except ValueError:
                    continue
                placed.update((path, n) for n in nums)
                filled.add(s["id"])
    for entry in (plan or {}).get("omitted", []):
        try:
            path, nums = expand_ref(entry["ref"])
        except (ValueError, KeyError):
            continue
        placed.update((path, n) for n in nums)
    for epath, rec in sorted(load_replan(root).items()):
        e = ext_idx.get(epath)
        if e is None or rec.get("sha256") != e["sha256"]:
            continue
        item = {"extraction": epath}
        new = [x["unit"] for x in rec.get("new") or [] if isinstance(x, dict) and isinstance(x.get("unit"), int)
               and (epath, x["unit"]) not in placed]
        replaced = [f"U{r['old']} -> U{r['new']} ({r.get('in', 'no section')})"
                    for r in ([] if rec.get("reviewed") else rec.get("replaced") or [])
                    if isinstance(r, dict) and "old" in r and "new" in r]
        if new:
            item["new"] = new
        if replaced:
            item["replaced"] = replaced
        emptied = [sid for sid in rec.get("emptied") or [] if sid not in filled
                   and (plan is None or (sid in ids and not any(x.startswith(sid + ".") for x in ids)))]
        if emptied:
            item["emptied"] = emptied
        if len(item) > 1:
            out.append(item)
    return out


# ----------------------------------------------------------------------------- plan integrity
PAGE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.html")


def check_plan(plan):
    """(problems, warnings, info) for a normalised plan.
    info: "pages" {chapter id: page}, "sections" {section id: {"page", "title", "chapter"}} in plan
    order, "supplements" {chapter id: {supplement id: section id}}, "order" {chapter id: [ids]}."""
    problems, warnings = [], []
    pages, sections, supplements, order = {}, {}, {}, {}
    seen_supp = set()

    def fail(code, detail):
        problems.append({"code": code, "detail": detail})

    for ch in plan["chapters"]:
        cid = ch["id"]
        if not re.fullmatch(r"\d+", cid):
            fail("plan.chapter_id", f"bad top-level chapter id: {cid!r}")
            continue
        if cid in pages:
            fail("plan.chapter_dup", f"duplicate chapter id: {cid}")
            continue
        page = ch["page"] or f"ch-{cid}.html"
        if not PAGE_RE.fullmatch(page) or page == "index.html":
            fail("plan.page", f"chapter {cid}: page {page!r} is not a plain .html file name")
        if page in pages.values():
            fail("plan.page_dup", f"page reused: {page}")
        pages[cid] = page
        ids = []
        for sec in ch["sections"]:
            sid = sec["id"]
            if not _ID_RE.fullmatch(sid):
                fail("plan.section_id", f"bad section id: {sid!r}")
                continue
            if sid in sections:
                fail("plan.id_dup", f"duplicate section id: {sid}")
                continue
            if sid.split(".")[0] != cid:
                fail("plan.id_scope", f"section {sid} listed under chapter {cid}")
            sections[sid] = {"page": page, "title": sec["title"], "chapter": cid}
            ids.append(sid)
            for sp in sec["supplements"]:
                if not sp["id"]:
                    fail("plan.supplement_id", f"section {sid}: a supplement has no id")
                    continue
                if sp["id"] in seen_supp:
                    fail("plan.supplement_dup", f"duplicate supplement id: {sp['id']}")
                seen_supp.add(sp["id"])
                supplements.setdefault(cid, {})[sp["id"]] = sid
        if not ids:
            fail("plan.sections", f"chapter {cid} has no sections")
        if cid in ids and len(ids) > 1:
            fail("plan.dotless_mix", f"chapter {cid}: dotless section {cid!r} mixed with dotted siblings")
        order[cid] = ids
        last = {}
        for sid in ids:                                   # siblings should count upwards in plan order
            parent, _, leaf = sid.rpartition(".")
            if parent in last and int(leaf) < last[parent]:
                warnings.append({"code": "plan.order",
                                 "detail": f"chapter {cid}: section {sid} comes after {parent}.{last[parent]} — "
                                           "numbers are out of reading order (request a renumber, see the architect rules)"})
            last[parent] = max(last.get(parent, 0), int(leaf))
    for sid in sections:
        parent = sid.rpartition(".")[0]
        if parent and parent not in sections and parent not in pages:
            fail("plan.orphan", f"section {sid} has no parent {parent}")
    if not pages and not problems:
        fail("plan.empty", "the plan has no chapters")
    return problems, warnings, {"pages": pages, "sections": sections, "supplements": supplements,
                                "order": order, "supplement_count": len(seen_supp)}
