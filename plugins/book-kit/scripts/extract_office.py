#!/usr/bin/env python3
"""Turn .pptx / .docx sources into markdown so agents never open the binaries (extractor v3).

Standard library only — no python-pptx / python-docx needed. Reads the Office XML directly, so
nothing a slide or page says is dropped without a trace:
  * equations typed in the Office equation editor become  [math: s^2 = (∑(x_i − x̄)^2)/(n − 1)]
  * shapes PowerPoint wraps in mc:AlternateContent (every text box that holds an equation) are read
  * SmartArt text, table cells, chart data, text boxes, footnotes, line breaks and alt text are kept
  * what cannot be turned into text is counted and marked in place: [visual] pictures,
    [object] embedded OLE objects (Equation Editor 3.0, MathType, Excel sheets)
  * v3: endnotes; numbered lists as "1." items (so steps stay recognisable as steps); lines longer
    than 1800 characters are wrapped, because the reading tool may cut over-long lines. A text
    source (.md/.txt/.html) that has such lines gets a wrapped copy the same way — its content is
    unchanged, only re-broken at spaces.

Usage (project = current directory, or --root <dir>):
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/extract_office.py" --all                    # every source that needs it and whose cache is missing or older
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/extract_office.py" "sources/ch2/2.1 deck.pptx" [...]
Output: .book-state/extracted-office/<sha256 first 12>.md (cached by content hash and extractor
version). Prints a JSON summary; exit 0 unless the directory is not a book project (2).
"""
import argparse
import json
import os
import posixpath
import re
import sys
import unicodedata
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitlib  # noqa: E402

_NS_SUFFIX = [
    ("office/drawing/2010/main", "a14"), ("markup-compatibility/2006", "mc"),
    ("drawingml/2006/main", "a"), ("drawingml/main", "a"),
    ("presentationml/2006/main", "p"), ("presentationml/main", "p"),
    ("officeDocument/2006/math", "m"), ("officeDocument/math", "m"),
    ("drawingml/2006/chart", "c"), ("drawingml/chart", "c"),
    ("drawingml/2006/diagram", "dgm"), ("drawingml/diagram", "dgm"),
    ("wordprocessingml/2006/main", "w"), ("wordprocessingml/main", "w"),
    ("officeDocument/2006/relationships", "r"), ("officeDocument/relationships", "r"),
    ("package/2006/relationships", "rel"), ("urn:schemas-microsoft-com:vml", "v"),
    ("word/2010/wordprocessingShape", "wps"),
]
_TAG_CACHE = {}


def T(el_or_tag):
    """'{namespace}local' -> 'prefix:local' with the prefixes used in this file (works for the
    transitional and the strict Office namespaces alike)."""
    tag = el_or_tag if isinstance(el_or_tag, str) else el_or_tag.tag
    hit = _TAG_CACHE.get(tag)
    if hit is None:
        if tag.startswith("{"):
            uri, _, name = tag[1:].partition("}")
            prefix = next((p for suffix, p in _NS_SUFFIX if uri.endswith(suffix)), "?")
            hit = f"{prefix}:{name}"
        else:
            hit = tag
        _TAG_CACHE[tag] = hit
    return hit


def A(el, name):
    """Attribute by prefixed name ('r:id', 'w:val') or plain name ('lvl')."""
    if ":" not in name:
        return el.get(name)
    for key, value in el.attrib.items():
        if T(key) == name:
            return value
    return None


def child(el, name):
    for c in el:
        if T(c) == name:
            return c
    return None


def find(el, *path):
    for name in path:
        if el is None:
            return None
        el = child(el, name)
    return el


def descendants(el, name):
    return [d for d in el.iter() if T(d) == name] if el is not None else []


def branch(alt):
    """Children of the branch of an mc:AlternateContent that carries the real content."""
    chosen = child(alt, "mc:Choice")
    if chosen is None:
        chosen = child(alt, "mc:Fallback")
    return list(chosen) if chosen is not None else []


class Package:
    """A .pptx/.docx zip with relationship lookups."""

    def __init__(self, path):
        self.zip = zipfile.ZipFile(path)
        self.names = set(self.zip.namelist())

    def xml(self, part):
        if part not in self.names:
            return None
        try:
            return ET.fromstring(self.zip.read(part))
        except ET.ParseError:
            return None

    def rels(self, part):
        """{relationship id: (type suffix, target part)} of a part."""
        root = self.xml(posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels"))
        out = {}
        for r in root if root is not None else []:
            target = r.get("Target") or ""
            if r.get("TargetMode") == "External":
                continue
            full = target.lstrip("/") if target.startswith("/") else posixpath.normpath(
                posixpath.join(posixpath.dirname(part), target))
            out[r.get("Id")] = ((r.get("Type") or "").rsplit("/", 1)[-1], full)
        return out


# ----------------------------------------------------------------------------- Office math -> text
def _wrap(s):
    s = s.strip()
    return s if re.fullmatch(r"[\w.\u0300-\u036f]*", s) else f"({s})"


def omml(el):
    """Linear text of an Office math element (m:oMath, m:oMathPara or any part of one)."""
    tag = T(el)
    kids = lambda name: [c for c in el if T(c) == name]          # noqa: E731
    part = lambda name: "".join(omml(c) for c in kids(name))      # noqa: E731
    if tag == "m:t":
        return el.text or ""
    if tag == "m:oMathPara":
        return " ; ".join(x for x in (omml(c) for c in kids("m:oMath")) if x.strip())
    if tag == "m:f":
        return f"{_wrap(part('m:num'))}/{_wrap(part('m:den'))}"
    if tag == "m:sSup":
        return f"{_wrap(part('m:e'))}^{_wrap(part('m:sup'))}"
    if tag == "m:sSub":
        return f"{_wrap(part('m:e'))}_{_wrap(part('m:sub'))}"
    if tag == "m:sSubSup":
        return f"{_wrap(part('m:e'))}_{_wrap(part('m:sub'))}^{_wrap(part('m:sup'))}"
    if tag == "m:sPre":
        return f"_{_wrap(part('m:sub'))}^{_wrap(part('m:sup'))}{_wrap(part('m:e'))}"
    if tag == "m:rad":
        deg = part("m:deg").strip()
        return (f"root[{deg}]" if deg else "√") + f"({part('m:e').strip()})"
    if tag == "m:nary":
        chr_el = find(el, "m:naryPr", "m:chr")
        op = (A(chr_el, "m:val") if chr_el is not None else None) or "∫"
        sub, sup = part("m:sub").strip(), part("m:sup").strip()
        return op + (f"_{_wrap(sub)}" if sub else "") + (f"^{_wrap(sup)}" if sup else "") + " " + part("m:e")
    if tag == "m:d":
        pr = child(el, "m:dPr")
        get = lambda name, default: (A(child(pr, name), "m:val") if pr is not None and child(pr, name) is not None  # noqa: E731
                                     else default)
        beg, end, sep = get("m:begChr", "("), get("m:endChr", ")"), get("m:sepChr", "|")
        return (beg or "") + (sep or "|").join(omml(c) for c in kids("m:e")) + (end or "")
    if tag == "m:func":
        return f"{part('m:fName').strip()} {_wrap(part('m:e'))}"
    if tag in ("m:acc", "m:bar"):
        base = part("m:e").strip()
        mark = "\u0305"
        if tag == "m:acc":
            chr_el = find(el, "m:accPr", "m:chr")
            mark = (A(chr_el, "m:val") if chr_el is not None else None) or "\u0302"
        if len(base) == 1 and len(mark) == 1 and 0x0300 <= ord(mark) <= 0x036F:
            return base + mark
        return {"\u0305": "bar", "¯": "bar", "\u0302": "hat", "^": "hat", "\u0303": "tilde", "~": "tilde",
                "\u20d7": "vec", "→": "vec", "\u0307": "dot", "˙": "dot"}.get(mark, "acc") + f"({base})"
    if tag == "m:limLow":
        return f"{part('m:e')}_{_wrap(part('m:lim'))}"
    if tag == "m:limUpp":
        return f"{part('m:e')}^{_wrap(part('m:lim'))}"
    if tag == "m:m":
        return "[" + "; ".join(", ".join(omml(c) for c in row if T(c) == "m:e") for row in kids("m:mr")) + "]"
    if tag == "m:eqArr":
        return " ; ".join(omml(c) for c in kids("m:e"))
    if tag.endswith("Pr"):                       # property containers carry no content
        return ""
    return "".join(omml(c) for c in el)


def math_text(el, stats):
    stats["equations"] += 1
    text = re.sub(r"\s+", " ", omml(el)).strip()
    return f"[math: {text}]" if text else "[math: (empty equation)]"


# ----------------------------------------------------------------------------- DrawingML text (pptx, charts, SmartArt)
def a_paragraph(p, stats):
    """(indent level, text) of an a:p — runs, fields, line breaks and equations in reading order."""
    out = []

    def walk(node):
        for c in node:
            tag = T(c)
            if tag in ("a:r", "a:fld"):
                t = child(c, "a:t")
                out.append(t.text or "" if t is not None else "")
            elif tag == "a:br":
                out.append("\n")
            elif tag == "a14:m":
                out.append(math_text(c, stats))
            elif tag == "mc:AlternateContent":
                walk(branch(c))
    walk(p)
    ppr = child(p, "a:pPr")
    lvl = int(A(ppr, "lvl") or 0) if ppr is not None and (A(ppr, "lvl") or "0").isdigit() else 0
    return lvl, "".join(out).strip()


def a_text_body(body, stats, bullet="- "):
    lines = []
    for p in body if body is not None else []:
        if T(p) != "a:p":
            continue
        lvl, text = a_paragraph(p, stats)
        if not text:
            continue
        pad = "  " * min(lvl, 4)
        first, *rest = text.split("\n")
        lines.append(pad + bullet + first.strip())
        lines.extend(pad + "  " + r.strip() for r in rest if r.strip())
    return lines


def chart_lines(pkg, part, stats):
    root = pkg.xml(part)
    if root is None:
        return ["- [chart] could not be read"]
    stats["charts"] += 1
    title = ""
    title_el = find(root, "c:chart", "c:title")
    if title_el is not None:
        title = " ".join((t.text or "").strip() for t in descendants(title_el, "a:t")).strip()
    lines = [f"- [chart] {title}".rstrip()]
    for ser in descendants(root, "c:ser")[:12]:
        def values(name):
            holder = child(ser, name)
            return [(v.text or "").strip() for pt in descendants(holder, "c:pt") for v in pt if T(v) == "c:v"] \
                if holder is not None else []
        name = " ".join(values("c:tx")) or "series"
        cats = values("c:cat") or values("c:xVal")
        vals = values("c:val") or values("c:yVal")
        pairs = [f"{c}={v}" for c, v in zip(cats, vals)] if cats and len(cats) == len(vals) else vals
        shown = ", ".join(pairs[:40]) + (f", … ({len(pairs)} points)" if len(pairs) > 40 else "")
        lines.append(f"  - {name}: {shown}")
    return lines


def smartart_lines(pkg, part, stats):
    root = pkg.xml(part)
    stats["smartart"] += 1
    items = []
    for pt in descendants(root, "dgm:pt") if root is not None else []:
        text = " ".join((t.text or "").strip() for t in descendants(pt, "a:t")).strip()
        if text:
            items.append(text)
    if not items:
        return ["- [smartart] (no text; the diagram itself is not extracted)"]
    return ["- [smartart] items in document order (arrows/layout are not extracted): " + " | ".join(items)]


def pptx_shape(el, pkg, rels, stats, lines, depth=0):
    tag = T(el)
    if tag == "mc:AlternateContent":
        stats["wrapped"] += 1
        for c in branch(el):
            pptx_shape(c, pkg, rels, stats, lines, depth)
    elif tag == "p:grpSp":
        for c in el:
            pptx_shape(c, pkg, rels, stats, lines, depth + 1)
    elif tag == "p:sp":
        ph = find(el, "p:nvSpPr", "p:nvPr", "p:ph")
        if ph is not None and (ph.get("type") or "") in ("sldNum", "dt", "ftr", "hdr"):
            return
        lines.extend(a_text_body(child(el, "p:txBody"), stats))
    elif tag == "p:pic":
        stats["pictures"] += 1
        pr = find(el, "p:nvPicPr", "p:cNvPr")
        alt = (pr.get("descr") or "").strip() if pr is not None else ""
        if alt:
            lines.append(f"- [picture, alt text] {alt}")
    elif tag == "p:graphicFrame":
        data = find(el, "a:graphic", "a:graphicData")
        if data is None:
            return
        uri = data.get("uri") or ""
        tbl = child(data, "a:tbl")
        if tbl is not None:
            stats["tables"] += 1
            for tr in tbl:
                if T(tr) != "a:tr":
                    continue
                cells = [" / ".join(x.lstrip("- ").strip() for x in a_text_body(child(tc, "a:txBody"), stats))
                         for tc in tr if T(tc) == "a:tc"]
                lines.append("| " + " | ".join(cells) + " |")
        elif uri.endswith("/chart"):
            ref = next((c for c in data if T(c) == "c:chart"), None)
            target = rels.get(A(ref, "r:id")) if ref is not None else None
            lines.extend(chart_lines(pkg, target[1], stats) if target else ["- [chart] (data part missing)"])
        elif uri.endswith("/diagram"):
            ref = next((c for c in data if T(c) == "dgm:relIds"), None)
            target = rels.get(A(ref, "r:dm")) if ref is not None else None
            lines.extend(smartart_lines(pkg, target[1], stats) if target else ["- [smartart] (data part missing)"])
        else:
            stats["ole"] += 1
            prog = next((d.get("progId") for d in el.iter() if d.get("progId")), "") or "unknown type"
            lines.append(f"- [object] embedded object ({prog}) — NOT extracted; if it carries teaching content "
                         "(an old-style equation, a spreadsheet), flag a gap")


def pptx_to_md(pkg, name, stats):
    pres = pkg.xml("ppt/presentation.xml")
    if pres is None:
        raise ValueError("ppt/presentation.xml is missing (not a .pptx?)")
    prels = pkg.rels("ppt/presentation.xml")
    slides = []
    id_list = child(pres, "p:sldIdLst")
    for sld in id_list if id_list is not None else []:
        target = prels.get(A(sld, "r:id"))
        if target:
            slides.append(target[1])
    lines = [f"# PPTX extraction: {name}", ""]
    for i, part in enumerate(slides, 1):
        root = pkg.xml(part)
        stats["slides"] += 1
        hidden = root is not None and root.get("show") == "0"
        lines.append(f"## Slide {i}" + (" (hidden in the slide show)" if hidden else ""))
        if root is None:
            lines += ["- [error] this slide could not be parsed", ""]
            continue
        rels = pkg.rels(part)
        before = dict(stats)
        tree = find(root, "p:cSld", "p:spTree")
        for el in tree if tree is not None else []:
            pptx_shape(el, pkg, rels, stats, lines)
        pics, ole = stats["pictures"] - before["pictures"], stats["ole"] - before["ole"]
        if pics:
            lines.append(f"- [visual] {pics} picture(s) on this slide are NOT extracted — infer nothing from them; "
                         "flag a gap if a picture carries the teaching content (ask for a PDF export of the deck)")
        notes_part = next((t for kind, t in rels.values() if kind == "notesSlide"), None)
        notes_root = pkg.xml(notes_part) if notes_part else None
        if notes_root is not None:
            notes = []
            for sp in descendants(notes_root, "p:sp"):
                ph = find(sp, "p:nvSpPr", "p:nvPr", "p:ph")
                if ph is not None and ph.get("type") == "body":
                    notes += [x.lstrip("- ").strip() for x in a_text_body(child(sp, "p:txBody"), stats)]
            if notes:
                lines.append("> notes: " + " / ".join(notes))
        lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------------------------- WordprocessingML (docx)
def docx_numbering(pkg):
    """{numId: {ilvl: number format}} — tells a numbered list ("decimal", "lowerLetter", …) from a
    bulleted one ("bullet")."""
    root = pkg.xml("word/numbering.xml")
    abstract, nums = {}, {}
    for el in root if root is not None else []:
        if T(el) == "w:abstractNum":
            levels = {}
            for lvl in el:
                if T(lvl) == "w:lvl":
                    fmt = child(lvl, "w:numFmt")
                    levels[A(lvl, "w:ilvl") or "0"] = (A(fmt, "w:val") or "") if fmt is not None else ""
            abstract[A(el, "w:abstractNumId")] = levels
        elif T(el) == "w:num":
            ref = child(el, "w:abstractNumId")
            nums[A(el, "w:numId")] = A(ref, "w:val") if ref is not None else None
    return {nid: abstract.get(aid, {}) for nid, aid in nums.items()}


def _ordered(numbering, numpr):
    """True when a w:numPr points at a numbered (not bulleted) list level."""
    if numpr is None:
        return False
    num, lvl = child(numpr, "w:numId"), child(numpr, "w:ilvl")
    fmt = numbering.get(A(num, "w:val") if num is not None else None, {}).get(
        (A(lvl, "w:val") if lvl is not None else None) or "0", "")
    return fmt not in ("", "bullet", "none")


def docx_styles(pkg, numbering=None):
    """({style id: heading level} for heading styles — by outline level or by name, in any UI
    language —, {style ids that make a paragraph a list item}, {those that number it})."""
    root = pkg.xml("word/styles.xml")
    raw, lists, ordered = {}, set(), set()
    for st in root if root is not None else []:
        if T(st) != "w:style":
            continue
        sid = A(st, "w:styleId") or ""
        name_el, based, ppr = child(st, "w:name"), child(st, "w:basedOn"), child(st, "w:pPr")
        outline = child(ppr, "w:outlineLvl") if ppr is not None else None
        raw[sid] = ((A(name_el, "w:val") or "") if name_el is not None else "",
                    (A(based, "w:val") or "") if based is not None else "",
                    A(outline, "w:val") if outline is not None else None)
        if (ppr is not None and child(ppr, "w:numPr") is not None) or raw[sid][0].lower().startswith("list "):
            lists.add(sid)
            if _ordered(numbering or {}, child(ppr, "w:numPr") if ppr is not None else None) \
                    or raw[sid][0].lower().startswith("list number"):
                ordered.add(sid)
    levels = {}

    def level(sid, seen=()):
        if sid in levels:
            return levels[sid]
        name, based, outline = raw.get(sid, ("", "", None))
        found = None
        if outline is not None and outline.isdigit() and int(outline) < 9:
            found = int(outline) + 1
        else:
            m = re.match(r"(?:heading|หัวเรื่อง|überschrift|titre|título|titolo)\s*(\d)", name.strip(), re.I) \
                or re.fullmatch(r"heading(\d)", sid, re.I)
            if m:
                found = int(m.group(1))
            elif name.strip().lower() == "title":
                found = 1
            elif based and based not in seen:
                found = level(based, seen + (sid,))
        levels[sid] = found
        return found

    for sid in raw:
        level(sid)
    return levels, lists, ordered


def w_paragraph(p, stats, extra):
    """Text of a w:p in reading order. Text boxes and footnote marks found on the way are
    appended to `extra` so they are emitted right after the paragraph."""
    out = []

    def walk(node):
        for c in node:
            tag = T(c)
            if tag == "w:r":
                walk(c)
            elif tag == "w:t":
                out.append(c.text or "")
            elif tag == "w:tab":
                out.append("\t")
            elif tag in ("w:br", "w:cr"):
                out.append("\n")
            elif tag == "w:noBreakHyphen":
                out.append("-")
            elif tag == "w:sym":
                code = A(c, "w:char") or ""
                try:
                    n = int(code, 16)
                    out.append(chr(n - 0xF000 if 0xF000 <= n <= 0xF0FF else n))
                except ValueError:
                    pass
            elif tag in ("m:oMath", "m:oMathPara"):
                out.append(" " + math_text(c, stats) + " ")
            elif tag == "w:footnoteReference":
                out.append(f"[fn {A(c, 'w:id')}]")
            elif tag == "w:endnoteReference":
                out.append(f"[en {A(c, 'w:id')}]")
            elif tag in ("w:drawing", "w:pict", "w:object"):
                boxes = descendants(c, "w:txbxContent")
                if boxes:
                    stats["textboxes"] += 1
                    for inner in boxes[0]:
                        if T(inner) == "w:p":
                            t = w_paragraph(inner, stats, extra)
                            if t:
                                extra.append(f"[text box] {t}")
                elif tag == "w:object":
                    stats["ole"] += 1
                    prog = next((d.get("ProgID") for d in c.iter() if d.get("ProgID")), "") or "unknown type"
                    out.append(f" [object: embedded {prog} — NOT extracted] ")
                else:
                    stats["pictures"] += 1
                    pr = next((d for d in c.iter() if d.tag.endswith("}docPr")), None)
                    alt = (pr.get("descr") or "").strip() if pr is not None else ""
                    out.append(f" [picture{': ' + alt if alt else ' — NOT extracted'}] ")
            elif tag == "mc:AlternateContent":
                walk(branch(c))
            elif tag in ("w:del", "w:moveFrom", "w:instrText", "w:pPr", "w:rPr"):
                continue
            elif tag in ("w:hyperlink", "w:ins", "w:moveTo", "w:smartTag", "w:sdt", "w:sdtContent",
                         "w:fldSimple", "w:dir", "w:bdo", "w:customXml"):
                walk(c)
    walk(p)
    return re.sub(r"[ \t]{2,}", " ", "".join(out)).strip()


def docx_blocks(parent, styles, stats, lines, counter):
    levels, list_styles, ordered_styles, numbering = styles
    for el in parent:
        tag = T(el)
        if tag == "w:p":
            extra = []
            text = w_paragraph(el, stats, extra)
            ppr = child(el, "w:pPr")
            level = None
            is_list = numbered = False
            depth = 0
            if ppr is not None:
                outline, style = child(ppr, "w:outlineLvl"), child(ppr, "w:pStyle")
                if outline is not None and (A(outline, "w:val") or "").isdigit() and int(A(outline, "w:val")) < 9:
                    level = int(A(outline, "w:val")) + 1
                elif style is not None:
                    level = levels.get(A(style, "w:val") or "")
                numpr, sid = child(ppr, "w:numPr"), (A(style, "w:val") or "") if style is not None else ""
                is_list = numpr is not None or sid in list_styles
                numbered = _ordered(numbering, numpr) if numpr is not None else sid in ordered_styles
                ilvl = child(numpr, "w:ilvl") if numpr is not None else None
                depth = min(int(A(ilvl, "w:val")), 4) if ilvl is not None and (A(ilvl, "w:val") or "").isdigit() else 0
            if text:
                if level:
                    lines.append("#" * min(level + 1, 6) + " " + text.replace("\n", " "))
                elif is_list:
                    pad = "  " * depth
                    lines.append(pad + ("1. " if numbered else "- ") + text.replace("\n", "\n" + pad + "  "))
                else:
                    lines.append(text)
                lines.append("")
            for x in extra:
                lines += [x, ""]
        elif tag == "w:tbl":
            counter["tables"] += 1
            stats["tables"] += 1
            lines.append(f"### Table {counter['tables']}")
            for tr in el:
                if T(tr) != "w:tr":
                    continue
                cells = []
                for tc in tr:
                    if T(tc) != "w:tc":
                        continue
                    parts, extra = [], []
                    for p in descendants(tc, "w:p"):
                        t = w_paragraph(p, stats, extra)
                        if t:
                            parts.append(t.replace("\n", " "))
                    cells.append(" / ".join(parts + extra))
                lines.append("| " + " | ".join(cells) + " |")
            lines.append("")
        elif tag == "w:sdt":
            content = child(el, "w:sdtContent")
            if content is not None:
                docx_blocks(content, styles, stats, lines, counter)
        elif tag == "mc:AlternateContent":
            docx_blocks(branch(el), styles, stats, lines, counter)


def docx_to_md(pkg, name, stats):
    doc = pkg.xml("word/document.xml")
    body = child(doc, "w:body") if doc is not None else None
    if body is None:
        raise ValueError("word/document.xml is missing (not a .docx?)")
    lines = [f"# DOCX extraction: {name}", ""]
    numbering = docx_numbering(pkg)
    docx_blocks(body, docx_styles(pkg, numbering) + (numbering,), stats, lines, {"tables": 0})
    for part, tag, mark, key, title in (("word/footnotes.xml", "w:footnote", "fn", "footnotes", "Footnotes"),
                                        ("word/endnotes.xml", "w:endnote", "en", "endnotes", "Endnotes")):
        notes = pkg.xml(part)
        shown = []
        for fn in notes if notes is not None else []:
            if T(fn) != tag or A(fn, "w:type") in ("separator", "continuationSeparator", "continuationNotice"):
                continue
            text = " ".join(t for t in (w_paragraph(p, stats, []) for p in descendants(fn, "w:p")) if t)
            if text:
                shown.append(f"- [{mark} {A(fn, 'w:id')}] {text}")
        if shown:
            stats[key] = len(shown)
            lines += [f"### {title}", ""] + shown + [""]
    return "\n".join(lines)


# ----------------------------------------------------------------------------- over-long lines
def wrap_long_lines(text, stats):
    """Re-break every line longer than kitlib.LONG_LINE at a space near kitlib.WRAP_AT (table rows
    stay whole: a broken row is no longer a row). Nothing is added or removed but line breaks."""
    out = []
    for line in text.split("\n"):
        if len(line) <= kitlib.LONG_LINE or line.lstrip().startswith("|"):
            out.append(line)
            continue
        stats["longlines"] += 1
        indent = "  " if re.match(r"\s*(?:[-*+]|\d+[.)])\s", line) else ""
        rest, first = line, True
        while len(rest) > kitlib.WRAP_AT:
            cut = rest.rfind(" ", kitlib.WRAP_AT // 2, kitlib.WRAP_AT)
            if cut < 0:                          # no space (long Thai run): break between characters,
                cut = kitlib.WRAP_AT             # never before a combining mark
                while cut > kitlib.WRAP_AT // 2 and unicodedata.category(rest[cut]).startswith("M"):
                    cut -= 1
            out.append(("" if first else indent) + rest[:cut].rstrip())
            rest, first = rest[cut:].lstrip(" "), False
        out.append(("" if first else indent) + rest)
    return "\n".join(out)


# ----------------------------------------------------------------------------- driver
STAT_KEYS = ["slides", "equations", "smartart", "wrapped", "textboxes", "charts", "tables", "footnotes", "endnotes",
             "longlines", "pictures", "ole"]


def extract(root, rel):
    """Extract one source; returns (status, info). status: extracted | cached | skipped | failed."""
    full = rel if os.path.isabs(rel) else os.path.join(root, rel)
    shown = os.path.relpath(full, root).replace(os.sep, "/")
    if not os.path.isfile(full):
        return "skipped", {"path": shown, "why": "not found"}
    ext = os.path.splitext(full)[1].lower()
    is_text = ext in kitlib.TEXT_EXT
    if ext not in kitlib.OFFICE_EXT and not (is_text and kitlib.text_shape(full)[2] > kitlib.LONG_LINE):
        return "skipped", {"path": shown, "why": "only .pptx/.docx and text files with over-long lines need pre-extraction"}
    sha = kitlib.file_sha256(full)
    cache = kitlib.office_cache_path(root, sha)
    cache_rel = os.path.relpath(cache, root).replace(os.sep, "/")
    old = kitlib.office_cache_info(root, sha)
    if old and old.get("extractor", 1) >= kitlib.OFFICE_EXTRACTOR:
        return "cached", {"path": shown, "cache": cache_rel}
    stats = dict.fromkeys(STAT_KEYS, 0)
    pkg = None
    try:
        if is_text:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                md = f.read()
        else:
            pkg = Package(full)
            md = (pptx_to_md if ext == ".pptx" else docx_to_md)(pkg, os.path.basename(full), stats)
    except (zipfile.BadZipFile, ValueError, KeyError, OSError, ET.ParseError) as e:
        if pkg is not None:
            pkg.zip.close()
        return "failed", {"path": shown, "error": f"{type(e).__name__}: {e}" + (
            " (password-protected or not an Office Open XML file?)" if isinstance(e, zipfile.BadZipFile) else "")}
    if pkg is not None:
        pkg.zip.close()
    md = wrap_long_lines(md, stats)
    fields = [f"source: {shown}", f"sha256: {sha}", f"extractor: {kitlib.OFFICE_EXTRACTOR}"]
    fields += [f"{k}: {stats[k]}" for k in STAT_KEYS if stats[k] or (k == "slides" and ext == ".pptx")]
    notes = []
    if stats["equations"]:
        notes.append(f"{stats['equations']} equation(s) were linearised from Office math into [math: …] — "
                     "check any that look ambiguous against the layout (ask for a PDF export)")
    if stats["pictures"] or stats["ole"]:
        notes.append(f"{stats['pictures']} picture(s) and {stats['ole']} embedded object(s) are NOT extracted "
                     "(marked [visual] / [picture] / [object] in place)")
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        f.write("<!-- " + " | ".join(fields) + " -->\n\n")
        if notes:
            f.write("> extractor notes: " + "; ".join(notes) + "\n\n")
        f.write(md)
    before = old.get("extractor", 1) if old else 0
    return "extracted", {"path": shown, "cache": cache_rel, "stats": {k: v for k, v in stats.items() if v},
                         "upgraded_from_v1": bool(old), "upgraded_from": before or None,
                         "recovered": kitlib.office_recovered(stats, max(before, 1))}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help=".pptx / .docx source files (relative to the project root)")
    ap.add_argument("--all", action="store_true", help="every .pptx/.docx under sources/ whose cache is missing or older")
    ap.add_argument("--root", help="book project root (default: current directory or $BOOK_ROOT)")
    args = ap.parse_args()
    root = kitlib.resolve_root(args.root)
    kitlib.require_book_project(root)
    paths = list(args.paths)
    if args.all:
        sources, _ = kitlib.walk_sources(root)
        paths += [rel for rel, full in sources.items() if os.path.splitext(rel)[1].lower() in kitlib.OFFICE_EXT
                  or (os.path.splitext(rel)[1].lower() in kitlib.TEXT_EXT and kitlib.text_shape(full)[2] > kitlib.LONG_LINE)]
    out = {"extractor": kitlib.OFFICE_EXTRACTOR, "extracted": [], "cached": 0, "skipped": [], "failed": []}
    for p in paths:
        status, info = extract(root, p)
        if status == "cached":
            out["cached"] += 1
        else:
            out[status].append(info)
    if not paths:
        out["note"] = "nothing to do — pass source paths or --all"
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
