#!/usr/bin/env python3
"""Mechanical validation of the book and of everything it was built from. No LLM judgment.

Blocking (problems -> FAIL)
  config       content.level
  extractions  every source has one; none is unstamped, unfinished, written from another version of
               its source (extraction.outdated), mis-numbered, or stops before its source does
               (extraction.truncated — pages/slides are counted mechanically)
  plan         shape, ids, hierarchy, supplements, unit references (plan.covers_ref)
  coverage     derived from the plan alone: every unit of every extraction is in exactly one place —
               a section's covers/merged or the plan's omitted list (coverage.gap, coverage.duplicate)
  pages        present, built at content.level, identical to their draft (book.stale_page), every
               planned section anchored and in the TOC, links resolve, no unfilled placeholder,
               UI markers, <html lang>
  drafts       nothing the plan does not know (draft.orphan_section), no repeated anchor, heading level
               and number follow the id, sections in plan order, supplements match the plan, a section
               that covers units is not empty (draft.section_empty), and the draft is not older than
               its inputs (draft.stale: a covered unit, a title or the section list changed after it
               was written)
Warnings (never block; the auditor judges each): extraction.error, extraction.stale,
  extraction.locator_gap, extraction.length_unverified, sources.unsupported, sources.visual_unread,
  coverage.brevity_reason, coverage.priority_omitted, content.section_thin,
  content.key_missing, formula.where_missing, level.steps_missing, level.long_paragraph,
  level.recall_missing, chapter.summary_missing, supplement.misplaced, terms.inconsistent, plan.order,
  ui.contrast, config.*, toc.parse_desync, book.legacy_build, plan.legacy_coverage.

Usage (project = current directory, or --root <dir>):
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_book.py" [--templates <dir>]
Writes .book-state/validate-report.json (complete) and .book-state/plan/coverage.json (the ledger
derived from the plan); prints the report with long lists shortened. Exit 0 PASS, 1 FAIL, 2 when
the directory is not a book project.
"""
import html as html_mod
import json
import os
import re
import sys
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitlib  # noqa: E402
import make_palette  # noqa: E402

# HTML void elements never emit an endtag event; pushing them would desync the #toc open-tag stack.
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "param", "source", "track", "wbr"}
# Level 1 keeps prose to orientation (<= 2 sentences per paragraph). A paragraph longer than this
# many non-whitespace characters is reported for the auditor (heuristic, non-blocking).
L1_PARA_LIMIT = 360
# The coverage ledger proves that the plan accounts for every unit — not that a draft contains it.
# A section that covers units but holds fewer than SECTION_EMPTY characters of its own is a heading
# without content (blocking); fewer than SECTION_THIN per covered unit is put before the auditor
# (the densest section of the level-1 sample has 86 per unit).
SECTION_EMPTY, SECTION_THIN = 20, 30
STDOUT_LIST_LIMIT = 40
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class PageScan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.hrefs = set(), []
        self.id_count = {}
        self.lang = None
        self.has_title = False
        self.toc_hrefs = set()
        self.html_attrs = {}
        self.meta = {}                 # <meta name=...> -> content
        self.supplements = []          # data-supplement values
        self.supp_section = {}         # supplement id -> section it sits in
        self.callouts = set()          # callout types present inside <main>
        self.paragraph_lengths = []    # non-whitespace chars per <p> inside <main>
        self.sec_seq = []              # [section id, tag, visible number or None] in document order
        self.sec_has_ol = set()        # sections that contain an ordered list
        self.sec_chars = {}            # section id -> non-whitespace characters of its own content
        self._outside = None           # [tag, depth] while inside the chapter summary/recall or a <nav>
        self.formulas = self.formulas_bare = 0
        self.terms = []                # (term, original term) from <strong>term</strong> (original)
        self.main_text = []
        self._main = 0
        self._p = None
        self._cur_sec = None
        self._heading = None           # [entry in sec_seq, tag, text parts]
        self._formula = None           # [open <div> depth, has a .where line]
        self._strong = None
        self._pending_term = None
        # Open-tag stack inside #toc: html.parser reports tags verbatim, so an omitted optional
        # close must be healed here via implied closes — otherwise every later link would leak
        # into toc_hrefs and silently turn toc.missing into a vacuous pass.
        self._toc_stack = None      # None = outside #toc
        self.toc_malformed = False

    def _close_p(self):
        if self._p is not None:
            self.paragraph_lengths.append(len(re.sub(r"\s+", "", "".join(self._p))))
            self._p = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self._pending_term = None
        if "id" in a:
            self.ids.add(a["id"])
            self.id_count[a["id"]] = self.id_count.get(a["id"], 0) + 1
        if tag == "html":
            self.lang = a.get("lang")
            self.html_attrs = a
        if tag == "title":
            self.has_title = True
        if tag == "meta" and a.get("name"):
            self.meta[a["name"]] = a.get("content") or ""
        if tag == "main":
            self._main += 1
        if self._main:
            classes = (a.get("class") or "").split()
            if self._outside is not None:
                self._outside[1] += 1 if tag == self._outside[0] else 0
            elif tag == "nav" or (tag == "div" and "callout" in classes and ("summary" in classes or "recall" in classes)):
                self._outside = [tag, 1]       # chapter-end boxes and navigation are not section content
            sec = re.fullmatch(r"sec-(\d+(?:-\d+)*)", a.get("id") or "")
            if sec:
                self._cur_sec = sec.group(1).replace("-", ".")
                entry = [self._cur_sec, tag, None]
                self.sec_seq.append(entry)
                if tag in HEADINGS:
                    self._heading = [entry, tag, []]
            if "data-supplement" in a:
                self.supplements.append(a.get("data-supplement") or "")
                self.supp_section[a.get("data-supplement") or ""] = self._cur_sec
            if "callout" in classes:
                self.callouts.update(c for c in classes if c != "callout")
            if tag == "div":
                if self._formula is not None:
                    self._formula[0] += 1
                elif "callout" in classes and "formula" in classes:
                    # data-symbols="above": the writer states that every symbol was defined earlier
                    self._formula = [1, "data-symbols" in a]
                    self.formulas += 1
            if self._formula is not None and "where" in classes:
                self._formula[1] = True
            if tag == "ol":
                self.sec_has_ol.add(self._cur_sec)
            if tag == "strong":
                self._strong = []
            if tag == "p":
                self._close_p()
                self._p = []
        if self._toc_stack is None and a.get("id") == "toc":
            self._toc_stack = []
        if self._toc_stack is not None:
            if tag == "a" and "href" in a:
                self.toc_hrefs.add(a["href"])
            if tag not in VOID_TAGS:
                self._toc_stack.append(tag)
        if tag == "a" and "href" in a:
            self.hrefs.append(a["href"])

    def handle_data(self, data):
        if self._p is not None:
            self._p.append(data)
        if self._main:
            self.main_text.append(data)
            if self._heading is not None:
                self._heading[2].append(data)
            elif self._cur_sec is not None and self._outside is None:
                self.sec_chars[self._cur_sec] = self.sec_chars.get(self._cur_sec, 0) + len("".join(data.split()))
            if self._strong is not None:
                self._strong.append(data)
            elif self._pending_term is not None:
                m = re.match(r"\s*\(([A-Za-z][^)]{1,80})\)", data)
                if m:
                    self.terms.append((self._pending_term, m.group(1)))
                self._pending_term = None

    def handle_endtag(self, tag):
        if tag == "p":
            self._close_p()
        if self._main:
            if self._outside is not None and tag == self._outside[0]:
                self._outside[1] -= 1
                if self._outside[1] <= 0:
                    self._outside = None
            if self._heading is not None and tag == self._heading[1]:
                m = re.match(r"\s*(\d+(?:\.\d+)*)(?!\S)", "".join(self._heading[2]))
                self._heading[0][2] = m.group(1) if m else None
                self._heading = None
            if tag == "div" and self._formula is not None:
                self._formula[0] -= 1
                if self._formula[0] == 0:
                    self.formulas_bare += 0 if self._formula[1] else 1
                    self._formula = None
            if tag == "strong" and self._strong is not None:
                text = " ".join("".join(self._strong).split())
                self._pending_term = text if 0 < len(text) <= 80 else None
                self._strong = None
        if tag == "main" and self._main:
            self._close_p()
            self._main -= 1
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


def placeholder_regex(templates):
    """The book.placeholder check matches only the placeholder names that actually occur in
    templates/*.html, so learner content that legitimately contains {{UPPERCASE}} tokens cannot
    false-positive a hard FAIL. Falls back to the generic pattern if no templates are readable."""
    names = set()
    try:
        for name in os.listdir(templates):
            if name.endswith(".html"):
                with open(os.path.join(templates, name), "r", encoding="utf-8") as f:
                    names.update(re.findall(r"\{\{([A-Z0-9_]+)\}\}", f.read()))
    except OSError:
        pass
    if names:
        return re.compile(r"\{\{(?:" + "|".join(sorted(names)) + r")\}\}")
    return re.compile(r"\{\{[A-Z0-9_]+\}\}")


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def run(root, templates):
    book = os.path.join(root, "book")
    state = os.path.join(root, ".book-state")
    problems, warnings, stats = [], [], {"root": root, "templates": templates, "kit": kitlib.KIT_VERSION}

    def fail(code, detail):
        problems.append({"code": code, "detail": detail})

    def warn(code, detail):
        warnings.append({"code": code, "detail": detail})

    if not os.path.isdir(templates):
        warn("templates.missing", f"templates dir not found: {templates} — placeholder check falls back "
                                  "to the generic {{UPPERCASE}} pattern")
    raw, cfg_error = kitlib.load_config(root)
    if cfg_error:
        warn("config.unreadable", cfg_error + "; using defaults")
    cfg, issues = kitlib.effective_config(raw)
    for i in issues:
        (problems if i["fatal"] else warnings).append({"code": i["code"], "detail": i["detail"]})
    expected_lang = cfg["book"]["language"]
    level = cfg["content"]["level"]
    stats["level"] = level
    ph_re = placeholder_regex(templates)

    # 1) sources and extractions
    sources, unsupported = kitlib.walk_sources(root)
    ext_idx = kitlib.extraction_index(root)
    e_problems, e_warnings, stale, _ = kitlib.check_extractions(root, sources, ext_idx, unsupported)
    problems += e_problems
    warnings += e_warnings
    stats.update(sources=len(sources), extractions=len(ext_idx), staleExtractions=len(stale),
                 units=sum(e["count"] for p, e in ext_idx.items() if p not in stale))

    # 2) plan integrity, 3) coverage derived from the plan
    plan_raw, plan_error = kitlib.load_plan(root)
    plan = {"chapters": [], "omitted": [], "has_omitted": False}
    info = {"pages": {}, "sections": {}, "supplements": {}, "order": {}, "supplement_count": 0}
    by_section = {}
    if plan_error:
        fail("plan.missing", plan_error)
    else:
        plan, shape = kitlib.normalize_plan(plan_raw)
        problems += shape
        p_problems, p_warnings, info = kitlib.check_plan(plan)
        problems += p_problems
        warnings += p_warnings
        cov_path = os.path.join(state, "plan", "coverage.json")
        ledger, c_problems, c_warnings, by_section = kitlib.derive_coverage(plan, ext_idx, stale, read_json(cov_path))
        problems += c_problems
        warnings += c_warnings
        for item in kitlib.replan_open(root, ext_idx, plan):
            if item.get("replaced"):                  # evidence for the cross-book auditor
                warn("plan.replaced_unreviewed",
                     f"{item['extraction']}: {', '.join(item['replaced'][:8])} — the unit(s) changed in place when the "
                     "source was extracted again and kept their predecessor's place in the plan by script; the "
                     "architect has not confirmed that they still belong there — auditor must judge")
        if not shape:
            text = json.dumps(ledger, ensure_ascii=False, indent=1) + "\n"
            try:
                with open(cov_path, "r", encoding="utf-8") as f:
                    same = f.read() == text
            except OSError:
                same = False
            if not same:
                os.makedirs(os.path.dirname(cov_path), exist_ok=True)
                with open(cov_path, "w", encoding="utf-8") as f:
                    f.write(text)
    pages, sections = info["pages"], info["sections"]
    stats.update(chapters=len(pages), sections=len(sections), supplements=info["supplement_count"])
    chapters = {ch["id"]: ch for ch in plan["chapters"] if ch["id"] in pages}

    # 4) pages, anchors, markers, links, TOC
    scans, texts = {}, {}
    if pages:
        for cid, page in pages.items():
            full = os.path.join(book, page)
            if not os.path.isfile(full):
                fail("book.page_missing", f"{page} (chapter {cid})")
                continue
            with open(full, "r", encoding="utf-8") as f:
                text = f.read()
            if ph_re.search(text):
                fail("book.placeholder", f"{page}: unfilled template placeholder")
            ps = PageScan()
            ps.feed(text)
            scans[page] = ps
        index_full = os.path.join(book, "index.html")
        if os.path.isfile(index_full):
            with open(index_full, "r", encoding="utf-8") as f:
                text = f.read()
            if ph_re.search(text):
                fail("book.placeholder", "index.html: unfilled template placeholder")
            ps = PageScan()
            ps.feed(text)
            scans["index.html"] = ps
        else:
            fail("book.index_missing", "book/index.html not found")

        for page, ps in scans.items():
            for marker in ("toc", "progress", "theme-toggle"):
                if marker not in ps.ids:
                    fail("ui.marker", f"{page}: missing #{marker}")
            if ps.lang != expected_lang:
                fail("ui.lang", f'{page}: <html lang="{expected_lang}"> required '
                                f'(book.config.json book.language), got {ps.lang!r}')
            if not ps.has_title:
                fail("ui.title", f"{page}: missing <title>")
            if ps.toc_malformed or ps._toc_stack is not None:
                warn("toc.parse_desync", f"{page}: malformed or unclosed markup inside #toc (implied closes were "
                                         "applied, so link scoping stayed correct) — every TOC tag must be closed")

        for sid, meta in sections.items():
            ps = scans.get(meta["page"])
            if ps and kitlib.anchor(sid) not in ps.ids:
                fail("book.anchor", f"{meta['page']}: missing #{kitlib.anchor(sid)} for section {sid}")

        book_pages = set(pages.values())
        if "index.html" in scans:
            book_pages.add("index.html")
        for page in sorted(book_pages):
            ps = scans.get(page)
            if not ps:
                continue
            for sid, meta in sections.items():
                frag = "#" + kitlib.anchor(sid)
                if meta["page"] + frag in ps.toc_hrefs or (page == meta["page"] and frag in ps.toc_hrefs):
                    continue
                # Every section — including a dotless one — must link with its #sec-* fragment:
                # app.js keys read-marks, scrollspy and state restore on hrefs ending in "#sec-*".
                fail("toc.missing", f"{page}: TOC lacks link for section {sid}")

        # 5) page contract: level, freshness, structure, supplements, level form, evidence for the auditor
        def is_v11(ps):
            return "book-kit:template" in ps.meta

        legacy_pages = sorted(p for p in book_pages if p in scans and not is_v11(scans[p]))
        if legacy_pages:
            warn("book.legacy_build", f"{len(legacy_pages)} page(s) were built by an older kit — run the kit's "
                                      "build_book.py (/book-kit:update-book) to rebuild; level, freshness and "
                                      "supplement checks were skipped for them")
        for page in sorted(book_pages):
            ps = scans.get(page)
            if ps and is_v11(ps) and str(ps.html_attrs.get("data-level")) != str(level):
                fail("book.level", f"{page}: built at level {ps.html_attrs.get('data-level')!r} but content.level "
                                   f"is {level} — run /book-kit:update-book")
        ledger_inputs = kitlib.load_ledger(root, level)
        briefed_inputs = kitlib.load_briefed(root, level)
        wcfg = kitlib.writer_config(root)
        term_seen = {}
        for cid, page in pages.items():
            ps = scans.get(page)
            if not ps or not is_v11(ps):
                continue
            rel = f".book-state/drafts/L{level}/ch-{cid}.html"
            di = kitlib.draft_info(kitlib.draft_path(root, cid, level))
            if not di["exists"]:
                fail("draft.missing", f"{rel} not found (chapter {cid})")
            else:
                if di["level"] != level:
                    fail("draft.level", f"{rel} is stamped level {di['level']}"
                                        f"{'' if di['stamped'] else ' (unstamped pre-v11 draft)'} but sits in the "
                                        f"level-{level} store")
                if ps.meta.get("book-kit:draft-sha") != di["sha"]:
                    fail("book.stale_page", f"{page}: {rel} changed after the page was built — run build_book.py")
                entry = ledger_inputs.get(cid)
                if kitlib.rewrite_pending(briefed_inputs.get(cid), di["sha"]):
                    fail("draft.stale", f"{rel}: a rewrite was requested (--rewrite) and this chapter has not been "
                                        "written again — run sync_state.py --plan and write the chapters it lists "
                                        "(chapter-writer, mode full)")
                elif entry and entry.get("draft_sha") == di["sha"]:
                    diff = kitlib.inputs_diff(entry, chapters[cid], ext_idx, wcfg["lang"])
                    if diff and diff.get("language"):
                        fail("draft.stale", f"{rel} was written in another language than book.language "
                                            f"({diff['language']}) — write the chapter again (chapter-writer, mode full)")
                    elif diff:
                        what = "; ".join(f"{k} {', '.join(v)}" for k, v in diff.items() if isinstance(v, list) and v)
                        fail("draft.stale", f"{rel} is older than its inputs ({what or 'section order changed'}) — "
                                            "rewrite these sections (chapter-writer, mode delta)")
                # what the draft contains must be something this configuration can show
                try:
                    with open(kitlib.draft_path(root, cid, level), "r", encoding="utf-8", errors="replace") as f:
                        draft_text = f.read()
                except OSError:
                    draft_text = ""
                form = kitlib.draft_form_issues(draft_text, wcfg, level)
                markup = kitlib.draft_markup_issues(draft_text)
                if markup["foreign"]:
                    (problems if di["stamped"] else warnings).append({
                        "code": "draft.foreign_markup",
                        "detail": f"{rel} contains {', '.join(markup['foreign'][:6])} — a draft is content only: the "
                                  "build owns scripts, styles and navigation, and nothing in a draft may run code; "
                                  "remove it (chapter-writer)"})
                if markup["colours"]:
                    more = len(markup["colours"]) - 5
                    warn("draft.hard_colour",
                         f"{rel}: {len(markup['colours'])} colour(s) written as literals — "
                         f"{'; '.join(markup['colours'][:5])}{f' … (+{more})' if more > 0 else ''} — they do not follow "
                         "the theme or the palette (dark ink disappears on the dark theme); use the CSS variables "
                         "(var(--fg), var(--muted), var(--line), var(--accent), var(--fig-1) …). Only a figure that "
                         "is ABOUT these colours may keep them — auditor must judge")
                if "raw_tex" in form:
                    fail("draft.raw_tex", f"{rel} contains TeX (\\( … \\) or \\[ … \\]) but ui.features.math_katex_cdn "
                                          "is off — readers would see the raw source; rewrite those formulas as inline "
                                          "HTML (chapter-writer), or turn the feature on")
                if "mermaid_off" in form:
                    fail("draft.mermaid_off", f"{rel} contains a <pre class=\"mermaid\"> diagram but "
                                              "ui.features.mermaid_cdn is off — readers would see the raw source; redraw "
                                              "it as inline SVG (chapter-writer), or turn the feature on")

            # structure: the page may contain nothing the plan does not know, in the plan's shape
            plan_ids = info["order"].get(cid, [])
            seen_order = []
            for sid, tag, number in ps.sec_seq:
                if ps.id_count.get(kitlib.anchor(sid), 0) > 1:
                    if sid not in seen_order:
                        fail("draft.anchor_dup", f"{page}: id {kitlib.anchor(sid)} occurs "
                                                 f"{ps.id_count[kitlib.anchor(sid)]} times")
                if sid not in plan_ids:
                    fail("draft.orphan_section", f"{page}: section {sid} is in the page but not in the plan — "
                                                 "remove it from the draft (stale content) or add it to the plan")
                    continue
                if sid in seen_order:
                    continue
                seen_order.append(sid)
                if sid == cid:
                    continue                                  # dotless chapter: anchored on the page <h1>
                want = "h" + str(min(sid.count(".") + 1, 6))
                if tag != want:
                    fail("draft.heading_level", f"{page}: section {sid} must be a <{want}>, found <{tag}>")
                if number != sid:
                    fail("draft.heading_number", f"{page}: the heading of section {sid} must start with "
                                                 f"\"{sid} \" (found {number!r})")
            if seen_order != [sid for sid in plan_ids if sid in seen_order]:
                fail("draft.section_order", f"{page}: sections appear as {', '.join(seen_order)} but the plan "
                                            f"orders them {', '.join(s for s in plan_ids if s in seen_order)}")

            # content: a section that covers units must hold them — the ledger alone cannot tell
            thin = []
            for sid in seen_order:
                taught = sum(1 for _, _, st in by_section.get(sid, []) if st == "represented")
                have = ps.sec_chars.get(sid, 0)
                if taught and have < SECTION_EMPTY:
                    fail("draft.section_empty", f"{page}: section {sid} covers {taught} unit(s) but has no content of "
                                                f"its own under its heading ({have} characters) — write it there")
                elif taught and have < SECTION_THIN * taught:
                    thin.append(f"{sid} ({taught} units, {have} characters)")
            if thin:
                warn("content.section_thin", f"{page}: section(s) with very little text for the units they cover: "
                                             f"{'; '.join(thin[:8])}{' …' if len(thin) > 8 else ''} — auditor must "
                                             "check each unit is really there")

            strict = di["stamped"]   # pre-v11 drafts were not written under this contract
            planned, found = info["supplements"].get(cid, {}), set(ps.supplements)
            for spid in sorted(set(planned) - found):
                (problems if strict else warnings).append(
                    {"code": "supplement.missing",
                     "detail": f"{page}: planned supplement {spid} is not marked in the page (data-supplement)"})
            for spid in sorted(found - set(planned)):
                (problems if strict else warnings).append(
                    {"code": "supplement.unplanned",
                     "detail": f"{page}: data-supplement={spid!r} is not listed in the plan"})
            for spid in sorted(x for x in found if ps.supplements.count(x) > 1):
                warn("supplement.misplaced", f"{page}: supplement {spid} is marked {ps.supplements.count(spid)} times "
                                             "(data-supplement) — one element per planned supplement")
            for spid in sorted(found & set(planned)):
                at, want = ps.supp_section.get(spid), planned[spid]
                if at and at != want and not at.startswith(want + ".") and want != cid:
                    warn("supplement.misplaced", f"{page}: supplement {spid} is planned for section {want} "
                                                 f"but sits in {at}")
            if "summary" not in ps.callouts:
                warn("chapter.summary_missing", f"{page}: no summary callout at the end of the chapter")
            if level == 1:
                if cfg["content"]["recall_questions"] and "recall" not in ps.callouts:
                    warn("level.recall_missing", f"{page}: level 1 with content.recall_questions but no recall callout")
                longs = [n for n in ps.paragraph_lengths if n > L1_PARA_LIMIT]
                if longs:
                    warn("level.long_paragraph", f"{page}: {len(longs)} paragraph(s) longer than {L1_PARA_LIMIT} "
                                                 f"characters (longest {max(longs)}) — level 1 keeps prose to "
                                                 "orientation; auditor must judge")
            if ps.formulas_bare:
                warn("formula.where_missing", f"{page}: {ps.formulas_bare} of {ps.formulas} formula callout(s) have no "
                                              "<p class=\"where\"> line — auditor must check that every symbol is "
                                              "defined at its first use")
            page_text = kitlib.norm_text(html_mod.unescape(" ".join(ps.main_text)))
            missing_keys, missing_steps = [], []
            for sid in plan_ids:
                for epath, n, unit_state in by_section.get(sid, []):
                    unit = ext_idx[epath]["units"][n]
                    for key in unit["keys"]:
                        k = kitlib.norm_text(key)
                        if k and k not in page_text:
                            missing_keys.append(f"{key!r} (ext:{epath}#U{n}, section {sid})")
                    if "procedure" in unit["flags"] and unit_state == "represented" and not any(
                            s is not None and (sid == cid or s == sid or s.startswith(sid + ".")) for s in ps.sec_has_ol):
                        missing_steps.append(f"ext:{epath}#U{n} (section {sid})")
            if missing_keys:
                warn("content.key_missing", f"{page}: {len(missing_keys)} key term(s) of covered units are not in the "
                                            f"chapter: {'; '.join(missing_keys[:8])}"
                                            f"{' …' if len(missing_keys) > 8 else ''} — auditor must judge")
            if missing_steps:
                warn("level.steps_missing", f"{page}: unit(s) flagged 'procedure' have no numbered steps in their "
                                            f"section: {'; '.join(missing_steps[:8])} — auditor must judge")
            for term, original in ps.terms:
                term_seen.setdefault(kitlib.norm_text(original.split(":")[0].split(",")[0]), {}).setdefault(term, page)
        clashes = sorted((orig, uses) for orig, uses in term_seen.items() if orig and len(uses) > 1)
        for orig, uses in clashes[:12]:
            warn("terms.inconsistent", f"'{orig}' is rendered in different ways: "
                                       + "; ".join(f"{t!r} ({p})" for t, p in sorted(uses.items())[:4])
                                       + " — one name per concept; auditor must judge")

        for page, ps in list(scans.items()):  # snapshot: loop body may add lazily-scanned pages
            for href in ps.hrefs:
                if re.match(r"^(https?:|mailto:|javascript:|data:)", href):
                    continue
                target, _, frag = href.partition("#")
                tfile = page if target == "" else target
                if tfile not in scans:
                    tf_full = os.path.join(book, tfile)
                    if not os.path.isfile(tf_full):
                        fail("link.file", f"{page}: broken link {href}")
                        continue
                    if frag:
                        with open(tf_full, "r", encoding="utf-8") as f:
                            text2 = f.read()
                        if ph_re.search(text2):
                            fail("book.placeholder", f"{tfile}: unfilled template placeholder")
                        ps2 = PageScan()
                        ps2.feed(text2)
                        scans[tfile] = ps2
                if frag and tfile in scans and frag not in scans[tfile].ids:
                    fail("link.anchor", f"{page}: broken anchor {href}")

    # 6) colours: every palette this project offers must meet WCAG AA in both themes
    try:
        defs = make_palette.load_definitions(templates)
        pals, default_palette, pwarn = make_palette.resolve_palettes(defs, cfg["ui"])
        warnings.extend(pwarn)
        stats["palette"] = default_palette
        for name, d in pals.items():
            g = make_palette.generate(d)
            for theme in ("light", "dark"):
                for f in make_palette.verify(g[theme]):
                    warn("ui.contrast", f"palette {name}/{theme}: {f['fg']} on {f['bg']} = {f['ratio']} "
                                        f"(WCAG AA needs {f['min']})")
    except (OSError, ValueError, KeyError, TypeError) as e:
        warn("templates.palettes", f"palettes.json not usable in {templates} ({e}) — colours were not checked")
    return problems, warnings, stats


def emit(root, problems, warnings, stats):
    status = "PASS" if not problems else "FAIL"

    def counts(items):
        out = {}
        for x in items:
            out[x["code"]] = out.get(x["code"], 0) + 1
        return dict(sorted(out.items()))

    report = {"status": status, "stats": stats,
              "problemCount": len(problems), "problemCodes": counts(problems), "problems": problems,
              "warningCount": len(warnings), "warningCodes": counts(warnings), "warnings": warnings}
    state = os.path.join(root, ".book-state")
    os.makedirs(state, exist_ok=True)
    with open(os.path.join(state, "validate-report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    shown = dict(report)
    for key in ("problems", "warnings"):                    # the file is complete; the console stays short
        if len(report[key]) > STDOUT_LIST_LIMIT:
            shown[key] = report[key][:STDOUT_LIST_LIMIT]
            shown[key + "Truncated"] = (f"{len(report[key]) - STDOUT_LIST_LIMIT} more in "
                                        ".book-state/validate-report.json")
    print(json.dumps(shown, indent=2, ensure_ascii=False))
    return 0 if status == "PASS" else 1


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", help="book project root (default: current directory or $BOOK_ROOT)")
    ap.add_argument("--templates", help="templates dir for the placeholder-name check and the palettes "
                                        "(default: <root>/templates if present, else the plugin templates)")
    args = ap.parse_args()
    root = kitlib.resolve_root(args.root)
    kitlib.require_book_project(root)
    kitlib.migrate_layout(root)
    templates = kitlib.resolve_templates(root, args.templates)
    try:
        problems, warnings, stats = run(root, templates)
    except Exception as e:      # whatever an agent wrote into the state, the orchestrator gets a report
        problems = [{"code": "validator.crash",
                     "detail": f"validate_book.py stopped on unexpected state: {type(e).__name__}: {e}"}]
        warnings, stats = [], {"root": root, "kit": kitlib.KIT_VERSION}
    return emit(root, problems, warnings, stats)


if __name__ == "__main__":
    sys.exit(main())
