#!/usr/bin/env python3
"""Assemble book/ deterministically from the plan, the drafts, the templates and the config.

No model writes HTML pages: this script fills the page shells, builds the nested TOC and the
agenda, wires previous/next, generates the colour tokens (assets/theme.css) and
assets/book-data.js, copies the static assets, and removes pages of chapters that left the plan.
The build costs zero tokens and is identical on every run with the same inputs.

Drafts live in one store per summary level (.book-state/drafts/L<level>/); the build reads the
store of content.level, so switching back to a level that was written before costs nothing.
For every draft it records, in that store's inputs.json, the fingerprint of what the draft was
written from — the inputs sync_state.py --plan handed its writer, not whatever the inputs are at
build time; a draft whose inputs changed afterwards is reported as draft.stale (validate_book.py
blocks on it).

It refuses to build — and writes nothing — when the inputs are inconsistent: a missing draft,
a draft stamped with another level than its store, a broken plan, or a project-local
templates/ override made for an older kit.

Usage (project = current directory, or --root <dir>):
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/build_book.py"            # build / rebuild book/
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/build_book.py" --check    # validate the inputs only, write nothing
Prints a JSON summary. Exit 0 = built, 1 = inputs not buildable (see "errors"), 2 = not a book project.
"""
import argparse
import html
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitlib  # noqa: E402
import make_palette  # noqa: E402

E = html.escape

# UI strings. Languages other than Thai fall back to English.
STRINGS = {
    "th": {
        "level_1": "ฉบับทบทวน", "level_1_long": "ฉบับทบทวนก่อนสอบ",
        "level_2": "ฉบับเรียบเรียง", "level_2_long": "ฉบับเรียบเรียงใหม่",
        "toc_title": "สารบัญ", "toc_filter": "ค้นหาหัวข้อ", "toc_open": "แสดงหรือซ่อนสารบัญ",
        "toc_empty": "ไม่พบหัวข้อที่ค้นหา", "progress": "ความคืบหน้าการอ่านหน้านี้",
        "appearance": "การแสดงผล", "theme": "สลับธีม", "skip": "ข้ามไปที่เนื้อหา",
        "pagenav": "บทก่อนหน้าและบทถัดไป", "prev": "ก่อนหน้า", "next": "ถัดไป", "home": "หน้าสารบัญ",
        "chapter": "บทที่ {n}", "start": "เริ่มอ่าน", "agenda": "สารบัญเนื้อหา",
        "sections": "{n} หัวข้อ", "cover_meta": "{c} บท {s} หัวข้อ",
        "palette": "ชุดสี", "font_size": "ขนาดตัวอักษร", "fs_down": "ตัวอักษรเล็กลง",
        "fs_reset": "ขนาดปกติ", "fs_up": "ตัวอักษรใหญ่ขึ้น", "reset": "ล้างสถานะการอ่าน",
        "expand": "แสดงหัวข้อย่อย", "collapse": "ซ่อนหัวข้อย่อย",
        "read_label": "อ่านแล้ว {r} จาก {t} หัวข้อ", "read_short": "อ่านแล้ว {r}/{t}",
        "resume": "อ่านต่อ {s}", "copy": "คัดลอก", "copied": "คัดลอกแล้ว",
        "copy_fail": "กด Ctrl+C เพื่อคัดลอก", "theme_auto": "ธีมตามระบบ", "theme_light": "ธีมสว่าง",
        "theme_dark": "ธีมมืด", "reset_confirm": "ล้างสถานะการอ่านทั้งหมดของหนังสือเล่มนี้ใช่ไหม",
        "l_def": "นิยาม", "l_formula": "สูตร", "l_note": "หมายเหตุ", "l_warn": "ข้อควรระวัง",
        "l_example": "ตัวอย่าง", "l_summary": "สรุปประเด็นสำคัญ", "l_recall": "ถามตัวเองก่อนสอบ",
        "l_supp": "เนื้อหาเสริม",
    },
    "en": {
        "level_1": "Review edition", "level_1_long": "Exam-review edition",
        "level_2": "Study edition", "level_2_long": "Study edition",
        "toc_title": "Contents", "toc_filter": "Find a topic", "toc_open": "Show or hide contents",
        "toc_empty": "No topic matches", "progress": "Reading progress on this page",
        "appearance": "Appearance", "theme": "Switch theme", "skip": "Skip to content",
        "pagenav": "Previous and next chapter", "prev": "Previous", "next": "Next", "home": "Contents page",
        "chapter": "Chapter {n}", "start": "Start reading", "agenda": "Contents",
        "sections": "{n} topics", "cover_meta": "{c} chapters, {s} topics",
        "palette": "Colours", "font_size": "Text size", "fs_down": "Smaller text",
        "fs_reset": "Default size", "fs_up": "Larger text", "reset": "Reset reading progress",
        "expand": "Show subtopics", "collapse": "Hide subtopics",
        "read_label": "Read {r} of {t} topics", "read_short": "Read {r}/{t}",
        "resume": "Continue: {s}", "copy": "Copy", "copied": "Copied",
        "copy_fail": "Press Ctrl+C to copy", "theme_auto": "Theme: system", "theme_light": "Theme: light",
        "theme_dark": "Theme: dark", "reset_confirm": "Reset all reading progress for this book?",
        "l_def": "Definition", "l_formula": "Formula", "l_note": "Note", "l_warn": "Watch out",
        "l_example": "Example", "l_summary": "Key points", "l_recall": "Ask yourself",
        "l_supp": "Added by the kit",
    },
}
JS_KEYS = ["expand", "collapse", "read_label", "read_short", "resume", "copy", "copied", "copy_fail",
           "theme_auto", "theme_light", "theme_dark", "reset_confirm"]
CSS_LABELS = ["l_def", "l_formula", "l_note", "l_warn", "l_example", "l_summary", "l_recall", "l_supp"]

PAGE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.html")
SAFE_SLUG_RE = re.compile(r"[^\s\"'\\<>&{}]{1,120}")
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
HEAD_NUM_RE = re.compile(r'(<h([2-6])\b[^>]*\bid="sec-([0-9-]+)"[^>]*>)(\s*)(\d+(?:\.\d+)*)(\s+)')
GENERATOR_MARK = 'name="generator" content="book-kit'

KATEX_HEAD = """<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16/dist/contrib/auto-render.min.js" onload="renderMathInElement(document.body,{delimiters:[{left:'\\\\(',right:'\\\\)',display:false},{left:'\\\\[',right:'\\\\]',display:true}]})"></script>"""
MERMAID_HEAD = """<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
mermaid.initialize({ startOnLoad: true, theme: document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "default" });
</script>"""


def err(errors, code, detail):
    errors.append({"code": code, "detail": detail})


def slugify(title):
    out = []
    for ch in unicodedata.normalize("NFC", title.strip().lower()):
        if ch.isalnum() or unicodedata.category(ch).startswith("M"):
            out.append(ch)
        elif ch.isspace() or ch in "-_":
            out.append("-")
    return re.sub(r"-{2,}", "-", "".join(out)).strip("-")[:80] or "book"


def existing_slug(book_dir):
    """Keep the slug of an already-built book so readers' progress (localStorage) survives rebuilds."""
    try:
        with open(os.path.join(book_dir, "assets", "book-data.js"), "r", encoding="utf-8") as f:
            m = re.search(r'["\']?slug["\']?\s*:\s*"([^"]+)"', f.read(4000))
    except OSError:
        return None
    return m.group(1) if m and SAFE_SLUG_RE.fullmatch(m.group(1)) else None


def read_chapters(plan, errors):
    chapters, seen_ids, seen_pages, seen_secs = [], set(), set(), set()
    for ch in plan.get("chapters") or []:
        if not isinstance(ch, dict):
            continue
        cid = str(ch.get("id", "")).strip()
        if not re.fullmatch(r"\d+", cid):
            err(errors, "plan.chapter_id", f"bad top-level chapter id: {cid!r}")
            continue
        if cid in seen_ids:
            err(errors, "plan.chapter_dup", f"duplicate chapter id: {cid}")
            continue
        seen_ids.add(cid)
        page = str(ch.get("page") or f"ch-{cid}.html")
        if not PAGE_RE.fullmatch(page) or page == "index.html" or page in seen_pages:
            err(errors, "plan.page", f"chapter {cid}: page {page!r} is not a unique, plain .html file name")
            continue
        seen_pages.add(page)
        secs = []
        for s in ch.get("sections") or []:
            sid = str(s.get("id", "")).strip() if isinstance(s, dict) else ""
            if not re.fullmatch(r"\d+(\.\d+)*", sid) or sid.split(".")[0] != cid or sid in seen_secs:
                err(errors, "plan.section_id", f"chapter {cid}: bad, misplaced or duplicate section id {sid!r}")
                continue
            seen_secs.add(sid)
            secs.append({"id": sid, "title": str(s.get("title_th") or s.get("title") or "").strip(),
                         "depth": sid.count(".") + 1})
        if not secs:
            err(errors, "plan.sections", f"chapter {cid} has no sections")
            continue
        chapters.append({"id": cid, "title": str(ch.get("title_th") or ch.get("title") or "").strip(),
                         "page": page, "sections": secs,
                         "dotless": len(secs) == 1 and secs[0]["id"] == cid,
                         "tab": len(chapters) % 7 + 1})
    if not chapters and not errors:
        err(errors, "plan.empty", "the plan has no chapters")
    return chapters


def parent_of(sid, ids, cid):
    """Nearest existing ancestor (the chapter itself when intermediate levels are missing)."""
    p = sid
    while "." in p:
        p = p.rsplit(".", 1)[0]
        if p in ids:
            return p
    return cid


def toc_html(chapters, current_id, S):
    def subtree(ch, parent, ids):
        kids = [s for s in ch["sections"] if s["id"] != ch["id"] and parent_of(s["id"], ids, ch["id"]) == parent]
        if not kids:
            return ""
        out = ["<ol>"]
        for s in kids:
            out.append(f'<li data-id="{s["id"]}"><a href="{ch["page"]}#{kitlib.anchor(s["id"])}">'
                       f'<span class="toc-num">{s["id"]}</span><span class="toc-text">{E(s["title"])}</span></a>'
                       f'{subtree(ch, s["id"], ids)}</li>')
        out.append("</ol>")
        return "".join(out)

    out = [f'<nav id="toc" aria-label="{E(S["toc_title"])}">',
           f'<div class="toc-head"><p class="toc-title">{E(S["toc_title"])}</p>'
           f'<input id="toc-filter" type="search" placeholder="{E(S["toc_filter"])}" '
           f'aria-label="{E(S["toc_filter"])}" autocomplete="off"></div>',
           '<ol class="toc-tree">']
    for ch in chapters:
        active = ch["id"] == current_id
        cls = "toc-ch" + (" active" if active else "") + ("" if active or ch["dotless"] else " collapsed")
        href = ch["page"] + ("#" + kitlib.anchor(ch["id"]) if ch["dotless"] else "")
        twisty = "" if ch["dotless"] else (
            f'<button class="twisty" type="button" aria-expanded="{"true" if active else "false"}" '
            f'aria-label="{E(S["collapse"] if active else S["expand"])}"></button>')
        out.append(f'<li class="{cls}" data-id="{ch["id"]}" data-tab="{ch["tab"]}"><div class="toc-row">'
                   f'<a class="toc-ch-link" href="{href}"><span class="toc-num">{ch["id"]}</span>'
                   f'<span class="toc-text">{E(ch["title"])}</span></a>'
                   f'<span class="toc-count" aria-hidden="true"></span>{twisty}</div>')
        if not ch["dotless"]:
            out.append(subtree(ch, ch["id"], {s["id"] for s in ch["sections"]}))
        out.append("</li>")
    out.append("</ol>")
    out.append(f'<p class="toc-empty" hidden>{E(S["toc_empty"])}</p>')
    segs = "".join(f'<span class="seg" data-id="{ch["id"]}" data-tab="{ch["tab"]}" '
                   f'style="flex-grow:{len(ch["sections"])}"><i></i></span>' for ch in chapters)
    out.append(f'<div class="book-progress"><span class="label"></span>'
               f'<div class="bar" aria-hidden="true">{segs}</div></div>')
    out.append("</nav>")
    return "\n".join(out)


def agenda_html(chapters, S):
    out = ['<ol class="agenda-list">']
    for ch in chapters:
        href = ch["page"] + ("#" + kitlib.anchor(ch["id"]) if ch["dotless"] else "")
        out.append(f'<li class="agenda-ch" data-id="{ch["id"]}" data-tab="{ch["tab"]}">'
                   f'<a class="agenda-tab" href="{href}" tabindex="-1" aria-hidden="true">{ch["id"]}</a>'
                   f'<div class="agenda-body"><h3><a href="{href}">{E(ch["title"])}</a></h3>'
                   f'<p class="agenda-meta"><span>{E(S["sections"].format(n=len(ch["sections"])))}</span>'
                   f'<span class="agenda-bar" aria-hidden="true"><i></i></span>'
                   f'<span class="agenda-progress"></span></p>')
        if not ch["dotless"]:
            out.append('<ol class="agenda-secs">' + "".join(
                f'<li class="d{min(s["depth"], 6)}"><a href="{ch["page"]}#{kitlib.anchor(s["id"])}">'
                f'<span class="toc-num">{s["id"]}</span><span class="toc-text">{E(s["title"])}</span></a></li>'
                for s in ch["sections"]) + "</ol>")
        out.append("</div></li>")
    out.append("</ol>")
    return "\n".join(out)


def navlink(kind, target, S):
    if target is None:
        return '<span class="navlink disabled"></span>'
    if target == "index":
        return (f'<a class="navlink {kind}" href="index.html"><span class="nav-dir">{E(S[kind])}</span>'
                f'<span class="nav-title">{E(S["home"])}</span></a>')
    return (f'<a class="navlink {kind}" href="{target["page"]}" data-tab="{target["tab"]}">'
            f'<span class="nav-dir">{E(S[kind])}</span><span class="nav-title">'
            f'<span class="toc-num">{target["id"]}</span>{E(target["title"])}</span></a>')


def appearance_html(palettes, generated, S, lang):
    sw = []
    for name, d in palettes.items():
        dots = "".join(f'<i style="background:{generated[name]["light"][s + "-solid"]}"></i>'
                       for s in ("c1", "c3", "c5", "c2"))
        sw.append(f'<button class="swatch" type="button" data-palette="{name}" aria-pressed="false">'
                  f'<span class="dots" aria-hidden="true">{dots}</span>'
                  f'<span>{E(make_palette.label_for(d, lang, name))}</span></button>')
    return (f'<div id="appearance" class="popover" role="dialog" aria-label="{E(S["appearance"])}" hidden>'
            f'<div class="pop-group"><p class="pop-label">{E(S["palette"])}</p>'
            f'<div class="swatches">{"".join(sw)}</div></div>'
            f'<div class="pop-group"><p class="pop-label">{E(S["font_size"])}</p><div class="seg-ctl">'
            f'<button type="button" data-fs-step="-1" aria-label="{E(S["fs_down"])}">A\u2212</button>'
            f'<button type="button" data-fs-step="0" aria-label="{E(S["fs_reset"])}">A</button>'
            f'<button type="button" data-fs-step="1" aria-label="{E(S["fs_up"])}">A+</button></div></div>'
            f'<div class="pop-group"><button id="reset-progress" class="link-btn" type="button">'
            f'{E(S["reset"])}</button></div></div>')


def prepare_content(draft_text, placeholder_names):
    """Draft fragment -> page content. Two mechanical touches only: section numbers in headings
    get a styling hook, and literal {{PLACEHOLDER}} text that happens to be a template name is
    entity-escaped so it renders unchanged and is never mistaken for an unfilled placeholder."""
    def num(m):
        if m.group(5) != m.group(3).replace("-", "."):
            return m.group(0)
        return f'{m.group(1)}{m.group(4)}<span class="sec-num">{m.group(5)}</span>{m.group(6)}'

    def brace(m):
        return ("&#123;&#123;" + m.group(1) + "}}") if m.group(1) in placeholder_names else m.group(0)

    return PLACEHOLDER_RE.sub(brace, HEAD_NUM_RE.sub(num, draft_text))


def fill(template, mapping):
    """Single pass: inserted content is never scanned for further placeholders."""
    return PLACEHOLDER_RE.sub(lambda m: mapping.get(m.group(1), m.group(0)), template)


def write_if_changed(path, data, written, rel):
    data = data if isinstance(data, bytes) else data.encode("utf-8")
    try:
        with open(path, "rb") as f:
            if f.read() == data:
                return
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    written.append(rel)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate inputs only; write nothing")
    ap.add_argument("--root", help="book project root (default: current directory or $BOOK_ROOT)")
    ap.add_argument("--templates", help="templates dir (default: <root>/templates if present, else the plugin's)")
    args = ap.parse_args()
    root = kitlib.resolve_root(args.root)
    kitlib.require_book_project(root)
    templates = kitlib.resolve_templates(root, args.templates)
    book_dir = os.path.join(root, "book")
    errors, warnings = [], []
    migrated = [] if args.check else kitlib.migrate_layout(root)

    raw, cfg_error = kitlib.load_config(root)
    if cfg_error:
        warnings.append({"code": "config.unreadable", "detail": cfg_error + "; using defaults"})
    cfg, issues = kitlib.effective_config(raw)
    for i in issues:
        (errors if i["fatal"] else warnings).append({"code": i["code"], "detail": i["detail"]})
    level, lang = cfg["content"]["level"], cfg["book"]["language"]
    S = STRINGS.get(lang.split("-")[0].lower(), STRINGS["en"])

    # templates (and their contract)
    shells = {}
    for name in ("chapter-shell.html", "book-shell.html"):
        try:
            with open(os.path.join(templates, name), "r", encoding="utf-8") as f:
                shells[name] = f.read()
        except OSError as e:
            err(errors, "templates.missing", f"{name} not readable in {templates} ({e})")
    for name, text in shells.items():
        if f'name="book-kit:template" content="{kitlib.TEMPLATE_CONTRACT}"' not in text:
            err(errors, "templates.contract",
                f"{os.path.join(templates, name)} was made for another kit version (needs template contract "
                f"{kitlib.TEMPLATE_CONTRACT}). If {templates!r} is an old project-local override, rename or delete "
                "it (the plugin templates are used instead), or re-create it with /book-kit:design")
    palettes = generated = default_palette = None
    try:
        defs = make_palette.load_definitions(templates)
        palettes, default_palette, pwarn = make_palette.resolve_palettes(defs, cfg["ui"])
        warnings.extend(pwarn)
        generated = {n: make_palette.generate(d) for n, d in palettes.items()}
        for n, g in generated.items():
            for theme in ("light", "dark"):
                for f in make_palette.verify(g[theme]):
                    warnings.append({"code": "ui.contrast",
                                     "detail": f"palette {n}/{theme}: {f['fg']} on {f['bg']} = {f['ratio']} "
                                               f"(needs {f['min']})"})
    except (OSError, ValueError, KeyError, TypeError) as e:
        err(errors, "templates.palettes", f"palettes.json unusable in {templates}: {e}")

    # plan + drafts
    plan, plan_error = kitlib.load_plan(root)
    chapters = []
    if plan_error:
        err(errors, "plan.missing", plan_error)
    else:
        chapters = read_chapters(plan, errors)
    drafts = {}
    for ch in chapters:
        path = kitlib.draft_path(root, ch["id"], level)
        info = kitlib.draft_info(path)
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        if not info["exists"]:
            err(errors, "draft.missing", f"{rel} not found (chapter {ch['id']}) — this chapter has not been "
                                         f"written at level {level} yet (/book-kit:update-book)")
            continue
        if info["level"] != level:
            how = f"level {info['level']}" + ("" if info["stamped"] else " (unstamped pre-v11 draft)")
            err(errors, "draft.level", f"{rel} was written at {how} but sits in the level-{level} store — "
                                       "rewrite this chapter at the configured level (/book-kit:update-book)")
            continue
        if info["stamped"] and info["chapter"] != ch["id"]:
            err(errors, "draft.chapter", f"{rel} is stamped chapter={info['chapter']!r}; expected {ch['id']!r}")
            continue
        with open(path, "r", encoding="utf-8") as f:
            drafts[ch["id"]] = (f.read(), info["sha"])

    summary = {"root": root, "templates": templates, "level": level, "kit": kitlib.KIT_VERSION}
    if migrated:
        summary["migrated"] = migrated
    if errors:
        summary.update(status="ERROR", errors=errors, warnings=warnings)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 1
    if args.check:
        summary.update(status="OK", checked=True, chapters=len(chapters), palette=default_palette, warnings=warnings)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    # ------------------------------------------------------------ what each draft was written from
    plan_norm, _ = kitlib.normalize_plan(plan)
    ext_idx = kitlib.extraction_index(root)
    built = {ch["id"] for ch in chapters}
    plan_norm["chapters"] = [c for c in plan_norm["chapters"] if c["id"] in built]
    _, _, stale = kitlib.settle_ledger(root, plan_norm, ext_idx, level)
    stale = {cid: {k: v for k, v in diff.items() if v} for cid, diff in stale.items()}
    # A slice tells a writer what to do. Once a chapter's draft is current that instruction is done:
    # a later repair or audit fix for the chapter must not read "write the whole chapter" from it.
    slices_dir = os.path.join(root, ".book-state", "plan", "slices")
    for ch in chapters:
        spath = os.path.join(slices_dir, f"ch-{ch['id']}.json")
        if ch["id"] in stale or not os.path.isfile(spath):
            continue
        try:
            with open(spath, "r", encoding="utf-8") as f:
                sl = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(sl, dict) and sl.get("level") == level and sl.get("write") != {"mode": "none"}:
            sl["write"] = {"mode": "none"}
            with open(spath, "w", encoding="utf-8") as f:
                f.write(json.dumps(sl, ensure_ascii=False, indent=1) + "\n")
    for cid, diff in stale.items():
        warnings.append({"code": "draft.stale",
                         "detail": f"chapter {cid}: its draft is older than its inputs ({diff}) — "
                                   "chapter-writer, mode delta"})

    # ------------------------------------------------------------ render
    slug = cfg["book"]["slug"] if SAFE_SLUG_RE.fullmatch(cfg["book"]["slug"] or "") else None
    slug = slug or existing_slug(book_dir) or slugify(cfg["book"]["title"])
    title = cfg["book"]["title"]
    names = set(PLACEHOLDER_RE.findall(shells["chapter-shell.html"])) | set(PLACEHOLDER_RE.findall(shells["book-shell.html"]))
    head_extra = "\n".join(x for x in (KATEX_HEAD if cfg["ui"]["features"]["math_katex_cdn"] else "",
                                       MERMAID_HEAD if cfg["ui"]["features"]["mermaid_cdn"] else "") if x)
    n_sections = sum(len(ch["sections"]) for ch in chapters)
    common = {
        "LANG": E(lang, quote=True), "BOOK_SLUG": slug, "BOOK_TITLE": E(title), "LEVEL": str(level),
        "LEVEL_LABEL": E(S[f"level_{level}"]), "LEVEL_LABEL_LONG": E(S[f"level_{level}_long"]),
        "PALETTE": default_palette, "PALETTE_NAMES": json.dumps(list(palettes)),
        "KIT_VERSION": kitlib.KIT_VERSION, "HEAD_EXTRA": head_extra,
        "APPEARANCE_HTML": appearance_html(palettes, generated, S, lang),
        "T_SKIP": E(S["skip"]), "T_PROGRESS": E(S["progress"]), "T_TOC_OPEN": E(S["toc_open"]),
        "T_APPEARANCE": E(S["appearance"]), "T_THEME": E(S["theme"]), "T_PAGENAV": E(S["pagenav"]),
        "T_START": E(S["start"]), "T_AGENDA": E(S["agenda"]),
    }
    outputs = {}
    for i, ch in enumerate(chapters):
        text, sha = drafts[ch["id"]]
        mapping = dict(common)
        mapping.update({
            "CHAPTER_ID": ch["id"], "TAB": str(ch["tab"]), "DRAFT_SHA": sha,
            "PAGE_TITLE": E(f'{ch["id"]} {ch["title"]}'), "CHAPTER_TITLE": E(ch["title"]),
            "CHAPTER_KICKER": E(S["chapter"].format(n=ch["id"])),
            "H1_ATTR": f' id="{kitlib.anchor(ch["id"])}"' if ch["dotless"] else "",
            "TOC_HTML": toc_html(chapters, ch["id"], S),
            "CONTENT_HTML": prepare_content(text, names),
            "PREV_LINK": navlink("prev", chapters[i - 1] if i else "index", S),
            "NEXT_LINK": navlink("next", chapters[i + 1] if i + 1 < len(chapters) else None, S),
        })
        outputs[ch["page"]] = fill(shells["chapter-shell.html"], mapping)
    first = chapters[0]
    mapping = dict(common)
    mapping.update({
        "BOOK_SUBTITLE": E(cfg["book"]["subtitle"]), "BOOK_AUTHOR": E(cfg["book"]["author"]),
        "FIRST_CHAPTER_HREF": first["page"] + ("#" + kitlib.anchor(first["id"]) if first["dotless"] else ""),
        "COVER_META": E(S["cover_meta"].format(c=len(chapters), s=n_sections)),
        "TOC_HTML": toc_html(chapters, None, S), "AGENDA_HTML": agenda_html(chapters, S),
    })
    outputs["index.html"] = fill(shells["book-shell.html"], mapping)

    labels = ":root{" + "".join(f'--{k.replace("_", "-")}:"{S[k]}";' for k in CSS_LABELS) + "}\n"
    # content.recall_questions switched off after level-1 chapters were written: their recall boxes
    # are hidden, at no token cost; switching it on again shows them
    recall_off = "" if cfg["content"]["recall_questions"] else ".callout.recall{display:none}\n"
    outputs["assets/theme.css"] = make_palette.theme_css(generated, default_palette) + labels + recall_off
    data = {
        "kit": kitlib.KIT_VERSION, "slug": slug, "title": title, "language": lang, "level": level,
        "palette": default_palette,
        "palettes": [{"name": n, "label": make_palette.label_for(d, lang, n)} for n, d in palettes.items()],
        "pages": [{"id": ch["id"], "href": ch["page"], "title": ch["title"], "tab": ch["tab"]} for ch in chapters],
        "sections": [{"id": s["id"], "page": ch["page"], "href": f'{ch["page"]}#{kitlib.anchor(s["id"])}',
                      "title": s["title"], "level": s["depth"]} for ch in chapters for s in ch["sections"]],
        # every renumbering of chapters/sections, oldest first: app.js moves a reader's stored
        # progress to the new ids instead of attributing it to whatever took the old number
        "idHistory": [h["map"] for h in plan_norm["idHistory"]],
        "t": {k: S[k] for k in JS_KEYS},
    }
    outputs["assets/book-data.js"] = "window.BOOK = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n"

    # ------------------------------------------------------------ write
    written, removed = [], []
    for rel, text in outputs.items():
        write_if_changed(os.path.join(book_dir, *rel.split("/")), text, written, rel)
    assets_src = os.path.join(templates, "assets")
    for dirpath, _, filenames in os.walk(assets_src):
        for name in sorted(filenames):
            src = os.path.join(dirpath, name)
            rel = "assets/" + os.path.relpath(src, assets_src).replace(os.sep, "/")
            if rel in outputs:
                continue
            with open(src, "rb") as f:
                write_if_changed(os.path.join(book_dir, *rel.split("/")), f.read(), written, rel)
    # pages of chapters that left the plan (only files this kit generated are ever deleted)
    for name in sorted(os.listdir(book_dir)):
        if not name.endswith(".html") or name in outputs:
            continue
        full = os.path.join(book_dir, name)
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                generated_here = GENERATOR_MARK in f.read(1500)
        except OSError:
            continue
        if generated_here:
            os.remove(full)
            removed.append(name)

    summary.update(status="OK", palette=default_palette, palettes=list(palettes), slug=slug,
                   chapters=len(chapters), sections=n_sections,
                   pages=["index.html"] + [ch["page"] for ch in chapters],
                   written=written, unchanged=len(outputs) - sum(1 for r in outputs if r in written),
                   removed=removed, stale=stale, warnings=warnings, open="book/index.html")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
