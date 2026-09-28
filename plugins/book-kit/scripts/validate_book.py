#!/usr/bin/env python3
"""Mechanical validation of the built book. No LLM judgment — structure only.

Checks: plan integrity, coverage completeness (every extraction unit resolved,
zero unresolved), pages/anchors exist per plan, TOC completeness on every page,
internal links resolve, no unfilled {{PLACEHOLDER}}s (matched against the
placeholder names present in templates/*.html, so arbitrary {{UPPERCASE}}
in learner content — e.g. Mustache samples — does not trip it), required UI markers
(#toc, #progress, #theme-toggle, <html lang> matching book.config.json
book.language — default "th"), and per-source extraction presence.
Extraction errors (units: 0 / "# Error" section) are reported as non-blocking
warnings — the auditor must raise a finding for each. An omitted_justified
reason that cites brevity/length/token-saving instead of a semantic
justification warns as coverage.brevity_reason (non-blocking heuristic, EN+TH
keywords; req 2: concise but complete) — the auditor judges each hit. Stale extractions (their
source was removed; pending renames are sha-protected) warn as extraction.stale
and are excluded from the coverage sweep; coverage entries still pointing at
one fail (coverage.stale_ref). A dotless section id mixed with dotted siblings
in the same chapter fails (plan.dotless_mix).

Usage (run from the book project root; the project is the current directory,
or pass --root <dir>):
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_book.py" [--templates <dir>]
Templates (for the placeholder-name check) resolve as: --templates, else a
project-local templates/ override, else the plugin's own templates/ next to
this script. Writes .book-state/validate-report.json; exits 0 on PASS, 1 on FAIL,
2 when the directory is not a book project.
"""
import hashlib
import json
import os
import re
import sys
from html.parser import HTMLParser

# Project resolution (plugin edition): the book project is the current working
# directory (or --root / BOOK_ROOT). The script lives in the plugin, so the
# plugin's templates/ is found relative to __file__ and a project-local
# templates/ takes precedence. Globals are assigned by configure().
ROOT = BOOK = STATE = PLAN = COVERAGE = EXTRACTIONS = REPORT = TEMPLATES = None
PLUGIN_TEMPLATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")


def resolve_root(explicit=None) -> str:
    return os.path.abspath(explicit or os.environ.get("BOOK_ROOT") or os.getcwd())


def resolve_templates(root: str, explicit=None) -> str:
    if explicit:
        return os.path.abspath(explicit)
    local = os.path.join(root, "templates")
    return local if os.path.isdir(local) else PLUGIN_TEMPLATES


def configure(root: str, templates: str) -> None:
    global ROOT, BOOK, STATE, PLAN, COVERAGE, EXTRACTIONS, REPORT, TEMPLATES
    ROOT = root
    BOOK = os.path.join(ROOT, "book")
    STATE = os.path.join(ROOT, ".book-state")
    PLAN = os.path.join(STATE, "plan", "book-plan.json")
    COVERAGE = os.path.join(STATE, "plan", "coverage.json")
    EXTRACTIONS = os.path.join(STATE, "extractions")
    REPORT = os.path.join(STATE, "validate-report.json")
    TEMPLATES = templates


def require_book_project(root: str) -> None:
    if os.path.isfile(os.path.join(root, "book.config.json")) or os.path.isdir(os.path.join(root, "sources")):
        return
    print(json.dumps({"error": "not a book project", "root": root,
                      "hint": "run from the project root (needs book.config.json or sources/), "
                              "pass --root <dir>, or run /book-kit:init to create one"},
                     ensure_ascii=False), file=sys.stderr)
    sys.exit(2)
VALID_STATES = {"represented", "merged", "omitted_justified", "administrative", "unresolved"}
# Heuristic (EN + TH): an omitted_justified reason that justifies the omission
# by brevity/length/token-saving rather than semantics (duplicate meaning,
# administrative, out of teaching scope). Non-blocking — the auditor judges
# each hit (req 2: concise but complete). Deliberately narrow: bare "token"/
# "short" are NOT matched (e.g. "tokenization out of scope" must not trip it).
BREVITY_REASON_RE = re.compile("|".join([
    r"brevity", r"concis", r"shorten", r"too long", r"for length",
    r"reduce length", r"keep(?:ing)?\b[^.]{0,24}\bshort\b", r"kept short",
    r"save space", r"save tokens", r"token (?:budget|limit|cost)",
    r"word count", r"page limit",
    r"กระชับ", r"ยาวเกิน", r"ลดความยาว",
    r"เพื่อประหยัด", r"ประหยัดโทเค็น", r"ประหยัดพื้นที่",
]), re.IGNORECASE)
IGNORE_NAMES = {".gitkeep", ".DS_Store", "Thumbs.db"}
IGNORE_EXT = {".tmp", ".part", ".crdownload"}  # keep in sync with scan_sources.py
# HTML void elements never emit an endtag event; pushing them would desync
# the #toc open-tag stack (e.g. <input id="toc-filter">) and leak page links
# into toc_hrefs.
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "param", "source", "track", "wbr"}


class PageScan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.hrefs = set(), []
        self.lang = None
        self.has_title = False
        self.toc_hrefs = set()
        # Open-tag stack inside #toc. html.parser reports tags verbatim, so an
        # omitted optional close (e.g. an unclosed <li>) must be healed here
        # via implied closes — otherwise depth tracking desyncs and every link
        # on the rest of the page leaks into toc_hrefs, silently turning the
        # toc.missing check into a vacuous pass. Mismatches are flagged so the
        # validator can warn the builder.
        self._toc_stack = None      # None = outside #toc
        self.toc_malformed = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "html":
            self.lang = a.get("lang")
        if tag == "title":
            self.has_title = True
        if self._toc_stack is None and a.get("id") == "toc":
            self._toc_stack = []
        if self._toc_stack is not None:
            if tag == "a" and "href" in a:
                self.toc_hrefs.add(a["href"])
            if tag not in VOID_TAGS:
                self._toc_stack.append(tag)
        if tag == "a" and "href" in a:
            self.hrefs.append(a["href"])

    def handle_endtag(self, tag):
        if self._toc_stack is None or tag in VOID_TAGS:
            return
        if tag in self._toc_stack:
            if self._toc_stack[-1] != tag:
                self.toc_malformed = True   # implied close(s) applied
            while self._toc_stack and self._toc_stack.pop() != tag:
                pass
        else:
            self.toc_malformed = True       # stray close inside #toc
        if not self._toc_stack:
            self._toc_stack = None          # nav closed — #toc ended


def fail(problems, code, detail):
    problems.append({"code": code, "detail": detail})


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path, problems, code):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        fail(problems, code, f"missing file: {os.path.relpath(path, ROOT)}")
    except json.JSONDecodeError as e:
        fail(problems, code, f"invalid JSON in {os.path.relpath(path, ROOT)}: {e}")
    return None


def walk_sources():
    src = os.path.join(ROOT, "sources")
    out = []
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name in IGNORE_NAMES or name.startswith(".") or name.lower() == "readme.md":
                continue
            if os.path.splitext(name)[1].lower() in IGNORE_EXT:
                continue
            out.append(os.path.relpath(os.path.join(dirpath, name), ROOT).replace(os.sep, "/"))
    return sorted(out)


def placeholder_regex():
    """The book.placeholder check matches only the placeholder names that
    actually occur in templates/*.html, so learner content that legitimately
    contains {{UPPERCASE}} tokens (e.g. a code sample teaching Mustache /
    Handlebars syntax) cannot false-positive a hard FAIL. Self-maintaining:
    new placeholders added to templates are picked up automatically. Falls
    back to the generic pattern if no templates are readable (v9.6)."""
    names = set()
    tdir = TEMPLATES
    try:
        for name in os.listdir(tdir):
            if name.endswith(".html"):
                with open(os.path.join(tdir, name), "r", encoding="utf-8") as f:
                    names.update(re.findall(r"\{\{([A-Z_]+)\}\}", f.read()))
    except OSError:
        pass
    if names:
        return re.compile(r"\{\{(?:" + "|".join(sorted(names)) + r")\}\}")
    return re.compile(r"\{\{[A-Z_]+\}\}")


def extraction_index(problems):
    """path(rel to extractions/) -> {source, units}; parsed from frontmatter."""
    idx = {}
    if not os.path.isdir(EXTRACTIONS):
        return idx
    for dirpath, _, filenames in os.walk(EXTRACTIONS):
        for name in filenames:
            if not name.endswith(".md"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, EXTRACTIONS).replace(os.sep, "/")
            with open(full, "r", encoding="utf-8") as f:
                head = f.read(4000)
            src = re.search(r"^source:\s*(.+)$", head, re.M)
            units = re.search(r"^units:\s*(\d+)", head, re.M)
            if not src or not units:
                fail(problems, "extraction.frontmatter",
                     f"{rel}: missing 'source:' or 'units:' in frontmatter")
                continue
            sha = re.search(r"^sha256:\s*([0-9a-fA-F]{64})\b", head, re.M)
            idx[rel] = {"source": src.group(1).strip(), "units": int(units.group(1)),
                        "sha256": sha.group(1).lower() if sha else "",
                        "error": bool(re.search(r"^#\s*Error\b", head, re.M))}
    return idx


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", help="book project root (default: current directory or $BOOK_ROOT)")
    ap.add_argument("--templates", help="templates dir for the placeholder-name check "
                                        "(default: <root>/templates if present, else the plugin templates)")
    args = ap.parse_args()
    root = resolve_root(args.root)
    require_book_project(root)
    configure(root, resolve_templates(root, args.templates))

    problems, warnings, stats = [], [], {}
    stats["root"] = ROOT
    stats["templates"] = TEMPLATES
    if not os.path.isdir(TEMPLATES):
        warnings.append({"code": "templates.missing",
                         "detail": f"templates dir not found: {TEMPLATES} — placeholder check falls back "
                                   "to the generic {{UPPERCASE}} pattern"})

    cfg = {}
    try:
        with open(os.path.join(ROOT, "book.config.json"), "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        warnings.append({"code": "config.unreadable",
                         "detail": f"book.config.json not readable ({e}); using defaults"})
    expected_lang = ((cfg.get("book") or {}).get("language") or "th").strip() or "th"

    ph_re = placeholder_regex()
    plan = load_json(PLAN, problems, "plan.missing")
    coverage = load_json(COVERAGE, problems, "coverage.missing")
    ext_idx = extraction_index(problems)
    sources = walk_sources()
    stats["sources"] = len(sources)
    stats["extractions"] = len(ext_idx)

    # stale extractions: source removed (path gone AND content sha absent from
    # current sources — a renamed-but-not-yet-remapped extraction keeps its sha
    # and is protected). Agents cannot delete files; scripts/prune_state.py can.
    src_set = set(sources)
    _sha_cache = {"done": False, "shas": set()}

    def current_source_shas():
        if not _sha_cache["done"]:
            for s in sources:
                try:
                    _sha_cache["shas"].add(file_sha256(os.path.join(ROOT, s)))
                except OSError:
                    pass
            _sha_cache["done"] = True
        return _sha_cache["shas"]

    stale = set()
    for epath, meta in sorted(ext_idx.items()):
        if meta["source"] in src_set:
            continue
        if meta.get("sha256") and meta["sha256"] in current_source_shas():
            continue  # pending rename, not stale
        stale.add(epath)
        warnings.append({"code": "extraction.stale",
                         "detail": f"{epath}: source {meta['source']!r} no longer exists — "
                                   "run `python scripts/prune_state.py` to delete stale state"})
    stats["staleExtractions"] = len(stale)

    # extraction errors: source unreadable -> no units, no coverage possible.
    # Non-blocking by design (the build may proceed), but the auditor MUST
    # raise a finding for each — this is the "never silently skip" mechanism.
    for epath, meta in sorted(ext_idx.items()):
        if epath in stale:
            continue
        if meta["units"] == 0 or meta.get("error"):
            warnings.append({"code": "extraction.error",
                             "detail": f"{epath}: source not (fully) extracted — "
                                       "coverage unknown; auditor must raise a finding"})

    # 1) every current source has an extraction
    extracted_sources = {meta["source"] for meta in ext_idx.values()}
    for s in sources:
        if s not in extracted_sources:
            fail(problems, "extraction.missing", f"no extraction found for {s}")

    # 2) plan integrity
    sections = {}   # id -> {"page": ..., "title": ...}
    pages = {}      # chapter top id -> page filename
    if plan:
        for ch in plan.get("chapters", []):
            cid, page = str(ch.get("id", "")), ch.get("page", "")
            if not cid or not re.fullmatch(r"\d+", cid):
                fail(problems, "plan.chapter_id", f"bad top-level chapter id: {cid!r}")
                continue
            if cid in pages:
                fail(problems, "plan.chapter_dup", f"duplicate chapter id: {cid}")
                continue
            if page in pages.values():
                fail(problems, "plan.page_dup", f"page reused: {page}")
            pages[cid] = page
            ch_sids = []
            for sec in ch.get("sections", []):
                sid = str(sec.get("id", ""))
                if not re.fullmatch(r"\d+(\.\d+)*", sid):
                    fail(problems, "plan.section_id", f"bad section id: {sid!r}")
                    continue
                if sid in sections:
                    fail(problems, "plan.id_dup", f"duplicate section id: {sid}")
                if sid.split(".")[0] != cid:
                    fail(problems, "plan.id_scope", f"section {sid} listed under chapter {cid}")
                sections[sid] = {"page": page, "title": sec.get("title_th", "")}
                ch_sids.append(sid)
            if cid in ch_sids and len(ch_sids) > 1:
                fail(problems, "plan.dotless_mix",
                     f"chapter {cid}: dotless section {cid!r} mixed with dotted siblings")
        for sid in sections:
            parts = sid.split(".")
            if len(parts) > 1:
                parent = ".".join(parts[:-1])
                if parent not in sections and parent not in pages:
                    fail(problems, "plan.orphan", f"section {sid} has no parent {parent}")
    stats["chapters"] = len(pages)
    stats["sections"] = len(sections)

    # 3) coverage completeness + honesty of refs
    if coverage is not None:
        unresolved = 0
        for ref, entry in coverage.items():
            state = entry.get("state")
            if state not in VALID_STATES:
                fail(problems, "coverage.state", f"{ref}: invalid state {state!r}")
                continue
            if state == "unresolved":
                unresolved += 1
            if state == "omitted_justified":
                reason = entry.get("reason") or ""
                if not reason:
                    fail(problems, "coverage.reason", f"{ref}: omitted_justified without reason")
                elif BREVITY_REASON_RE.search(reason):
                    warnings.append({"code": "coverage.brevity_reason",
                                     "detail": f"{ref}: omission reason cites brevity/length "
                                               f"({reason!r}) — not a valid justification "
                                               "(req 2: concise but complete); "
                                               "auditor must judge"})
            if state == "represented" and entry.get("section") not in sections:
                fail(problems, "coverage.section", f"{ref}: unknown section {entry.get('section')!r}")
            if state == "merged" and entry.get("into") not in sections:
                fail(problems, "coverage.merge_target",
                     f"{ref}: unknown merge target {entry.get('into')!r}")
            m = re.fullmatch(r"ext:(.+)#U(\d+)", ref)
            if not m:
                fail(problems, "coverage.ref", f"bad unit ref format: {ref}")
                continue
            epath, unum = m.group(1), int(m.group(2))
            if epath not in ext_idx:
                fail(problems, "coverage.ext_missing", f"{ref}: extraction not found")
            elif epath in stale:
                fail(problems, "coverage.stale_ref",
                     f"{ref}: references removed source {ext_idx[epath]['source']!r}")
            elif not (1 <= unum <= ext_idx[epath]["units"]):
                fail(problems, "coverage.unit_range",
                     f"{ref}: unit out of range (1..{ext_idx[epath]['units']})")
        if unresolved:
            fail(problems, "coverage.unresolved", f"{unresolved} unit(s) unresolved")
        # every enumerated unit must appear in coverage
        for epath, meta in ext_idx.items():
            if epath in stale:
                continue
            for u in range(1, meta["units"] + 1):
                if f"ext:{epath}#U{u}" not in coverage:
                    fail(problems, "coverage.gap", f"ext:{epath}#U{u} not accounted for")

    # 4) pages, anchors, markers, links, TOC
    scans = {}
    if pages:
        for cid, page in pages.items():
            full = os.path.join(BOOK, page)
            if not os.path.isfile(full):
                fail(problems, "book.page_missing", f"{page} (chapter {cid})")
                continue
            with open(full, "r", encoding="utf-8") as f:
                text = f.read()
            if ph_re.search(text):
                fail(problems, "book.placeholder", f"{page}: unfilled template placeholder")
            ps = PageScan()
            ps.feed(text)
            scans[page] = ps
        index_full = os.path.join(BOOK, "index.html")
        if os.path.isfile(index_full):
            with open(index_full, "r", encoding="utf-8") as f:
                text = f.read()
            if ph_re.search(text):
                fail(problems, "book.placeholder", "index.html: unfilled template placeholder")
            ps = PageScan()
            ps.feed(text)
            scans["index.html"] = ps
        else:
            fail(problems, "book.index_missing", "book/index.html not found")

        for page, ps in scans.items():
            for marker in ("toc", "progress", "theme-toggle"):
                if marker not in ps.ids:
                    fail(problems, "ui.marker", f"{page}: missing #{marker}")
            if ps.lang != expected_lang:
                fail(problems, "ui.lang",
                     f'{page}: <html lang="{expected_lang}"> required '
                     f'(book.config.json book.language), got {ps.lang!r}')
            if not ps.has_title:
                fail(problems, "ui.title", f"{page}: missing <title>")
            if ps.toc_malformed or ps._toc_stack is not None:
                warnings.append({"code": "toc.parse_desync",
                                 "detail": f"{page}: malformed or unclosed markup inside #toc "
                                           "(implied closes were applied, so link scoping stayed "
                                           "correct) — the builder must close every TOC tag"})

        for sid, meta in sections.items():
            anchor = "sec-" + sid.replace(".", "-")
            ps = scans.get(meta["page"])
            if ps and anchor not in ps.ids:
                fail(problems, "book.anchor", f"{meta['page']}: missing #{anchor} for section {sid}")

        book_pages = set(pages.values())
        if "index.html" in scans:
            book_pages.add("index.html")
        for page in sorted(book_pages):
            ps = scans.get(page)
            if not ps:
                continue
            for sid, meta in sections.items():
                frag = "#sec-" + sid.replace(".", "-")
                want = meta["page"] + frag
                if want in ps.toc_hrefs:
                    continue
                if page == meta["page"] and frag in ps.toc_hrefs:
                    continue
                # Every section — including a dotless one (section == whole
                # chapter) — must link with its #sec-* fragment. A bare
                # chapter-page link is NOT accepted: app.js keys read-marks,
                # scrollspy, and state restore on hrefs ending in "#sec-*",
                # so a bare link renders a dead TOC entry (v9.4).
                fail(problems, "toc.missing", f"{page}: TOC lacks link for section {sid}")

        for page, ps in list(scans.items()):  # snapshot: loop body may add lazily-scanned pages
            for href in ps.hrefs:
                if re.match(r"^(https?:|mailto:|javascript:|data:)", href):
                    continue
                target, _, frag = href.partition("#")
                tfile = page if target == "" else target
                if tfile not in scans:
                    tf_full = os.path.join(BOOK, tfile)
                    if not os.path.isfile(tf_full):
                        fail(problems, "link.file", f"{page}: broken link {href}")
                        continue
                    if frag:
                        with open(tf_full, "r", encoding="utf-8") as f:
                            text2 = f.read()
                        if ph_re.search(text2):
                            fail(problems, "book.placeholder",
                                 f"{tfile}: unfilled template placeholder")
                        ps2 = PageScan()
                        ps2.feed(text2)
                        scans[tfile] = ps2
                if frag and tfile in scans and frag not in scans[tfile].ids:
                    fail(problems, "link.anchor", f"{page}: broken anchor {href}")

    status = "PASS" if not problems else "FAIL"
    report = {"status": status, "stats": stats,
              "problemCount": len(problems), "problems": problems,
              "warningCount": len(warnings), "warnings": warnings}
    os.makedirs(STATE, exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
