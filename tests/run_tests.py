#!/usr/bin/env python3
"""Regression suite for book-kit v11.6 (no test framework needed).

  python3 tests/run_tests.py            # script battery (standard library only)
  python3 tests/run_tests.py --browser  # + real-browser tests of the built book (needs Playwright + Chromium)

Every case builds a throw-away project from tests/fixtures (the same plan serves both summary
levels) and drives the real scripts. Exit code 0 = all passed.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_fixture import (FIX, REPO, SCRIPTS, SOURCES, copy_drafts, extraction_text, make_project,  # noqa: E402
                          run, set_config, source_text)

PLUGIN = os.path.join(REPO, "plugins", "book-kit")
TEMPLATES = os.path.join(PLUGIN, "templates")
RESULTS = []
TMP = tempfile.mkdtemp(prefix="bookkit-tests-")


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   <- {str(detail)[:400]}"))


def J(proc):
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return {"_stdout": proc.stdout, "_stderr": proc.stderr}


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def edit(path, old, new, count=1):
    text = read(path)
    assert old in text, f"{old[:40]!r} not in {path}"
    write(path, text.replace(old, new, count))


def project(name, level=2):
    return make_project(os.path.join(TMP, name), level)


def build(root, *args):
    p = run("build_book.py", *args, root=root)
    return p.returncode, J(p)


def validate(root):
    p = run("validate_book.py", root=root)
    return p.returncode, J(p)


def scan(root):
    return J(run("scan_sources.py", "--status", root=root))


def sync(root, *args):
    p = run("sync_state.py", *args, root=root)
    return p.returncode, J(p)


def codes(report, key="problems"):
    return [x["code"] for x in report.get(key, [])]


def draft(root, cid, level=2):
    return os.path.join(root, ".book-state", "drafts", f"L{level}", f"ch-{cid}.html")


def page(root, name):
    return os.path.join(root, "book", name)


def plan_path(root):
    return os.path.join(root, ".book-state", "plan", "book-plan.json")


def coverage_path(root):
    return os.path.join(root, ".book-state", "plan", "coverage.json")


def extraction(root, rel):
    return os.path.join(root, ".book-state", "extractions", *rel.split("/"))


def load_plan(root):
    return json.loads(read(plan_path(root)))


def save_plan(root, plan):
    write(plan_path(root), json.dumps(plan, ensure_ascii=False, indent=1))


def section(plan, sid):
    return next(s for ch in plan["chapters"] for s in ch["sections"] if s["id"] == sid)


def book_data(root):
    text = read(page(root, "assets/book-data.js"))
    return json.loads(text[text.index("{"):text.rindex("}") + 1])


def touch_draft(root, cid, level=2):
    """What a writer does at the end of every run: bump the stamp's rev."""
    text = read(draft(root, cid, level))
    m = re.search(r'(<!-- book-kit:draft chapter="[^"]*" level="\d+")(?: rev="(\d+)")?( -->)', text)
    write(draft(root, cid, level), text.replace(m.group(0), f'{m.group(1)} rev="{int(m.group(2) or 0) + 1}"{m.group(3)}', 1))


# ----------------------------------------------------------------------------- cases
def t_guards():
    empty = os.path.join(TMP, "not-a-project")
    os.makedirs(empty)
    for script, args in (("scan_sources.py", ("--status",)), ("validate_book.py", ()), ("build_book.py", ()),
                         ("sync_state.py", ("--stamp",)), ("extract_office.py", ("x.pptx",))):
        check(f"guard: {script} refuses a non-project (exit 2)", run(script, *args, root=empty).returncode == 2)
    p = run("make_palette.py", "--check", root=empty)
    check("make_palette --check works outside a project and passes", p.returncode == 0 and J(p).get("status") == "PASS", p.stdout[:200])


def t_init():
    root = os.path.join(TMP, "init")
    os.makedirs(root)
    a = J(run("init_project.py", "--title", "ทดสอบ", root=root))
    cfg = json.loads(read(os.path.join(root, "book.config.json")))
    check("init: scaffolds config with level 2, palette and parallelism",
          cfg["content"]["level"] == 2 and cfg["ui"]["palette"] == "notebook"
          and cfg["pipeline"]["max_parallel_agents"] == 6 and cfg["book"]["title"] == "ทดสอบ", cfg)
    check("init: no dead config keys are scaffolded",
          not {"english_terms_on_first_use", "supplement_policy", "figures"} & set(cfg["content"]), cfg["content"])
    check("init: CLAUDE.md routes design and level requests", "/book-kit:design" in read(os.path.join(root, "CLAUDE.md"))
          and "content.level" in read(os.path.join(root, "CLAUDE.md")))
    perms = json.loads(read(os.path.join(root, ".claude", "settings.json")))["permissions"]
    check("init: sources/ and book/ are denied to the edit tools; state and config are allowed",
          {"Edit(sources/**)", "Edit(book/**)"} <= set(perms["deny"]) and "Bash(python3 *)" in perms["allow"]
          and "Edit(.book-state/**)" in perms["allow"] and "Edit(book/**)" not in perms["allow"], perms)
    b = J(run("init_project.py", root=root))
    check("init: idempotent (second run creates nothing)", a.get("created") and not b.get("created"), b)
    old = os.path.join(TMP, "init-old")
    write(os.path.join(old, ".claude", "settings.json"), json.dumps({"permissions": {"allow": ["Edit(book/**)", "Read(x)"], "deny": []}, "x": 1}))
    c = J(run("init_project.py", root=old))
    perms = json.loads(read(os.path.join(old, ".claude", "settings.json")))
    check("init: a v11.0 project loses the allow rule for book/ and keeps its other settings",
          "Edit(book/**)" not in perms["permissions"]["allow"] and "Read(x)" in perms["permissions"]["allow"]
          and perms["x"] == 1 and c.get("settingsRulesRemoved") == ["allow: Edit(book/**)"], c)
    write(os.path.join(root, "templates", "chapter-shell.html"), "<html><body>{{CONTENT_HTML}}</body></html>")
    c = J(run("init_project.py", root=root))
    check("init: reports a pre-v11 templates/ override", "legacyTemplates" in c, c)


def t_build_level2():
    root = project("l2")
    s = scan(root)
    check("scan: diff + config + level blocks", s["summary"]["added"] == 6 and s["config"]["level"] == 2
          and s["config"]["level_name"] == "study" and s["level"]["write_full"] == []
          and s["level"]["write_delta"] == {} and s["kit"].startswith("11.6"), s)
    check("scan: nothing has to be read when every source has a current extraction (resume without re-reading)",
          s["extract"] == [] and "state" not in s and "stamp" not in s, s.get("extract"))
    rc, b = build(root)
    check("build: level 2 builds", rc == 0 and b.get("status") == "OK" and b["chapters"] == 4 and b["sections"] == 12, b)
    rc, v = validate(root)
    check("validate: level-2 sample is PASS with 0 problems and 0 warnings",
          rc == 0 and v["status"] == "PASS" and not v["warnings"], (codes(v), v.get("warnings")))
    cov = json.loads(read(coverage_path(root)))
    check("coverage.json is generated from the plan (44 units, one merged)", len(cov) == 44
          and cov["ext:ch2/2.3-review.md#U1"] == {"state": "merged", "into": "2.1"}
          and cov["ext:ch1/1-intro.md#U1"] == {"state": "represented", "section": "1"}, len(cov))
    ch2, ch1, idx = read(page(root, "ch-2.html")), read(page(root, "ch-1.html")), read(page(root, "index.html"))
    check("page: level / tab / palette stamps", 'data-level="2"' in ch2 and 'data-tab="2"' in ch2 and 'data-palette="notebook"' in ch2)
    check("page: section numbers get a styling hook", '<span class="sec-num">2.1</span>' in ch2
          and '<span class="sec-num">2.2.2.1</span>' in ch2)
    check("page: 4-level nesting anchors survive", 'id="sec-2-2-2-1"' in ch2 and "<h4" in ch2)
    check("page: dotless chapter is anchored on the h1", '<h1 id="sec-1">' in ch1)
    check("toc: dotless chapter links with its fragment, others carry a twisty",
          'href="ch-1.html#sec-1"' in ch2 and ch2.count('class="twisty"') == 3)
    check("toc: current chapter expanded, others collapsed", 'class="toc-ch active" data-id="2"' in ch2
          and 'class="toc-ch collapsed" data-id="3"' in ch2)
    check("index: agenda lists every section with depth classes", idx.count('class="agenda-ch"') == 4
          and 'class="d4"><a href="ch-2.html#sec-2-2-2-1"' in idx)
    check("index: no draft-sha meta, level label on the cover", "book-kit:draft-sha" not in idx and "ฉบับเรียบเรียงใหม่" in idx)
    data = book_data(root)
    check("book-data: sections, palettes, UI strings and an (empty) id history", len(data["sections"]) == 12
          and len(data["palettes"]) == 4 and data["level"] == 2 and "read_label" in data["t"] and data["slug"]
          and data["idHistory"] == [], data.keys())
    theme = read(page(root, "assets/theme.css"))
    check("theme.css: complete blocks per palette and theme + localized labels",
          'html[data-palette="ocean"][data-theme="dark"]{' in theme and '--l-def:"นิยาม"' in theme and ":root{--bg:" in theme)
    check("theme.css: follows the system dark theme when JavaScript is off",
          '@media (prefers-color-scheme: dark){html:not([data-theme])[data-palette="notebook"]{' in theme)
    check("assets: fonts and scripts copied", os.path.isfile(page(root, "assets/fonts/text-thai-400.woff2"))
          and os.path.isfile(page(root, "assets/app.js")) and os.path.isfile(page(root, "assets/style.css")))
    ledger = json.loads(read(os.path.join(root, ".book-state", "drafts", "L2", "inputs.json")))
    check("build: records what each draft was written from", set(ledger["chapters"]) == {"1", "2", "3", "4"}
          and len(ledger["chapters"]["2"]["sections"]) == 6 and ledger["chapters"]["2"]["draft_sha"], ledger.keys())
    rc, b2 = build(root)
    check("build: idempotent — a second run writes nothing", rc == 0 and b2["written"] == [], b2.get("written"))
    slug = data["slug"]
    set_config(root, title="ชื่อใหม่ทั้งหมด")
    build(root)
    check("build: slug (reader progress key) survives a title change", book_data(root)["slug"] == slug
          and "ชื่อใหม่ทั้งหมด" in read(page(root, "index.html")))
    rc, c = build(root, "--check")
    check("build --check validates inputs without writing", rc == 0 and c.get("checked") is True)
    return root


def t_level_store():
    root = project("switch")
    build(root)
    set_config(root, level=1)
    s = scan(root)
    check("level switch: every chapter needs a first draft at the new level; the old level stays cached",
          s["level"]["write_full"] == ["1", "2", "3", "4"] and s["level"]["config"] == 1 and s["level"]["book"] == 2
          and s["level"]["other_levels_cached"] == {"2": ["1", "2", "3", "4"]}, s["level"])
    before = read(page(root, "ch-2.html"))
    rc, b = build(root)
    check("level switch: build refuses while drafts of the level are missing and writes nothing",
          rc == 1 and codes(b, "errors").count("draft.missing") == 4 and read(page(root, "ch-2.html")) == before, b)
    rc, v = validate(root)
    check("level switch: validator fails pages built at the other level", rc == 1 and "book.level" in codes(v)
          and "draft.missing" in codes(v), codes(v))
    os.makedirs(os.path.dirname(draft(root, "1", 1)), exist_ok=True)
    shutil.copyfile(os.path.join(FIX, "drafts", "L1", "ch-1.html"), draft(root, "1", 1))
    check("level switch: resumable — only unwritten chapters remain", scan(root)["level"]["write_full"] == ["2", "3", "4"])
    copy_drafts(root, 1)
    rc, b = build(root)
    rc2, v = validate(root)
    ch2 = read(page(root, "ch-2.html"))
    check("level switch: level-1 drafts build and validate clean (same plan, coverage, supplements)",
          rc == 0 and rc2 == 0 and not v["warnings"] and 'data-level="1"' in ch2 and "callout recall" in ch2
          and "ฉบับทบทวน" in ch2, (codes(v), v.get("warnings")))
    set_config(root, level=2)
    s = scan(root)
    rc, b = build(root)
    rc2, v = validate(root)
    check("level switch back: the cached level needs no writer at all (zero tokens) and validates clean",
          s["level"]["write_full"] == [] and s["level"]["write_delta"] == {} and rc == 0 and rc2 == 0
          and 'data-level="2"' in read(page(root, "ch-2.html")) and not v["warnings"], (s["level"], codes(v)))
    shutil.copyfile(draft(root, "3", 1), draft(root, "3", 2))
    rc, b = build(root)
    check("level store: a draft stamped with another level than its store is refused", rc == 1
          and codes(b, "errors") == ["draft.level"], b.get("errors"))
    l1 = sum(len(read(os.path.join(FIX, "drafts", "L1", f"ch-{c}.html"))) for c in "1234")
    l2 = sum(len(read(os.path.join(FIX, "drafts", "L2", f"ch-{c}.html"))) for c in "1234")
    check("fixtures: level 1 is denser than level 2 with identical anchors", l1 < l2 and all(
        set(re.findall(r'id="(sec-[\d-]+)"', read(os.path.join(FIX, "drafts", "L1", f"ch-{c}.html"))))
        == set(re.findall(r'id="(sec-[\d-]+)"', read(os.path.join(FIX, "drafts", "L2", f"ch-{c}.html")))) for c in "1234"),
        (l1, l2))
    # a v11.0 project: one draft set directly in .book-state/drafts/
    old = project("legacy-layout")
    base = os.path.join(old, ".book-state", "drafts")
    for name in os.listdir(os.path.join(base, "L2")):
        os.replace(os.path.join(base, "L2", name), os.path.join(base, name))
    os.rmdir(os.path.join(base, "L2"))
    s = scan(old)
    rc, b = build(old)
    check("migration: v11.0 drafts move into their level's store once, losslessly", len(s.get("migrated", [])) == 4
          and os.path.isfile(draft(old, "2")) and not os.path.exists(os.path.join(base, "ch-2.html"))
          and rc == 0 and "migrated" not in scan(old), s.get("migrated"))


def t_freshness_and_supplements():
    root = project("fresh")
    build(root)
    edit(draft(root, "3"), '<h2 id="sec-3-2">', '<p>แก้ไขภายหลัง</p>\n<h2 id="sec-3-2">')
    rc, v = validate(root)
    check("freshness: a draft edited after the build fails book.stale_page", rc == 1 and codes(v) == ["book.stale_page"], codes(v))
    build(root)
    check("freshness: rebuilding clears it", validate(root)[0] == 0)
    edit(draft(root, "3"), ' data-supplement="S-3.3-a"', "")
    build(root)
    rc, v = validate(root)
    check("supplements: a planned supplement missing from a stamped draft blocks", rc == 1 and "supplement.missing" in codes(v), codes(v))
    edit(draft(root, "3"), '<figure id="fig-3-3-a">', '<figure id="fig-3-3-a" data-supplement="S-9.9-z">')
    build(root)
    rc, v = validate(root)
    check("supplements: an unplanned supplement blocks too", rc == 1 and {"supplement.missing", "supplement.unplanned"} <= set(codes(v)), codes(v))
    text = read(draft(root, "3"))
    write(draft(root, "3"), text.split("\n", 1)[1])          # drop the stamp -> pre-v11 draft
    build(root)
    rc, v = validate(root)
    check("supplements: pre-v11 (unstamped) drafts only warn", rc == 0 and {"supplement.missing", "supplement.unplanned"} <= set(codes(v, "warnings")),
          (codes(v), codes(v, "warnings")))
    plan = load_plan(root)
    plan["chapters"][1]["sections"][0]["supplements"] = [{"id": "S-3.3-a", "type": "figure", "reason": "dup"}]
    save_plan(root, plan)
    check("plan: duplicate supplement ids are rejected", "plan.supplement_dup" in codes(validate(root)[1]))
    root = project("supp-place")
    plan = load_plan(root)
    supp = section(plan, "3.3").pop("supplements")
    section(plan, "3.1")["supplements"] = supp
    save_plan(root, plan)
    build(root)
    rc, v = validate(root)
    check("supplements: one that sits in another section than planned is reported for the auditor",
          "supplement.misplaced" in codes(v, "warnings") and "supplement.missing" not in codes(v), (codes(v), codes(v, "warnings")))


def t_level1_form():
    root = project("form", level=1)
    build(root)
    edit(draft(root, "2", 1), '<h2 id="sec-2-3">', "<p>" + "ข้อความยาวที่ไม่ควรอยู่ในฉบับทบทวน " * 14 + '</p>\n<h2 id="sec-2-3">')
    text = read(draft(root, "4", 1))
    write(draft(root, "4", 1), text[:text.index('<div class="callout recall">')])
    text = read(draft(root, "1", 1))
    a = text.index('<div class="callout summary">')
    write(draft(root, "1", 1), text[:a] + text[text.index('<div class="callout recall">'):])
    build(root)
    rc, v = validate(root)
    w = codes(v, "warnings")
    check("level 1: long prose, a missing recall block and a missing summary are reported (non-blocking)",
          rc == 0 and {"level.long_paragraph", "level.recall_missing", "chapter.summary_missing"} <= set(w), (codes(v), w))
    set_config(root, raw={"content": {"recall_questions": False}})
    build(root)
    check("level 1: recall questions are optional via content.recall_questions",
          "level.recall_missing" not in codes(validate(root)[1], "warnings"))
    l2 = project("form2")
    edit(draft(l2, "2"), '<h2 id="sec-2-3">', "<p>" + "ย่อหน้ายาวในฉบับเรียบเรียง " * 20 + '</p>\n<h2 id="sec-2-3">')
    build(l2)
    check("level 2: long paragraphs are not flagged", "level.long_paragraph" not in codes(validate(l2)[1], "warnings"))


def t_config():
    root = project("cfg")
    set_config(root, level=3)
    rc, b = build(root)
    rc2, v = validate(root)
    s = scan(root)
    check("config: an invalid level stops the build and fails validation",
          rc == 1 and "config.level" in codes(b, "errors") and "config.level" in codes(v) and s["config"].get("issues"), (b, codes(v)))
    set_config(root, level=2.0)
    check("config: 2.0 and \"2\" are accepted as level 2", build(root)[0] == 0)
    set_config(root, level="2", raw={"ui": {"accent": "#ff0000", "palette": "nope"}})
    rc, b = build(root)
    rc2, v = validate(root)
    w = codes(v, "warnings")
    check("config: string level accepted; deprecated ui.accent and unknown palette warn and fall back",
          rc == 0 and rc2 == 0 and "config.deprecated" in w and "config.palette" in w
          and 'data-palette="notebook"' in read(page(root, "index.html")), (b.get("errors"), w))
    set_config(root, raw={"ui": {"palette": "custom", "custom_palette": {
        "label": "ของฉัน", "base": "ocean", "paper": "warm", "chroma": 9,
        "hues": {"primary": "#0f766e", "summary": 95, "bogus": 10}}}})
    write(os.path.join(root, "book.config.json"), read(os.path.join(root, "book.config.json")).replace('"accent": "#ff0000",', ""))
    rc, b = build(root)
    p = run("make_palette.py", "--check", root=root)
    data = book_data(root)
    check("palette: custom palette from config is generated, selectable and AA-clean",
          rc == 0 and p.returncode == 0 and J(p)["status"] == "PASS" and "custom" in J(p)["palettes"]
          and data["palette"] == "custom" and {"name": "custom", "label": "ของฉัน"} in data["palettes"]
          and 'html[data-palette="custom"]{' in read(page(root, "assets/theme.css"))
          and 'data-palette="custom"' in read(page(root, "ch-1.html")), (b, p.stdout[:300]))
    check("palette: invalid custom keys are reported, not fatal", "config.palette" in codes(b, "warnings"), b.get("warnings"))
    set_config(root, language="en", raw={"ui": {"palette": "vivid", "features": {"math_katex_cdn": True, "mermaid_cdn": True}}})
    build(root)
    rc, v = validate(root)
    idx = read(page(root, "index.html"))
    check("i18n: language en switches UI strings and <html lang>", '<html lang="en"' in idx and "Contents" in idx
          and "Study edition" in idx and '--l-def:"Definition"' in read(page(root, "assets/theme.css")), codes(v))
    w = sync(root, "--plan")[1]["write"]
    check("i18n: chapters written in another language than book.language are stale as a whole (v11.3)",
          rc == 1 and set(codes(v)) == {"draft.stale"} and "another language" in v["problems"][0]["detail"]
          and all(x["mode"] == "full" and "language" in x.get("reason", "") for x in w.values()) and len(w) == 4, (codes(v), w))
    for cid in w:
        touch_draft(root, cid)                 # the writers wrote every chapter again
    build(root)
    check("i18n: once rewritten the chapters are current in the new language", validate(root)[0] == 0
          and sync(root, "--plan")[1]["write"] == {}, codes(validate(root)[1]))
    check("features: KaTeX auto-render and Mermaid are injected on request",
          "auto-render.min.js" in idx and "left:'\\\\(',right:'\\\\)'" in idx and "mermaid.esm.min.mjs" in idx)
    set_config(root, raw={"pipeline": {"max_parallel_agents": 4, "models": {"writer": "opus", "robot": "x", "analyst": 3}}})
    s = scan(root)
    check("config: per-role model overrides are passed on; unknown roles and non-strings are reported",
          s["config"].get("models") == {"writer": "opus"} and len(s["config"]["issues"]) == 2
          and s["config"]["max_parallel_agents"] == 4, s["config"])


def t_structure_changes():
    root = project("struct")
    build(root)
    plan = load_plan(root)
    plan["chapters"] = plan["chapters"][:3]
    save_plan(root, plan)
    rc, b = build(root)
    check("build: the page of a chapter that left the plan is removed", rc == 0 and b["removed"] == ["ch-4.html"]
          and not os.path.exists(page(root, "ch-4.html")) and "ch-4.html" not in read(page(root, "index.html")), b)
    write(page(root, "notes.html"), "<html><body>mine</body></html>")
    build(root)
    check("build: files it did not generate are never deleted", os.path.exists(page(root, "notes.html")))
    root = project("ph")
    edit(draft(root, "1"), '<div class="callout summary">',
         '<p><code>{{BOOK_TITLE}}</code> และ <code>{{SOMETHING_ELSE}}</code></p>\n<div class="callout summary">')
    build(root)
    ch1 = read(page(root, "ch-1.html"))
    rc, v = validate(root)
    check("build: template-like text in learner content is kept literally and never mistaken for a placeholder",
          rc == 0 and "&#123;&#123;BOOK_TITLE}}" in ch1 and "{{SOMETHING_ELSE}}" in ch1, codes(v))
    os.remove(draft(root, "2"))
    rc, b = build(root)
    check("build: a missing draft stops the build; scan lists the chapter for a full write", rc == 1
          and "draft.missing" in codes(b, "errors") and scan(root)["level"]["write_full"] == ["2"], b.get("errors"))


def t_template_override():
    root = project("tpl")
    old = os.path.join(root, "templates")
    write(os.path.join(old, "chapter-shell.html"), '<html lang="{{LANG}}"><body>{{TOC_HTML}}{{CONTENT_HTML}}</body></html>')
    write(os.path.join(old, "book-shell.html"), '<html lang="{{LANG}}"><body>{{TOC_HTML}}{{AGENDA_HTML}}</body></html>')
    rc, b = build(root)
    check("templates: a pre-v11 project override is refused with nothing written",
          rc == 1 and "templates.contract" in codes(b, "errors") and not os.path.exists(page(root, "index.html")), b)
    shutil.rmtree(old)
    shutil.copytree(TEMPLATES, old)
    edit(os.path.join(old, "book-shell.html"), "{{T_START}}", "{{T_START}} ✦")
    rc, b = build(root)
    rc2, v = validate(root)
    check("templates: a current project override takes precedence", rc == 0 and rc2 == 0 and "✦" in read(page(root, "index.html"))
          and v["stats"]["templates"] == old, (b.get("errors"), codes(v)))


def t_coverage():
    root = project("cov")
    plan = load_plan(root)
    section(plan, "1")["covers"] = ["ext:ch1/1-intro.md#U1-U5"]
    section(plan, "4.2")["covers"] = ["ext:ch4/4-normal.md#U4-U5"]
    section(plan, "3.3")["covers"] = ["ext:ch3/3-probability.md#U9-10"]          # "U9-10" is accepted like "U9-U10"
    plan["omitted"] = [
        {"ref": "ext:ch1/1-intro.md#U6", "state": "omitted_justified", "reason": "dropped for brevity"},
        {"ref": "ext:ch4/4-normal.md#U7", "state": "omitted_justified", "reason": "ตัดออกเพื่อความกระชับ"},
        {"ref": "ext:ch4/4-normal.md#U6", "state": "omitted_justified", "reason": "not needed at level 1"},
        {"ref": "ext:ch3/3-probability.md#U12", "state": "omitted_justified", "reason": "tokenization is out of the teaching scope"},
        {"ref": "ext:ch3/3-probability.md#U11", "state": "administrative"}]
    save_plan(root, plan)
    build(root)
    rc, v = validate(root)
    w = codes(v, "warnings")
    check("coverage: brevity- and level-justified omissions warn (EN, TH, level); semantic reasons do not",
          rc == 0 and w.count("coverage.brevity_reason") == 3, (codes(v), w))
    check("coverage: omitting a unit the analyst marked important is put before the auditor",
          w.count("coverage.priority_omitted") == 5, w)
    cov = json.loads(read(coverage_path(root)))
    check("coverage.json mirrors the plan's omissions", cov["ext:ch3/3-probability.md#U11"] == {"state": "administrative"}
          and cov["ext:ch1/1-intro.md#U6"]["reason"] == "dropped for brevity", cov.get("ext:ch1/1-intro.md#U6"))
    root = project("cov2")
    plan = load_plan(root)
    section(plan, "1")["covers"] = ["ext:ch1/1-intro.md#U4-U6"]
    plan["omitted"] = [{"ref": "ext:ch1/1-intro.md#U1", "state": "unresolved"},
                       {"ref": "ext:ch1/1-intro.md#U3", "state": "omitted_justified", "reason": ""}]
    save_plan(root, plan)
    build(root)
    c = codes(validate(root)[1])
    check("coverage: unresolved, gap and empty reason block", {"coverage.unresolved", "coverage.gap", "coverage.reason"} <= set(c), c)
    # a v11.0 project: no "omitted" in the plan, omissions live in a hand-written coverage.json
    root = project("cov-legacy")
    plan = load_plan(root)
    del plan["omitted"]
    s21 = section(plan, "2.1")
    s21["covers"] += s21.pop("merged")
    section(plan, "1")["covers"] = ["ext:ch1/1-intro.md#U1-U5"]
    save_plan(root, plan)
    write(coverage_path(root), json.dumps({"ext:ch1/1-intro.md#U6": {"state": "omitted_justified", "reason": "outside the teaching scope"},
                                           "ext:ch1/1-intro.md#U1": {"state": "represented", "section": "1"}}))
    build(root)
    rc, v = validate(root)
    rc2, v2 = validate(root)
    check("coverage: a v11.0 plan keeps its omissions from coverage.json (reported once per run, stable across runs)",
          rc == 0 and rc2 == 0 and codes(v, "warnings").count("plan.legacy_coverage") == 1
          and json.loads(read(coverage_path(root)))["ext:ch1/1-intro.md#U6"]["state"] == "omitted_justified", (codes(v), codes(v, "warnings")))
    plan = load_plan(root)
    section(plan, "1")["covers"] = ["ext:ch1/1-intro.md#U1-U4"]
    save_plan(root, plan)
    check("coverage: a unit the old ledger calls represented but no section covers is a gap (ledger and plan cannot disagree)",
          "coverage.gap" in codes(validate(root)[1]))
    root = project("cov-links")
    build(root)
    ch3 = read(page(root, "ch-3.html"))
    write(page(root, "ch-3.html"), ch3.replace('<a href="ch-2.html#sec-2-3">', '<a href="ch-2.html#sec-2-9">', 1))
    c = codes(validate(root)[1])
    check("toc/links: a missing TOC entry and a broken anchor block", "toc.missing" in c and "link.anchor" in c, c)
    write(page(root, "ch-3.html"), ch3.replace('<html lang="th"', '<html lang="en"', 1).replace('id="theme-toggle"', 'id="x"', 1))
    c = codes(validate(root)[1])
    check("ui: wrong lang and a missing marker block", "ui.lang" in c and "ui.marker" in c, c)
    build(root)
    plan = load_plan(root)
    plan["chapters"][0]["sections"].append({"id": "1.1", "title_th": "x", "covers": []})
    save_plan(root, plan)
    check("plan: dotless section mixed with dotted siblings is rejected", "plan.dotless_mix" in codes(validate(root)[1]))


def t_integrity():
    """The accounting chain: what the validator accepts is what the sources contain (F11)."""
    def fresh(name, mutate_plan=None):
        root = project(name)
        if mutate_plan:
            plan = load_plan(root)
            mutate_plan(plan)
            save_plan(root, plan)
        return root
    root = fresh("int-more")
    write(extraction(root, "ch3/3-probability.md"), read(extraction(root, "ch3/3-probability.md")).replace(
        "# Key verbatim", "## U13 [§13] (critical) one more formula\n- teaches: x\n\n## U14 [§14] (critical) and another\n- teaches: y\n\n# Key verbatim"))
    build(root)
    rc, v = validate(root)
    check("integrity: units are counted from the body — two the frontmatter does not announce are still demanded",
          rc == 1 and codes(v) == ["coverage.gap"] and "U13–U14" in v["problems"][0]["detail"], v["problems"])
    root = fresh("int-less")
    text = read(extraction(root, "ch3/3-probability.md"))
    write(extraction(root, "ch3/3-probability.md"), text[:text.index("## U9 ")] + "# Key verbatim\n\nnone\n")
    build(root)
    c = codes(validate(root)[1])
    check("integrity: a plan that covers units the extraction does not contain is rejected", "plan.covers_ref" in c, c)
    root = fresh("int-ref", lambda p: section(p, "4.1").update(covers=["ext:ch4/does-not-exist.md#U1-U3", "ext:ch4/4-normal.md#U99", "nonsense"]))
    build(root)
    v = validate(root)[1]
    check("integrity: covers pointing at a missing extraction, a missing unit or nothing are rejected",
          codes(v).count("plan.covers_ref") == 3 and "coverage.gap" in codes(v), codes(v))
    root = fresh("int-dup", lambda p: section(p, "4.2").update(covers=["ext:ch4/4-normal.md#U3-U7"]))
    build(root)
    check("integrity: a unit assigned to two sections is rejected (exactly one state)", "coverage.duplicate" in codes(validate(root)[1]))
    root = fresh("int-num")
    edit(extraction(root, "ch1/1-intro.md"), "## U3 ", "## U9 ")
    rc, s = sync(root, "--stamp")
    check("integrity: unit numbers with gaps are rejected before anything is planned", rc == 1
          and "extraction.unit_numbering" in codes(s), codes(s))
    # stamping: agents never copy hashes or count units
    root = fresh("int-stamp")
    src = "sources/ch4/4 normal.md"
    write(extraction(root, "ch4/4-normal.md"), extraction_text(src, "4", 7, "ch4/4-normal.md", stamped=False))
    v = validate(root)[1]
    check("integrity: an extraction without sha256 blocks (extraction.unstamped) and is not listed for re-reading",
          "extraction.unstamped" in codes(v) and scan(root)["extract"] == [] and scan(root)["stamp"]["count"] == 1, codes(v))
    rc, s = sync(root, "--stamp")
    text = read(extraction(root, "ch4/4-normal.md"))
    check("stamp: sha256, unit count and date are written by the script", rc == 0 and s["stamped"] == ["ch4/4-normal.md"]
          and re.search(r"^sha256: [0-9a-f]{64}$", text, re.M) and "units: 7" in text and "extracted: " in text
          and "stamp" not in scan(root), (s, text[:200]))
    write(extraction(root, "ch4/4-normal.md"), extraction_text(src, "4", 7, "ch4/4-normal.md", stamped=False).replace(
        "# Key verbatim", "<!-- continue -->\n\n# Key verbatim"))
    rc, s = sync(root, "--stamp")
    sc = scan(root)
    check("stamp: an unfinished extraction is not stamped, blocks, and stays on the read list",
          rc == 1 and s["unfinished"] == ["ch4/4-normal.md"] and "extraction.incomplete" in codes(s)
          and [x["reason"] for x in sc["extract"]] == ["incomplete"], (s, sc["extract"]))
    # a source that changed after it was extracted
    root = fresh("int-outdated")
    build(root)
    run("scan_sources.py", "--commit", root=root)
    write(os.path.join(root, "sources", "ch4", "4 normal.md"), source_text("sources/ch4/4 normal.md", 7) + "\n## added later\n")
    sc = scan(root)
    rc, v = validate(root)
    check("freshness: a source edited after extraction is on the read list and blocks validation (extraction.outdated)",
          [(x["path"], x["reason"]) for x in sc["extract"]] == [("sources/ch4/4 normal.md", "changed")]
          and rc == 1 and codes(v) == ["extraction.outdated"], (sc["extract"], codes(v)))
    run("scan_sources.py", "--commit", root=root)
    check("freshness: committing the manifest cannot hide it", [x["reason"] for x in scan(root)["extract"]] == ["changed"]
          and "extraction.outdated" in codes(validate(root)[1]))


def tiny_pdf(path, pages):
    """A minimal multi-page PDF written by hand (no library needed)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Count %d /Kids [%s] >>" % (pages, " ".join(f"{3 + i} 0 R" for i in range(pages)))]
    objs += ["<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>" for _ in range(pages)]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(out)


def t_pdf_and_paths():
    sys.path.insert(0, SCRIPTS)
    import kitlib
    root = project("pdf")
    pdf = "sources/ch4/4.3 long.pdf"
    tiny_pdf(os.path.join(root, *pdf.split("/")), 45)
    item = [x for x in scan(root)["extract"] if x["path"] == pdf][0]
    check("scan: tells the analyst where the extraction of a source belongs", item["extraction"] == ".book-state/extractions/ch4/4.3-long.pdf.md"
          and item["reason"] == "new" and item["chapter"] == "4", item)
    if kitlib.pdf_page_count(os.path.join(root, *pdf.split("/"))) is None:
        print("SKIP  PDF page-count checks (neither pypdf nor pdfinfo is available)")
        return

    def units(spans):
        lines = ["---", f"source: {pdf}", 'chapter: "4"', "---", "", "# Units", ""]
        for n, span in enumerate(spans, 1):
            lines += [f"## U{n} [p.{span}] (important) block {n}", "- teaches: x", ""]
        write(extraction(root, "ch4/4.3-long.pdf.md"), "\n".join(lines) + "# Key verbatim\n\nnone\n")
    check("scan: counts the pages of a PDF so the orchestrator can hand out page ranges", item.get("pages") == 45, item)
    units(["1-12", "13-20"])
    rc, y = sync(root, "--stamp")
    check("truncation: a 45-page PDF whose units stop at page 20 blocks", rc == 1 and "extraction.truncated" in codes(y)
          and "pages: 45" in read(extraction(root, "ch4/4.3-long.pdf.md")), codes(y))
    units(["1-12", "13-20", "21-40", "41-45"])
    rc, y = sync(root, "--stamp")
    check("truncation: units that reach the last page pass", "extraction.truncated" not in codes(y)
          and "extraction.locator_gap" not in codes(y, "warnings"), (codes(y), codes(y, "warnings")))
    # a changed source extracted again under another file name: the new text adopts the established path
    src = os.path.join(root, "sources", "ch1", "1 intro.md")
    write(src, read(src) + "\nnew point\n")
    write(extraction(root, "ch1/intro-NEW.md"), extraction_text("sources/ch1/1 intro.md", "1", 7, "ch1/1-intro.md", stamped=False))
    rc, y = sync(root, "--stamp")
    check("stamp: a re-extraction written to a new file takes over the path the plan references",
          y.get("adopted") == [{"from": "ch1/intro-NEW.md", "to": "ch1/1-intro.md"}] and not os.path.exists(extraction(root, "ch1/intro-NEW.md"))
          and "## U7 " in read(extraction(root, "ch1/1-intro.md")) and "extraction.duplicate" not in codes(y)
          and "extraction.outdated" not in codes(y), y)


def t_structure():
    """A page may contain nothing the plan does not know, in the plan's shape (F2)."""
    root = project("shape")
    edit(draft(root, "2"), '<h2 id="sec-2-3">', '<h2 id="sec-2-9">2.9 หัวข้อที่ถูกลบออกจาก plan แล้ว</h2>\n<p>เนื้อหาเก่า</p>\n<h2 id="sec-2-3">')
    edit(draft(root, "2"), '<h3 id="sec-2-2-1">', '<h3 id="sec-2-2-1">ซ้ำ</h3>\n<h3 id="sec-2-2-1">')
    edit(draft(root, "2"), '<h3 id="sec-2-2-2">2.2.2', '<h2 id="sec-2-2-2">7.7.7')
    text = read(draft(root, "4"))
    a, b = text.index('<h2 id="sec-4-1">'), text.index('<h2 id="sec-4-2">')
    write(draft(root, "4"), text[:a] + text[b:] + text[a:b])
    build(root)
    rc, v = validate(root)
    c = set(codes(v))
    check("structure: a section that is not in the plan blocks (stale content cannot stay in the book)", "draft.orphan_section" in c, c)
    check("structure: a repeated anchor blocks", "draft.anchor_dup" in c, c)
    check("structure: heading level and visible number must follow the section id", {"draft.heading_level", "draft.heading_number"} <= c, c)
    check("structure: sections must come in plan order", "draft.section_order" in c, c)
    root = project("shape-order")
    plan = load_plan(root)
    ch2 = plan["chapters"][1]["sections"]
    ch2.insert(1, ch2.pop())                                   # 2.3 moved in front of 2.2
    save_plan(root, plan)
    rc, s = sync(root, "--plan")
    check("plan: numbers out of reading order are reported (plan.order)", "plan.order" in codes(s, "warnings"), s.get("warnings"))


def t_stale():
    """A draft that is older than what it was written from is found mechanically (F3)."""
    root = project("stale")
    build(root)
    edit(extraction(root, "ch3/3-probability.md"), "- teaches: point 5", "- teaches: point 5 — the addition rule now needs disjoint events")
    s = scan(root)
    rc, v = validate(root)
    check("stale: a changed unit marks exactly the section that covers it", s["level"]["write_delta"] == {"3": {"changed": ["3.2"]}}
          and s["level"]["current"] == ["1", "2", "4"], s["level"])
    check("stale: validation blocks until the chapter is rewritten", rc == 1 and codes(v) == ["draft.stale"], codes(v))
    rc, p = sync(root, "--plan")
    sl = json.loads(read(os.path.join(root, ".book-state", "plan", "slices", "ch-3.json")))
    check("plan step: prints the write list and puts it into the chapter's slice", p["write"] == {"3": {"mode": "delta", "changed": ["3.2"], "added": [], "removed": [], "reordered": False}}
          and sl["write"]["changed"] == ["3.2"] and sl["draft"] == ".book-state/drafts/L2/ch-3.html"
          and sl["chapter"]["id"] == "3" and sl["extractions"] == [".book-state/extractions/ch3/3-probability.md"], p.get("write"))
    rc, b = build(root)
    check("stale: building does not hide it", codes(b, "warnings") == ["draft.stale"] and validate(root)[0] == 1, b.get("warnings"))
    touch_draft(root, "3")
    build(root)
    check("stale: once the writer has processed the chapter (stamp rev bumped) the book validates",
          validate(root)[0] == 0 and scan(root)["level"]["write_delta"] == {})
    plan = load_plan(root)
    section(plan, "4.1")["title_th"] = "ชื่อใหม่"
    plan["chapters"][3]["sections"].append({"id": "4.3", "title_th": "หัวข้อใหม่", "priority": "important", "covers": []})
    plan["chapters"][1]["sections"] = [x for x in plan["chapters"][1]["sections"] if x["id"] != "2.3"]
    plan["omitted"] = [{"ref": "ext:ch2/2.3-review.md#U2-U4", "state": "omitted_justified", "reason": "outside the teaching scope"}]
    save_plan(root, plan)
    s = scan(root)["level"]["write_delta"]
    c = codes(validate(root)[1])
    check("stale: a retitled, an added and a removed section are told apart",
          s == {"2": {"removed": ["2.3"]}, "4": {"changed": ["4.1"], "added": ["4.3"]}}, s)
    check("stale: the removed section still in the draft is an orphan; the new one is missing", {"draft.stale", "draft.orphan_section", "book.anchor"} <= set(c), c)


def t_scan_lifecycle():
    root = project("scan")
    build(root)
    c = J(run("scan_sources.py", "--commit", root=root))
    s = scan(root)
    check("scan: commit then clean status", c.get("committed") and s["summary"]["unchanged"] == 6 and s["extract"] == [], s["summary"])
    src = os.path.join(root, "sources", "ch4", "4 normal.md")
    write(src, read(src) + "\nextra\n")
    os.rename(os.path.join(root, "sources", "ch1", "1 intro.md"), os.path.join(root, "sources", "ch1", "1 introduction.md"))
    os.remove(os.path.join(root, "sources", "ch2", "2.3 review.md"))
    s = scan(root)
    check("scan: changed / renamed / removed are told apart", s["summary"]["changed"] == 1 and s["summary"]["renamed"] == 1
          and s["summary"]["removed"] == 1, s["summary"])
    check("scan: only the changed file is on the read list; the rename and the removal are state work",
          [x["path"] for x in s["extract"]] == ["sources/ch4/4 normal.md"]
          and s["state"]["renames"] == [{"from": "sources/ch1/1 intro.md", "to": "sources/ch1/1 introduction.md"}]
          and s["state"]["stale"] == ["ch2/2.3-review.md"] and "renumber" not in s["state"], s.get("state"))
    w = codes(validate(root)[1], "warnings")
    check("validate: stale extraction and pending rename are reported", {"extraction.stale", "extraction.rename_pending"} <= set(w), w)
    rc, y = sync(root, "--sources")
    check("sync --sources: remaps the moved source (no re-read) and deletes the removed source's state",
          rc == 0 and [x["to"] for x in y["remapped"]] == ["sources/ch1/1 introduction.md"]
          and y["removedExtractions"] == ["ch2/2.3-review.md"] and not os.path.exists(extraction(root, "ch2/2.3-review.md"))
          and "source: sources/ch1/1 introduction.md" in read(extraction(root, "ch1/1-intro.md")) and "state" not in scan(root), y)
    c = codes(validate(root)[1])
    check("validate: a plan that still covers the removed source is rejected", "plan.covers_ref" in c and "extraction.outdated" in c, c)
    shutil.rmtree(os.path.join(root, "sources"))
    os.makedirs(os.path.join(root, "sources"))
    rc, y = sync(root, "--sources")
    check("sync --sources: refuses to delete everything when sources/ is empty", "refused" in y and os.path.exists(extraction(root, "ch1/1-intro.md")))
    root = project("unsupported")
    for name in ("1 old-deck.ppt", "grades.xlsx", "~$1 intro.docx", ".hidden.md"):
        write(os.path.join(root, "sources", "ch1", name), "x")
    s = scan(root)
    build(root)
    rc, v = validate(root)
    check("unsupported files: reported with a hint, not counted as sources; lock files are ignored",
          [u["path"] for u in s["unsupported"]] == ["sources/ch1/1 old-deck.ppt", "sources/ch1/grades.xlsx"]
          and "PDF" in s["unsupported"][0]["hint"] and s["sourceCount"] == 6 and rc == 0
          and codes(v, "warnings") == ["sources.unsupported", "sources.unsupported"], (s.get("unsupported"), codes(v), codes(v, "warnings")))


def t_renumber():
    """The user renumbers source chapters to insert one: the book follows at zero tokens (F6)."""
    root = project("renum")
    copy_drafts(root, 1)
    edit(draft(root, "2"), '<div class="callout summary">', '<p>ดูต่อที่ <a href="ch-3.html#sec-3-1">3.1</a></p>\n<div class="callout summary">')
    edit(draft(root, "3"), '<div class="callout summary">', '<p>ทบทวน <a href="ch-2.html#sec-2-3">2.3</a></p>\n<div class="callout summary">')
    build(root)
    run("scan_sources.py", "--commit", root=root)
    src = os.path.join(root, "sources")
    os.makedirs(os.path.join(src, "ch5"))
    os.rename(os.path.join(src, "ch4", "4 normal.md"), os.path.join(src, "ch5", "5 normal.md"))
    os.rename(os.path.join(src, "ch3", "3 probability.md"), os.path.join(src, "ch4", "4 probability.md"))
    write(os.path.join(src, "ch3", "3 sampling.md"), "# a new lecture\n")
    write(os.path.join(root, ".book-state", "audits", "audit-1.json"), json.dumps({"id": "A1", "status": "pending_approval", "findings": [
        {"id": "F1", "severity": "major", "type": "clarity", "location": "ch-3.html#sec-3-2", "description": "x", "resolution": "open"},
        {"id": "F2", "severity": "minor", "type": "clarity", "location": "ch-2.html#sec-2-1", "description": "y", "resolution": "open"},
        {"id": "F3", "severity": "minor", "type": "consistency", "location": "ch-4", "description": "z", "resolution": "open"}]}))
    write(os.path.join(root, ".book-state", "audits", "audit-0.json"), json.dumps({"id": "A0", "status": "applied", "findings": [
        {"id": "F1", "location": "ch-3.html#sec-3-1", "resolution": "fixed"}]}))
    s = scan(root)
    check("renumber: the scan derives the chapter shift from the moved files", s["state"].get("renumber") == {"3": "4", "4": "5"}
          and [x["path"] for x in s["extract"]] == ["sources/ch3/3 sampling.md"], s.get("state"))
    rc, y = sync(root, "--sources")
    plan = load_plan(root)
    check("renumber: plan ids, pages and supplement ids follow", rc == 0 and [c["id"] for c in plan["chapters"]] == ["1", "2", "4", "5"]
          and plan["chapters"][2]["page"] == "ch-4.html" and [x["id"] for x in plan["chapters"][2]["sections"]] == ["4.1", "4.2", "4.3"]
          and plan["chapters"][2]["sections"][2]["supplements"][0]["id"] == "S-4.3-a" and plan["idHistory"][0]["map"] == {"3": "4", "4": "5"}, y)
    d4 = read(draft(root, "4"))
    check("renumber: drafts are renamed and rewritten (stamp, anchors, headings, figure and supplement ids)",
          not os.path.exists(draft(root, "3")) and 'chapter="4"' in d4.split("\n")[0] and '<h2 id="sec-4-3">4.3 ' in d4
          and 'data-supplement="S-4.3-a"' in d4 and 'id="fig-4-3-a"' in d4 and "sec-3-" not in d4
          and '<h2 id="sec-5-1">5.1 ' in read(draft(root, "5"))
          and '<a href="ch-4.html#sec-4-1">4.1</a>' in read(draft(root, "2")), d4[:300])
    locs = [f["location"] for f in json.loads(read(os.path.join(root, ".book-state", "audits", "audit-1.json")))["findings"]]
    check("renumber: an open audit report keeps pointing at the same content; closed reports are history",
          locs == ["ch-4.html#sec-4-2", "ch-2.html#sec-2-1", "ch-5"] and y.get("audits_relocated") == ["audit-1.json"]
          and "ch-3.html#sec-3-1" in read(os.path.join(root, ".book-state", "audits", "audit-0.json")), (locs, y.get("audits_relocated")))
    l1 = read(draft(root, "4", 1))
    check("renumber: every level's store follows, including the visible numbers of recall links",
          '<a href="#sec-4-1">4.1</a>' in l1 and "#sec-3-" not in l1 and os.path.isfile(draft(root, "5", 1)), l1[-600:])
    check("renumber: the extraction keeps its file, gets the new source path and chapter",
          'chapter: "4"' in read(extraction(root, "ch3/3-probability.md"))
          and "source: sources/ch4/4 probability.md" in read(extraction(root, "ch3/3-probability.md")))
    s = scan(root)
    check("renumber: no chapter has to be rewritten afterwards", s["level"]["write_full"] == [] and s["level"]["write_delta"] == {}
          and "state" not in s, s["level"])
    rc, b = build(root)
    rc2, v = validate(root)
    check("renumber: the book rebuilds; only the new, unread source is open", rc == 0 and b["removed"] == ["ch-3.html"]
          and codes(v) == ["extraction.missing"] and book_data(root)["idHistory"] == [{"3": "4", "4": "5"}], (b.get("removed"), codes(v)))
    rc, y = sync(root, "--renumber", "2.3=2.4")
    d2 = read(draft(root, "2"))
    check("renumber: a section can be renumbered the same way; links from other chapters follow",
          rc == 0 and '<h2 id="sec-2-4">2.4 ' in d2 and "sec-2-3" not in d2
          and '<a href="ch-2.html#sec-2-4">2.4</a>' in read(draft(root, "4")), y)
    before = read(plan_path(root))
    rc, y = sync(root, "--renumber", "2.1=2.2")
    check("renumber: a map that would collide changes nothing", rc == 1 and codes(y) == ["renumber.collision"] and read(plan_path(root)) == before, y)
    root = project("renum-partial")
    build(root)
    run("scan_sources.py", "--commit", root=root)
    os.makedirs(os.path.join(root, "sources", "ch7"))
    os.rename(os.path.join(root, "sources", "ch2", "2.3 review.md"), os.path.join(root, "sources", "ch7", "7 review.md"))
    s = scan(root)
    check("renumber: moving only part of a chapter is left to the architect", "renumber" not in s["state"]
          and "only part of chapter 2" in s["state"]["renumber_skipped"], s["state"])
    plan = load_plan(root)
    plan["renumber_request"] = ["2.3=2.9"]
    save_plan(root, plan)
    rc, y = sync(root, "--sources", "--plan")
    check("renumber: the architect's renumber_request is applied by the plan step", [x["id"] for x in load_plan(root)["chapters"][1]["sections"]][-1] == "2.9"
          and "renumber_request" not in load_plan(root) and '<h2 id="sec-2-9">2.9 ' in read(draft(root, "2")), y.get("renumbered"))


def t_fuzz():
    """Whatever an agent writes into the state, no script answers with a traceback (F7)."""
    base = project("fuzz-base")
    build(base)

    def case(name, plan=None, raw=None, cfg=None):
        root = os.path.join(TMP, "fuzz-" + name)
        shutil.copytree(base, root)
        if plan:
            p = load_plan(root)
            p = plan(p) or p
            save_plan(root, p)
        for rel, text in (raw or {}).items():
            write(os.path.join(root, rel), text)
        if cfg:
            set_config(root, raw=cfg)
        crashed, statuses = [], []
        for script, args in (("scan_sources.py", ("--status",)), ("build_book.py", ("--check",)),
                             ("sync_state.py", ("--stamp", "--plan")), ("validate_book.py", ())):
            p = run(script, *args, root=root)
            if "Traceback" in p.stderr or "_stdout" in J(p):
                crashed.append(script)
            statuses.append(J(p).get("status"))
        return crashed, statuses

    def put(p, key, value):
        p[key] = value
    shapes = {
        "chapters-null": dict(plan=lambda p: put(p, "chapters", None)),
        "chapters-dict": dict(plan=lambda p: put(p, "chapters", {"1": {}})),
        "plan-list": dict(raw={".book-state/plan/book-plan.json": "[]"}),
        "plan-garbage": dict(raw={".book-state/plan/book-plan.json": "{not json"}),
        "section-string": dict(plan=lambda p: p["chapters"][1]["sections"].append("2.9")),
        "sections-null": dict(plan=lambda p: put(p["chapters"][1], "sections", None)),
        "chapter-string": dict(plan=lambda p: p["chapters"].append("5")),
        "supplements-string": dict(plan=lambda p: put(p["chapters"][1]["sections"][0], "supplements", "S-1")),
        "covers-number": dict(plan=lambda p: put(p["chapters"][1]["sections"][0], "covers", 7)),
        "omitted-string": dict(plan=lambda p: put(p, "omitted", "none")),
        "omitted-items": dict(plan=lambda p: put(p, "omitted", [None, 3, "ext:x#U1", {"ref": 5}])),
        "ids-numeric": dict(plan=lambda p: (put(p["chapters"][0], "id", 1), put(p["chapters"][1]["sections"][0], "id", 2.1))),
        "coverage-list": dict(raw={".book-state/plan/coverage.json": "[]"}),
        "coverage-entries": dict(raw={".book-state/plan/coverage.json": '{"ext:ch1/1-intro.md#U1": "x", "a": null}'},
                                 plan=lambda p: p.pop("omitted")),
        "config-list": dict(raw={"book.config.json": "[]"}),
        "config-strings": dict(cfg={"content": {"level": "two"}, "pipeline": {"models": "opus", "max_parallel_agents": "many"}}),
        "manifest-garbage": dict(raw={".book-state/manifest.json": '{"files": {"a": "b", "c": {"sha256": 5}}}'}),
        "ledger-garbage": dict(raw={".book-state/drafts/L2/inputs.json": '{"chapters": {"2": "x", "3": {"sections": []}}}'}),
        "extraction-empty": dict(raw={".book-state/extractions/ch1/1-intro.md": ""}),
        "extraction-binary": dict(raw={".book-state/extractions/ch1/1-intro.md": "---\nsource: [\nunits: x\n---\n## U0\n## Ux\n## U1 [p.-3] ((critical\n- keys:\n- flags: |||\n"}),
        "audit-garbage": dict(raw={".book-state/audits/audit-2.json": "[1,2]", ".book-state/audits/audit-x.json": "{}"}),
    }
    bad = {name: case(name, **kw)[0] for name, kw in shapes.items()}
    check(f"robustness: {len(shapes)} malformed states x 4 scripts end in a JSON report, never a traceback",
          not any(bad.values()), {k: v for k, v in bad.items() if v})
    crashed, statuses = case("shape-code", plan=lambda p: p["chapters"][1]["sections"].append("2.9"))
    v = J(run("validate_book.py", root=os.path.join(TMP, "fuzz-shape-code")))
    check("robustness: a malformed plan becomes plan.shape, routed to the architect like any plan problem",
          "plan.shape" in codes(v) and v["status"] == "FAIL", codes(v))
    many = os.path.join(TMP, "fuzz-many")
    shutil.copytree(base, many)
    p = load_plan(many)
    for ch in p["chapters"]:
        for s in ch["sections"]:
            s["covers"] = []
    save_plan(many, p)
    v = J(run("validate_book.py", root=many))
    full = json.loads(read(os.path.join(many, ".book-state", "validate-report.json")))
    check("validate: the console report stays short and counts by code; the file is complete",
          len(v["problems"]) <= 40 and v["problemCodes"].get("coverage.gap") == 6 and full["problemCount"] == len(full["problems"]), v["problemCodes"])


def tiny_pptx(path, slides):
    """A minimal .pptx written with the standard library: one text shape per slide."""
    import zipfile
    P = "http://schemas.openxmlformats.org/presentationml/2006/main"
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    REL = "http://schemas.openxmlformats.org/package/2006/relationships"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("ppt/presentation.xml", f'<p:presentation xmlns:p="{P}" xmlns:r="{R}"><p:sldIdLst>' + "".join(
            f'<p:sldId id="{256 + i}" r:id="rId{i + 1}"/>' for i in range(len(slides))) + "</p:sldIdLst></p:presentation>")
        z.writestr("ppt/_rels/presentation.xml.rels", f'<Relationships xmlns="{REL}">' + "".join(
            f'<Relationship Id="rId{i + 1}" Type="{R}/slide" Target="slides/slide{i + 1}.xml"/>' for i in range(len(slides)))
            + "</Relationships>")
        for i, text in enumerate(slides, 1):
            z.writestr(f"ppt/slides/slide{i}.xml", f'<p:sld xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree><p:sp><p:txBody>'
                       f"<a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>")


def slide_extraction(root, rel, source, slides, stamped_sha=None, extractor=None):
    lines = ["---", f"source: {source}"]
    if stamped_sha:
        lines.append(f"sha256: {stamped_sha}")
    lines.append('chapter: "2"')
    if extractor:
        lines.append(f"extractor: {extractor}")
    lines += ["---", "", "# Units", ""]
    for n, s in enumerate(slides, 1):
        lines += [f"## U{n} [s.{s}] (important) slide {s}", "- teaches: x", ""]
    write(extraction(root, rel), "\n".join(lines) + "# Key verbatim\n\nnone\n")


def t_office():
    """Nothing a slide or a page says is dropped without a trace (F1)."""
    import hashlib
    root = project("office")
    deck, notes = "sources/ch2/2.4 deck.pptx", "sources/ch2/2.5 notes.docx"
    shutil.copyfile(os.path.join(FIX, "office", "deck.pptx"), os.path.join(root, *deck.split("/")))
    shutil.copyfile(os.path.join(FIX, "office", "notes.docx"), os.path.join(root, *notes.split("/")))
    s = scan(root)
    check("office: the scan asks for pre-extraction first", s["office"]["refresh"] == [deck, notes], s.get("office"))
    j = J(run("extract_office.py", "--all", root=root))
    by = {e["path"]: e for e in j.get("extracted", [])}
    d = read(os.path.join(root, by[deck]["cache"])) if deck in by else ""
    n = read(os.path.join(root, by[notes]["cache"])) if notes in by else ""
    check("office/pptx: an equation inside a text box PowerPoint wraps in AlternateContent is read with its sentence",
          "- Definition: [math: s^2=(∑_(i=1)^n ((x_i−x̅))^2)/(n−1)] for a sample of size n" in d, d[:900])
    check("office/pptx: SmartArt text, chart data, table cells, notes, alt text, line breaks, groups and hidden slides are kept",
          "[smartart] items in document order (arrows/layout are not extracted): Collect data | Summarise | Decide" in d
          and "- standard deviation: A=0.71, B=6.32" in d and "| B | 10 | 6.32 |" in d
          and "> notes: Stress that IQR ignores the tails." in d and "[picture, alt text] box plot of the two data sets" in d
          and "- first line\n  second line" in d and "- grouped note one" in d and "## Slide 4 (hidden in the slide show)" in d, d)
    check("office/pptx: what cannot become text is marked in place and counted in the header",
          "[visual] 1 picture(s) on this slide are NOT extracted" in d and "extractor: 3 | slides: 4 | equations: 1" in d.split("\n")[0]
          and by[deck]["stats"]["wrapped"] == 1 and by[deck]["recovered"] == 4, d.split("\n")[0])
    check("office/docx: inline and display equations, equations in table cells, outline-level headings and list items are kept",
          "The sample variance is [math: s^2=" in n and "[math: σ=√(σ^2)]" in n and "| sample | divide by [math: n−1] |" in n
          and "### Summary" in n and "- First reason" in n and "## 2.2 Variance and standard deviation" in n, n)
    j2 = J(run("extract_office.py", "--all", root=root))
    s = scan(root)
    check("office: cached by content hash and extractor version; the scan then knows the slide count",
          j2["cached"] == 2 and not j2["extracted"] and "office" not in s
          and [x.get("slides") for x in s["extract"] if x["path"] == deck] == [4], (j2, s["extract"]))
    def file_sha(rel):
        with open(os.path.join(root, *rel.split("/")), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    sha = file_sha(deck)
    # reading to the end is checked mechanically: 4 slides, units for 2
    slide_extraction(root, "ch2/2.4-deck.md", deck, [1, 2])
    rc, y = sync(root, "--stamp")
    check("truncation: an extraction that stops at slide 2 of 4 blocks (extraction.truncated)",
          "extraction.truncated" in codes(y) and "slides: 4" in read(extraction(root, "ch2/2.4-deck.md")), codes(y))
    slide_extraction(root, "ch2/2.4-deck.md", deck, [1, 2, 4])
    rc, y = sync(root, "--stamp")
    check("truncation: a skipped slide in the middle is put before the auditor (extraction.locator_gap)",
          "extraction.truncated" not in codes(y) and "extraction.locator_gap" in codes(y, "warnings"), (codes(y), codes(y, "warnings")))
    slide_extraction(root, "ch2/2.4-deck.md", deck, [1, 2, 3, 4])
    rc, y = sync(root, "--stamp")
    text = read(extraction(root, "ch2/2.4-deck.md"))
    check("stamp: a fresh office extraction records the extractor it was read with", "extractor: 3" in text and "units: 4" in text
          and "extraction.truncated" not in codes(y) and "extraction.locator_gap" not in codes(y, "warnings"), text[:200])
    # upgrading a v11.0 project: only sources that actually lost content are read again
    plain = "sources/ch2/2.6 plain.pptx"
    tiny_pptx(os.path.join(root, *plain.split("/")), ["only plain text", "second slide"])
    run("extract_office.py", "--all", root=root)
    psha = file_sha(plain)
    slide_extraction(root, "ch2/2.6-plain.md", plain, [1, 2], stamped_sha=psha)
    slide_extraction(root, "ch2/2.4-deck.md", deck, [1, 2, 3, 4], stamped_sha=sha)
    for h in (sha, psha):                                        # what v11.0 left behind: no extractor field
        cache = os.path.join(root, ".book-state", "extracted-office", h[:12] + ".md")
        write(cache, f"<!-- source: x | sha256: {h} -->\n\n# PPTX extraction\n\n## Slide 1\n- text only\n")
    s = scan(root)
    j = J(run("extract_office.py", "--all", root=root))
    s2 = scan(root)
    check("upgrade: v11.0 caches are refreshed; a deck whose equations/SmartArt were dropped goes back on the read list, a plain one does not",
          set(s["office"]["refresh"]) == {deck, plain} and all(e["upgraded_from_v1"] for e in j["extracted"])
          and [(x["path"], x["reason"]) for x in s2["extract"] if x["path"] in (deck, plain)] == [(deck, "office_recovered")], (s.get("office"), s2["extract"]))
    sync(root, "--stamp")
    check("upgrade: the stamp marks the plain deck as verified and leaves the lossy one open",
          "extractor: 3" in read(extraction(root, "ch2/2.6-plain.md")) and "extractor" not in read(extraction(root, "ch2/2.4-deck.md"))
          and [x["reason"] for x in scan(root)["extract"] if x["path"] == deck] == ["office_recovered"])
    broken = "sources/ch2/2.7 broken.docx"
    write(os.path.join(root, *broken.split("/")), "not a zip")
    p = run("extract_office.py", "--all", root=root)
    check("office: an unreadable file is reported, not a crash", p.returncode == 0 and [f["path"] for f in J(p)["failed"]] == [broken]
          and "Traceback" not in p.stderr, p.stdout[-300:])
    item = [x for x in scan(root)["extract"] if x["path"] == broken][0]
    check("office: the analyst of a file that could not be pre-extracted gets no file to read", "read" not in item and item["reason"] == "new", item)
    write(extraction(root, "ch2/2.7-broken.docx.md"), f"---\nsource: {broken}\nchapter: \"2\"\n---\n\n# Error\n\nnot an Office file\n")
    sync(root, "--stamp")
    s = scan(root)
    check("errors: an unreadable source is recorded, warned about and not tried again as long as it is the same file",
          broken in s["extraction_errors"] and broken not in [x["path"] for x in s["extract"]]
          and "extraction.error" in codes(validate(root)[1], "warnings"), s.get("extraction_errors"))
    shutil.copyfile(os.path.join(FIX, "office", "notes.docx"), os.path.join(root, *broken.split("/")))
    run("extract_office.py", "--all", root=root)
    check("errors: once the user replaces the file it goes back on the read list",
          [(x["reason"], "read" in x) for x in scan(root)["extract"] if x["path"] == broken] == [("changed", True)])


def t_evidence():
    """Mechanical evidence that meaning-critical items survive at every level (D1)."""
    for level in (2, 1):
        root = project(f"evidence-{level}", level)
        edit(draft(root, "4", level), '<p class="where">', "<p>")
        edit(draft(root, "2", level), "(median)", "(med.)")
        edit(draft(root, "2", level), '<ol class="steps">', '<ul class="steps">')
        text = read(draft(root, "2", level))
        i = text.index('<ul class="steps">')
        write(draft(root, "2", level), text[:i] + text[i:].replace("</ol>", "</ul>", 1))
        edit(draft(root, "4", level), '<div class="callout summary">',
             '<p><strong>ค่าแปรปรวน</strong> (variance) ถูกเรียกอีกชื่อหนึ่งในบทนี้</p>\n<div class="callout summary">')
        build(root)
        rc, v = validate(root)
        w = {x["code"]: x["detail"] for x in v["warnings"]}
        check(f"evidence L{level}: a formula without its symbol meanings, a missing key term, missing steps and a renamed term are reported",
              rc == 0 and {"formula.where_missing", "content.key_missing", "level.steps_missing", "terms.inconsistent"} <= set(w)
              and "'median'" in w.get("content.key_missing", "") and "1 of 2" in w.get("formula.where_missing", "")
              and "variance" in w.get("terms.inconsistent", ""), (codes(v), w))
    edit(draft(root, "4", 1), '<div class="callout formula">', '<div class="callout formula" data-symbols="above">')
    build(root)
    check("evidence: a formula may state that its symbols were defined earlier (data-symbols)",
          "formula.where_missing" not in codes(validate(root)[1], "warnings"))


def t_audit_merge():
    root = project("audit")
    adir = os.path.join(root, ".book-state", "audits")
    check("audit: the scan names the next audit number and a per-chapter spot-check budget",
          scan(root)["audit"] == {"latest": 0, "next": 1, "spot_checks_per_chapter": 2}, scan(root)["audit"])
    write(os.path.join(adir, "audit-1.part-ch-1.json"), json.dumps({"mode": "chapter", "chapter": "1", "findings": []}))
    write(os.path.join(adir, "audit-1.part-ch-2.json"), json.dumps({"mode": "chapter", "chapter": "2", "sourceReads": [
        {"file": "sources/ch2/2.2 dispersion.md", "loc": "§7", "why": "sample a critical formula"}], "findings": [
        {"severity": "minor", "type": "clarity", "location": "ch-2.html#sec-2-1", "description": "wordy", "suggested_fix": "compress"},
        {"severity": "critical", "type": "extraction", "location": "ch-2.html#sec-2-2-2", "source": "sources/ch2/2.2 dispersion.md §7",
         "description": "the extraction has n where the source has n − 1", "suggested_fix": "re-extract U7"}]}))
    write(os.path.join(adir, "audit-1.part-cross.json"), "{broken")
    check("audit: while parts exist the next number does not move", scan(root)["audit"]["next"] == 2)
    rc, y = sync(root, "--merge-audit", "--expect", "1", "2", "3", "cross", "--mode", "full")
    rep = json.loads(read(os.path.join(adir, "audit-1.json")))
    sev = [f["severity"] for f in rep["findings"]]
    check("audit merge: one report, findings numbered by severity, source reads kept, parts removed",
          rc == 0 and rep["id"] == "A1" and rep["status"] == "pending_approval" and rep["mode"] == "full" and rep["level"] == 2
          and sev == ["critical", "critical", "critical", "minor"] and [f["id"] for f in rep["findings"]] == ["F1", "F2", "F3", "F4"]
          and len(rep["sourceReads"]) == 1 and sorted(os.listdir(adir)) == [".gitkeep", "audit-1.json"]
          and all(f["resolution"] == "open" for f in rep["findings"]), rep)
    check("audit merge: a part that is missing or unreadable becomes a critical finding — never a silent skip",
          sum("not audited" in f["description"] for f in rep["findings"]) == 2
          and any(f["type"] == "extraction" and f.get("source") for f in rep["findings"]), [f["description"] for f in rep["findings"]])
    check("audit merge: prints the summary the orchestrator shows", y["audit"]["summary"] == {"critical": 3, "major": 0, "minor": 1}
          and len(y["audit"]["findings"]) == 4 and y["audit"]["findings"][0].startswith("F1 critical "), y.get("audit"))
    check("audit: the scan reports the latest report and its status", scan(root)["audit"]["latest"] == 1
          and scan(root)["audit"]["status"] == "pending_approval" and scan(root)["audit"]["next"] == 2)
    # F7: a newer audit of other chapters must not bury what is still open
    write(os.path.join(adir, "audit-2.part-ch-4.json"), json.dumps({"findings": []}))
    rc, y = sync(root, "--merge-audit", "--mode", "scope")
    rep = json.loads(read(os.path.join(adir, "audit-2.json")))
    old = json.loads(read(os.path.join(adir, "audit-1.json")))
    check("audit merge: open findings of an earlier report that were not re-examined are carried into the new one",
          rep["status"] == "pending_approval" and rep["scope"] == ["4"] and rep["mode"] == "scope" and y["audit"]["carried"] == 4
          and sorted(f["carried_from"] for f in rep["findings"]) == ["A1/F1", "A1/F2", "A1/F3", "A1/F4"]
          and old["status"] == "superseded" and old["superseded_by"] == "A2" and y["superseded"] == ["A1"]
          and "[carried from A1/" in y["audit"]["findings"][0], (rep, y))
    s = scan(root)["audit"]
    check("audit: the scan reports the level and the number of open findings of the latest report",
          s["latest"] == 2 and s["status"] == "pending_approval" and s["level"] == 2 and s["open"] == 4, s)
    for label in ("ch-1", "ch-2", "ch-3", "ch-4", "cross"):
        write(os.path.join(adir, f"audit-3.part-{label}.json"), json.dumps({"findings": [], "prior": [
            {"id": f["id"], "resolution": "fixed"} for f in rep["findings"] if f["part"] == label]}))
    write(os.path.join(adir, "audit-2.part-ch-9.json"), "{}")                     # left behind by an abandoned audit
    rc, y = sync(root, "--merge-audit", "--mode", "full", "--expect", "1", "2", "3", "4", "cross")
    rep = json.loads(read(os.path.join(adir, "audit-3.json")))
    check("audit merge: what the new auditors report fixed is not carried; a clean full audit closes the old report",
          rep["status"] == "clean" and y["audit"]["carried"] == 0 and rep["scope"] == "book" and len(y["audit"]["closed_prior"]) == 4
          and json.loads(read(os.path.join(adir, "audit-2.json")))["status"] == "superseded", (rep, y))
    check("audit merge: parts of an abandoned audit are removed, not left to confuse the numbering",
          y.get("stale_parts_removed") == ["audit-2.part-ch-9.json"] and scan(root)["audit"]["next"] == 4, y)
    # recheck: the auditor reports in a part file; the script edits the report
    write(os.path.join(adir, "audit-4.part-ch-1.json"), json.dumps({"findings": [
        {"severity": "major", "type": "accuracy", "location": "ch-1.html#sec-1", "description": "a", "suggested_fix": "b"},
        {"severity": "minor", "type": "clarity", "location": "ch-1.html#sec-1", "description": "c", "suggested_fix": "d"}]}))
    sync(root, "--merge-audit", "--mode", "scope")
    set_config(root, level=1)
    rc, y = sync(root, "--set-audit", "approved")
    rc3, y3 = sync(root, "--set-audit", "approved", "--audit", "4")
    check("audit gate: a report made at another summary level cannot be approved (its findings point at other drafts)",
          rc == 1 and codes(y) == ["audit.status"] and "level-1 edition" in y["problems"][0]["detail"]
          and rc3 == 1 and codes(y3) == ["audit.level"]
          and json.loads(read(os.path.join(adir, "audit-4.json")))["status"] == "pending_approval", (y, y3))
    set_config(root, level=2)
    rc, y = sync(root, "--set-audit", "approved")
    check("audit gate: approving is a script call", rc == 0 and y["audit"]["status"] == "approved" and y["audit"]["open"] == 2, y)
    write(os.path.join(adir, "audit-4.part-recheck.json"), json.dumps({"mode": "recheck", "results": [
        {"id": "F1", "resolution": "fixed"}, {"id": "F2", "resolution": "still_open", "note": "still wordy"}, {"id": "F9", "resolution": "fixed"}],
        "findings": [{"severity": "major", "type": "accuracy", "location": "ch-1.html#sec-1", "description": "the fix dropped a condition", "suggested_fix": "restore it"}]}))
    rc, y = sync(root, "--merge-audit")
    rep = json.loads(read(os.path.join(adir, "audit-4.json")))
    res = {f["id"]: f["resolution"] for f in rep["findings"]}
    check("recheck: results are applied by the script; a fix-introduced finding is appended; the report is pending again",
          rc == 0 and res == {"F1": "fixed", "F2": "still_open", "F3": "open"} and rep["status"] == "pending_approval"
          and y["audit"]["recheck"] == {"fixed": ["F1"], "still_open": ["F2"], "new": ["F3"]} and len(y["audit"]["findings"]) == 2
          and rep["findings"][2]["introduced_by_fix"] and codes(y, "warnings") == ["audit.recheck_id"]
          and not os.path.exists(os.path.join(adir, "audit-4.part-recheck.json")), (rep, y))
    sync(root, "--set-audit", "approved")
    write(os.path.join(adir, "audit-4.part-recheck.json"), json.dumps({"results": [{"id": "F2", "resolution": "fixed"}, {"id": "F3", "resolution": "fixed"}]}))
    rc, y = sync(root, "--merge-audit")
    check("recheck: when nothing is open any more the report is applied", y["audit"]["status"] == "applied" and y["audit"]["findings"] == [], y)
    rc, y = sync(root, "--set-audit", "declined")
    check("audit gate: a status that makes no sense is refused", rc == 1 and codes(y) == ["audit.status"], y)
    write(os.path.join(adir, "audit-5.part-cross.json"), json.dumps({"findings": [
        {"severity": "minor", "type": "consistency", "location": "book", "description": "x", "suggested_fix": "y"}]}))
    sync(root, "--merge-audit", "--mode", "scope")
    rc, y = sync(root, "--set-audit", "declined")
    rc2, y2 = sync(root, "--set-audit", "pending_approval")
    check("audit gate: declining and reopening are script calls too", rc == 0 and y["audit"]["status"] == "declined"
          and rc2 == 0 and scan(root)["audit"]["status"] == "pending_approval", (y, y2))
    # nothing may edit a draft while an audit runs
    built = project("audit-edit")
    build(built)
    bdir = os.path.join(built, ".book-state", "audits")
    write(os.path.join(bdir, "audit-1.part-ch-2.json"), json.dumps({"findings": []}))
    touch_draft(built, "2")
    rc, y = sync(built, "--merge-audit", "--mode", "scope")
    check("audit merge: a draft that changed while the audit ran is a critical finding",
          y["audit"]["status"] == "pending_approval" and any("must never edit a draft" in f for f in y["audit"]["findings"]), y)
    rc, y = sync(root, "--merge-audit")
    check("audit merge: nothing to merge is an error, not an empty report", rc == 1 and codes(y) == ["audit.no_parts"], y)


def tiny_docx(path, body, parts=None):
    """A minimal .docx written with the standard library."""
    import zipfile
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
        for name, xml in (parts or {}).items():
            z.writestr(name, xml.replace("{W}", W))


def line_extraction(root, rel, source, spans, chapter="4"):
    lines = ["---", f"source: {source}", f'chapter: "{chapter}"', "---", "", "# Units", ""]
    for n, span in enumerate(spans, 1):
        lines += [f"## U{n} [{span}] (important) block {n}", "- teaches: x", ""]
    write(extraction(root, rel), "\n".join(lines) + "# Key verbatim\n\nnone\n")


def t_v112():
    """What an audit of v11.1.0 reproduced (F1–F8): each case now blocks or is reported."""
    sys.path.insert(0, SCRIPTS)
    import kitlib
    # F6 — the ledger proves that the plan accounts for a unit, not that the draft contains it
    root = project("empty-section")
    text = read(draft(root, "3"))
    a, b = text.index("</h2>", text.index('id="sec-3-2"')) + 5, text.index('<h2 id="sec-3-3"')
    write(draft(root, "3"), text[:a] + "\n" + text[b:])
    build(root)
    rc, v = validate(root)
    check("content: a section that covers units but is only a heading blocks (draft.section_empty)",
          rc == 1 and codes(v) == ["draft.section_empty"] and "3.2" in v["problems"][0]["detail"], v.get("problems"))
    write(draft(root, "3"), text[:a] + "\n<p>กฎการบวกและกฎการคูณ ดูตัวอย่างในหนังสือเรียนประกอบ</p>\n" + text[b:])
    build(root)
    rc, v = validate(root)
    check("content: a section with a line or two for four units is put before the auditor (content.section_thin)",
          rc == 0 and codes(v, "warnings") == ["content.section_thin"] and "3.2 (4 units" in v["warnings"][0]["detail"], v.get("warnings"))
    for level in (1, 2):
        ok = project(f"dense-{level}", level)
        build(ok)
        rc, v = validate(ok)
        check(f"content: the level-{level} sample has no empty or thin section (chapter summary and navigation do not count as content)",
              rc == 0 and not v["problems"] and "content.section_thin" not in codes(v, "warnings"), (v.get("problems"), v.get("warnings")))
    one = project("dotless-empty")
    t1 = read(draft(one, "1"))
    write(draft(one, "1"), t1.split("\n", 1)[0] + '\n<div class="callout summary"><ul><li>สรุปยาวพอสมควรเพื่อทดสอบว่าไม่ถูกนับเป็นเนื้อหา</li></ul></div>\n')
    build(one)
    check("content: in a chapter without subsections the summary box alone is not content either",
          codes(validate(one)[1]) == ["draft.section_empty"], validate(one)[1].get("problems"))

    # F1 — text sources: was the file read to its last line?
    root = project("long-text")
    long_md = "sources/ch4/4.3 long.md"
    write(os.path.join(root, *long_md.split("/")), "# Long\n" + "\n".join(f"- fact {i}" for i in range(1, 3001)) + "\n")
    item = [x for x in scan(root)["extract"] if x["path"] == long_md][0]
    check("scan: a text source comes with its line count", item.get("lines") == 3001 and "read" not in item, item)
    line_extraction(root, "ch4/4.3-long.md", long_md, ["l.1-1000", "l.1001-2000"])
    rc, y = sync(root, "--stamp")
    check("truncation: a text extraction that stops at line 2000 of 3001 blocks (extraction.truncated)",
          rc == 1 and codes(y) == ["extraction.truncated"] and "line 2000" in y["problems"][0]["detail"]
          and "lines: 3001" in read(extraction(root, "ch4/4.3-long.md")), y)
    line_extraction(root, "ch4/4.3-long.md", long_md, ["l.1-1000", "l.1500-3001"])
    rc, y = sync(root, "--stamp")
    check("truncation: lines nobody located in the middle of a text source are put before the auditor",
          rc == 0 and codes(y, "warnings") == ["extraction.locator_gap"] and "1001–1499" in y["warnings"][0]["detail"], y)
    line_extraction(root, "ch4/4.3-long.md", long_md, ["§1", "§2"])
    rc, y = sync(root, "--stamp")
    check("truncation: a long text source without line locators is reported as unverified, never passed in silence",
          rc == 0 and codes(y, "warnings") == ["extraction.length_unverified"], y)
    line_extraction(root, "ch4/4.3-long.md", long_md, ["l.1-1500", "lines 1501–3001"])
    rc, y = sync(root, "--stamp")
    check("truncation: a text source read to its last line passes; short sources need no line locators",
          rc == 0 and not y["warnings"], y)

    # F2 — PDF pages without pypdf/pdfinfo, and an honest "unknown"
    pdf = os.path.join(root, "sources", "ch4", "4.4 slides.pdf")
    tiny_pdf(pdf, 37)
    check("pdf: the page count is read with the standard library when no PDF reader is installed", kitlib.pdf_pages_stdlib(pdf) == 37)
    with open(pdf, "ab") as f:
        f.write(b"\n99 0 obj\n<< /Type /Page >>\nendobj\n")                    # an orphaned page object: two readings disagree
    check("pdf: when two readings of the file disagree the count is unknown, not guessed", kitlib.pdf_pages_stdlib(pdf) is None)
    with open(pdf, "wb") as f:
        f.write(b"%PDF-1.4\nnot really a pdf\n")
    lines = ["---", "source: sources/ch4/4.4 slides.pdf", 'chapter: "4"', "---", "", "# Units", "", "## U1 [p.1-20] (important) x", "- teaches: x", ""]
    write(extraction(root, "ch4/4.4-slides.pdf.md"), "\n".join(lines) + "# Key verbatim\n\nnone\n")
    rc, y = sync(root, "--stamp")
    check("pdf: an unknown page count is a warning the auditor must judge (extraction.length_unverified)",
          "extraction.length_unverified" in codes(y, "warnings") and "extraction.truncated" not in codes(y), y)

    # F3 — a draft is fingerprinted with what its writer was handed, not with what the inputs are at build time
    root = project("briefing")
    shutil.rmtree(os.path.join(root, ".book-state", "drafts", "L2"))
    rc, p = sync(root, "--plan")
    copy_drafts(root, 2)                                                           # the writers finish; no build yet
    edit(extraction(root, "ch3/3-probability.md"), "- teaches: point 5", "- teaches: point 5 — now needs disjoint events")
    rc, p2 = sync(root, "--plan")
    check("briefing: a draft written before a build, whose inputs changed afterwards, is found stale (was: silently current)",
          set(p["write"]) == {"1", "2", "3", "4"} and p2["write"] == {"3": {"mode": "delta", "changed": ["3.2"], "added": [], "removed": [], "reordered": False}}
          and p2["current"] == ["1", "2", "4"], (p.get("write"), p2.get("write")))
    rc, b = build(root)
    check("briefing: the build does not adopt the new inputs for the old draft", codes(b, "warnings") == ["draft.stale"]
          and codes(validate(root)[1]) == ["draft.stale"], b.get("warnings"))
    touch_draft(root, "3")
    build(root)
    check("briefing: once the briefed writer has rewritten the chapter the book validates", validate(root)[0] == 0)
    root = project("untracked-edit")
    build(root)
    edit(extraction(root, "ch3/3-probability.md"), "- teaches: point 5", "- teaches: point 5 — now needs disjoint events")
    touch_draft(root, "3")                                                         # e.g. an audit fix elsewhere in the chapter
    build(root)
    check("briefing: an edit nobody was briefed for does not bring a stale chapter up to date",
          codes(validate(root)[1]) == ["draft.stale"], validate(root)[1].get("problems"))
    sync(root, "--plan")
    touch_draft(root, "3")
    build(root)
    check("briefing: plan, write, build — then it is current", validate(root)[0] == 0 and scan(root)["level"]["write_delta"] == {})
    root = project("renumber-briefed")
    build(root)
    edit(extraction(root, "ch3/3-probability.md"), "- teaches: point 5", "- teaches: point 5 — now needs disjoint events")
    sync(root, "--plan")
    rc, y = sync(root, "--renumber", "3=4", "4=5")
    s = scan(root)["level"]
    check("briefing: renumbering neither hides nor invents staleness", rc == 0 and s["write_delta"] == {"4": {"changed": ["4.2"]}}
          and s["current"] == ["1", "2", "5"], (y, s))
    touch_draft(root, "4")
    build(root)
    check("briefing: the briefing follows the renumbered chapter", codes(validate(root)[1]) == [], validate(root)[1].get("problems"))

    # F4 — pictures the kit cannot read are said out loud
    root = project("visuals")
    deck = "sources/ch2/2.4 deck.pptx"
    shutil.copyfile(os.path.join(FIX, "office", "deck.pptx"), os.path.join(root, *deck.split("/")))
    run("extract_office.py", "--all", root=root)
    s = scan(root)
    w = [x for x in validate(root)[1]["warnings"] if x["code"] == "sources.visual_unread"]
    check("visuals: unread pictures of an office source reach the user (scan) and the auditor (validation warning)",
          s["unread_visuals"]["files"] == [{"path": deck, "pictures": 1, "objects": 0}] and len(w) == 1 and "export the file to PDF" in w[0]["detail"], (s.get("unread_visuals"), w))

    # F5 / F8 — endnotes, numbered lists, over-long lines
    root = project("docx3")
    doc = "sources/ch2/2.5 method.docx"
    para = lambda text, ppr="": f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"       # noqa: E731
    num = lambda n: f'<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="{n}"/></w:numPr></w:pPr>'   # noqa: E731
    long_th = "ย่อหน้ายาวมากที่ไม่มีการขึ้นบรรทัดใหม่ " * 120
    tiny_docx(os.path.join(root, *doc.split("/")),
              para("Sort the data", num(1)) + para("Take the middle value", num(1)) + para("a remark", num(2))
              + f'<w:p><w:r><w:t>{long_th}</w:t></w:r><w:r><w:endnoteReference w:id="2"/></w:r></w:p>',
              {"word/numbering.xml": '<w:numbering xmlns:w="{W}"><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl></w:abstractNum>'
                                     '<w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/></w:lvl></w:abstractNum>'
                                     '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num><w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num></w:numbering>',
               "word/endnotes.xml": '<w:endnotes xmlns:w="{W}"><w:endnote w:type="separator" w:id="0"><w:p/></w:endnote>'
                                    '<w:endnote w:id="2"><w:p><w:r><w:t>Bessel correction, see chapter 2</w:t></w:r></w:p></w:endnote></w:endnotes>'})
    j = J(run("extract_office.py", "--all", root=root))
    cache = read(os.path.join(root, j["extracted"][0]["cache"]))
    check("office/docx: a numbered list stays a numbered list, a bulleted one a bulleted one",
          "1. Sort the data" in cache and "1. Take the middle value" in cache and "- a remark" in cache, cache[:600])
    check("office/docx: endnotes are read and marked where they are referenced",
          "[en 2]" in cache and "### Endnotes" in cache and "- [en 2] Bessel correction, see chapter 2" in cache
          and "endnotes: 1" in cache.split("\n")[0], cache[-300:])
    body = cache.split("\n")
    check("office/docx: no line longer than the reading tool takes; nothing but line breaks changed",
          max(len(x) for x in body) <= kitlib.LONG_LINE and "longlines: 1" in body[0]
          and "".join(cache.split()).count("".join(long_th.split())) == 1, max(len(x) for x in body))
    txt = "sources/ch2/2.6 notes.md"
    write(os.path.join(root, *txt.split("/")), "# Notes\n\n" + ("one very long line without a break " * 100) + "\n\n- short\n")
    s = scan(root)
    check("long lines: a text source with over-long lines is pre-extracted like an office file", txt in s["office"]["refresh"], s.get("office"))
    run("extract_office.py", "--all", root=root)
    item = [x for x in scan(root)["extract"] if x["path"] == txt][0]
    copy_text = read(os.path.join(root, *item["read"].split("/"))) if "read" in item else ""
    check("long lines: the analyst is given the wrapped copy and its line count",
          copy_text and max(len(x) for x in copy_text.split("\n")) <= kitlib.LONG_LINE and item["lines"] == len(copy_text.rstrip("\n").split("\n")), item)
    import hashlib
    with open(os.path.join(root, *txt.split("/")), "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    write(extraction(root, "ch2/2.6-notes.md"), f'---\nsource: {txt}\nsha256: {sha}\nchapter: "2"\nunits: 1\n---\n\n# Units\n\n## U1 [§1] (important) x\n- teaches: x\n\n# Key verbatim\n\nnone\n')
    check("long lines: a source that was read before its lines were wrapped goes back on the read list once",
          [x["reason"] for x in scan(root)["extract"] if x["path"] == txt] == ["long_lines"], scan(root)["extract"])
    write(extraction(root, "ch2/2.6-notes.md"), f'---\nsource: {txt}\nchapter: "2"\n---\n\n# Units\n\n## U1 [l.1-9] (important) x\n- teaches: x\n\n# Key verbatim\n\nnone\n')
    sync(root, "--stamp")
    check("long lines: re-read from the wrapped copy, it is stamped and leaves the read list",
          "extractor: 3" in read(extraction(root, "ch2/2.6-notes.md")) and txt not in [x["path"] for x in scan(root)["extract"]],
          read(extraction(root, "ch2/2.6-notes.md"))[:200])

    # the spot-check budget is a budget
    root = project("budget")
    set_config(root, raw={"audit": {"max_source_spot_checks": 3}})
    check("audit: max_source_spot_checks is shared out, not multiplied (4 chapters, budget 3 -> 1 each)",
          scan(root)["audit"]["spot_checks_per_chapter"] == 1, scan(root)["audit"])


def t_v113():
    """v11.3 — audit findings G1–G8: every reproduction case of the audit is a negative test here."""
    sys.path.insert(0, SCRIPTS)
    import kitlib

    def parts(root, n, labels, level, findings=None, prior=None):
        adir = os.path.join(root, ".book-state", "audits")
        for label in labels:
            body = {"mode": "cross" if label == "cross" else "chapter", "level": level, "findings": (findings or {}).get(label, [])}
            if prior and label in prior:
                body["prior"] = prior[label]
            write(os.path.join(adir, f"audit-{n}.part-{label}.json"), json.dumps(body))

    def report(root, n):
        return json.loads(read(os.path.join(root, ".book-state", "audits", f"audit-{n}.json")))

    crit = {"severity": "critical", "type": "accuracy", "location": "ch-2.html#sec-2-2", "description": "defect in the level-2 draft", "suggested_fix": "x"}
    ALL = ["ch-1", "ch-2", "ch-3", "ch-4", "cross"]

    # ---- G1: each level has its own line of audit reports
    root = project("g1")
    build(root)
    parts(root, 1, ALL, 2, {"ch-2": [crit]})
    sync(root, "--merge-audit", "--mode", "full", "--expect", "1", "2", "3", "4", "cross")
    set_config(root, level=1)
    copy_drafts(root, 1)
    sync(root, "--plan")
    build(root)
    parts(root, 2, ALL, 1)
    rc, y = sync(root, "--merge-audit", "--mode", "full", "--expect", "1", "2", "3", "4", "cross")
    s = scan(root)["audit"]
    check("G1: a clean audit of the level-1 edition does not close an open report about the level-2 edition",
          report(root, 1)["status"] == "pending_approval" and report(root, 2)["status"] == "clean" and report(root, 2)["level"] == 1
          and y["audit"]["carried"] == 0 and y.get("other_levels_open") == ["A1 (level 2)"] and "superseded" not in y, y)
    check("G1: the scan describes the report of the configured level and names open findings of the other edition",
          s["latest"] == 2 and s["status"] == "clean" and s["other_levels"] == {"2": {"latest": 1, "status": "pending_approval", "open": 1}}, s)
    parts(root, 3, ["ch-1", "cross"], 1, {"ch-1": [dict(crit, location="ch-1.html#sec-1", description="level-1 defect")]})
    rc, y = sync(root, "--merge-audit", "--mode", "scope", "--expect", "1", "cross")
    check("G1: a scoped audit of one level never carries findings of the other level into its report",
          y["audit"]["carried"] == 0 and [f["description"] for f in report(root, 3)["findings"]] == ["level-1 defect"], y)
    rc, y = sync(root, "--set-audit", "approved")
    check("G1: approving acts on the report of the configured level", rc == 0 and y["audit"]["report"].endswith("audit-3.json")
          and report(root, 1)["status"] == "pending_approval", y)
    set_config(root, level=2)
    s = scan(root)["audit"]
    rc, y = sync(root, "--set-audit", "approved")
    check("G1: back at level 2 its finding is still on the table and can be approved",
          s["latest"] == 1 and s["status"] == "pending_approval" and s["open"] == 1 and s["other_levels"]["1"]["latest"] == 3
          and rc == 0 and y["audit"]["report"].endswith("audit-1.json"), (s, y))
    parts(root, 4, ["ch-3"], 1)
    rc, y = sync(root, "--merge-audit", "--mode", "scope")
    check("G1: an audit part made for another level than content.level counts as no audit",
          any("examined the level-1 edition" in f for f in y["audit"]["findings"]), y)

    # ---- G8: re-auditing a part does not drop a finding nobody answered
    root = project("g8")
    build(root)
    parts(root, 1, ALL, 2, {"ch-2": [crit]})
    sync(root, "--merge-audit", "--mode", "full")
    s = scan(root)["audit"]
    check("G8: the scan hands the open findings of each part to the next audit",
          s["prior"] == {"report": ".book-state/audits/audit-1.json", "parts": {"ch-2": ["F1"]}}, s)
    parts(root, 2, ["ch-2", "cross"], 2)
    rc, y = sync(root, "--merge-audit", "--mode", "scope")
    f = report(root, 2)["findings"]
    check("G8: a part audited again without a verdict on an open finding keeps it open, marked as not re-examined",
          y["audit"]["status"] == "pending_approval" and y["audit"]["carried"] == 1 and f[0]["unconfirmed"] is True
          and f[0]["carried_from"] == "A1/F1" and "not re-examined" in y["audit"]["findings"][0], y)
    parts(root, 3, ["ch-2", "cross"], 2, prior={"ch-2": [{"id": "F1", "resolution": "still_open", "note": "still there"}]})
    rc, y = sync(root, "--merge-audit", "--mode", "scope")
    f = report(root, 3)["findings"]
    check("G8: a verdict 'still_open' carries the finding as confirmed", len(f) == 1 and "unconfirmed" not in f[0]
          and f[0]["carried_from"] == "A1/F1" and f[0]["recheck_note"] == "still there", f)
    parts(root, 4, ["ch-2", "cross"], 2, prior={"ch-2": [{"id": "F1", "resolution": "fixed"}]})
    rc, y = sync(root, "--merge-audit", "--mode", "scope")
    check("G8: only a verdict 'fixed' closes it", report(root, 4)["status"] == "clean" and y["audit"]["closed_prior"] == ["A3/F1"]
          and report(root, 3)["findings"][0]["closed_by"] == "A4", y)

    # ---- G6: an interrupted fix batch can be resumed
    root = project("g6")
    build(root)
    parts(root, 1, ["ch-2"], 2, {"ch-2": [crit]})
    sync(root, "--merge-audit", "--mode", "scope")
    sync(root, "--set-audit", "approved")
    s = scan(root)["audit"]
    rc, y = sync(root, "--set-audit", "approved")
    check("G6: a report left 'approved' by an interrupted batch is announced by the scan and can be approved again",
          s["status"] == "approved" and "resumes" in s.get("hint", "") and rc == 0 and "resumed" in y["audit"] and y["audit"]["open"] == 1, (s, y))

    # ---- G2: content after the last located line of a text source
    root = project("g2")
    for total, upto, want in ((2040, 2000, "block"), (6000, 5880, "block"), (100, 96, "warn"), (100, 99, "ok")):
        write(os.path.join(root, "sources", "ch4", "4.9 tail.md"), "".join(f"line {i} with content\n" for i in range(1, total + 1)))
        line_extraction(root, "ch4/4.9-tail.md", "sources/ch4/4.9 tail.md",
                        [f"l.{a}-{min(a + 499, upto)}" for a in range(1, upto + 1, 500)])
        rc, y = sync(root, "--stamp")
        got = ("block" if "extraction.truncated" in codes(y) else "warn" if any(
            w["code"] == "extraction.locator_gap" and "last line" in w["detail"] for w in y["warnings"]) else "ok")
        check(f"G2: {total - upto} content lines after the last located line of a {total}-line file -> {want}", got == want, y)

    # ---- G5: two sources never share one extraction path
    root = project("g5")
    for rel in ("ch5/lecture/slides.md", "ch5/tutorial/slides.md", "ch5/5.1 notes.md", "ch5/5.1 notes.txt"):
        write(os.path.join(root, "sources", *rel.split("/")), f"# {rel}\n- point\n")
    ex = {x["path"]: x["extraction"] for x in scan(root)["extract"]}
    check("G5: sources with the same name in one chapter get different extraction paths",
          len(set(ex.values())) == 4 and ex["sources/ch5/lecture/slides.md"].endswith("ch5/slides.md")
          and ex["sources/ch5/tutorial/slides.md"].endswith("ch5/tutorial-slides.md")
          and ex["sources/ch5/5.1 notes.txt"].endswith("ch5/5.1-notes.txt.md"), ex)
    for src, ext in ex.items():
        write(os.path.join(root, *ext.split("/")), f'---\nsource: {src}\nchapter: "5"\n---\n\n# Units\n\n## U1 [l.1-2] (important) a\n- teaches: a\n\n# Key verbatim\n\nnone\n')
    rc, y = sync(root, "--stamp")
    check("G5: after extraction every one of them has its own file and the paths stay stable",
          "extraction.missing" not in codes(y) and scan(root)["extract"] == [], (codes(y), scan(root)["extract"]))

    # ---- G3: what did not change is neither read nor written again
    root = project("g3")
    build(root)
    ep = extraction(root, "ch2/2.2-dispersion.md")
    text = read(ep)
    for u in range(10, 0, -1):                       # one new unit in front: every old unit moves by one
        text = text.replace(f"## U{u} [§{u}]", f"## U{u + 1} [§{u + 1}]")
    text = text.replace("# Units\n\n", "# Units\n\n## U1 [§1] (important) inserted\n- teaches: something new\n- visual: none\n\n", 1)
    write(ep, text)
    plan = load_plan(root)
    for sid, ref in (("2.2", "#U1-U3"), ("2.2.1", "#U4-U7"), ("2.2.2", "#U8-U10"), ("2.2.2.1", "#U11")):
        section(plan, sid)["covers"] = ["ext:ch2/2.2-dispersion.md" + ref]
    save_plan(root, plan)
    sync(root, "--stamp")
    rc, y = sync(root, "--plan")
    check("G3: units that only moved (new number, new locator) leave their sections current",
          rc == 0 and y["write"] == {"2": {"mode": "delta", "changed": ["2.2"], "added": [], "removed": [], "reordered": False}}, y)

    root = project("g3-migrate")
    build(root)
    lp = os.path.join(root, ".book-state", "drafts", "L2", "inputs.json")
    led = json.loads(read(lp))
    plan_n, ext_idx = kitlib.normalize_plan(load_plan(root))[0], kitlib.extraction_index(root)
    for ch in plan_n["chapters"]:                     # what v11.2 wrote: version-1 fingerprints, no fp/lang/style
        e = led["chapters"][ch["id"]]
        led["chapters"][ch["id"]] = {"draft_sha": e["draft_sha"], "order": e["order"],
                                     "sections": kitlib.chapter_inputs(ch, ext_idx, 1)["sections"]}
    led["chapters"]["2"]["sections"]["2.3"] = "0" * 16          # one section that already was stale
    led["kit"] = "11.2.0"
    write(lp, json.dumps(led))
    rc, v = validate(root)
    rc2, y = sync(root, "--plan")
    check("G3: a v11.2 ledger is carried over — current sections stay current, a stale one stays stale",
          rc == 1 and codes(v) == ["draft.stale"] and "2.3" in v["problems"][0]["detail"]
          and y["write"] == {"2": {"mode": "delta", "changed": ["2.3"], "added": [], "removed": [], "reordered": False}}, (codes(v), y.get("write")))

    root = project("g3-keep")
    src = os.path.join(root, "sources", "ch4", "4.8 keep.md")
    blocks = [[f"block {b} line {i}" for i in range(1, 11)] for b in (1, 2, 3)]
    write(src, "\n".join(sum(blocks, [])) + "\n")
    line_extraction(root, "ch4/4.8-keep.md", "sources/ch4/4.8 keep.md", ["l.1-10", "l.11-20", "l.21-30"])
    sync(root, "--stamp")
    old = read(extraction(root, "ch4/4.8-keep.md"))
    blocks[1][4] = "block 2 line 5 — corrected value"
    write(src, "\n".join(["new heading", "new intro"] + sum(blocks, [])) + "\n")
    item = next(x for x in scan(root)["extract"] if x["path"].endswith("4.8 keep.md"))
    check("G3: for a changed text source the scan proves which units are untouched and where they are now",
          item["reason"] == "changed" and item["previous_units"] == 3
          and item["keep"] == [{"unit": 1, "at": "l.3-12"}, {"unit": 3, "at": "l.23-32"}] and item["read_ranges"] == ["l.1-2", "l.13-22"]
          and "read" not in item, item)
    body = old.split("# Units\n\n")[1].split("# Key verbatim")[0]
    units = {int(m.group(1)): m.group(0) for m in re.finditer(r"## U(\d+) .*?\n(?:- .*\n)+", body)}
    new = ["## U1 [l.1-2] (supporting) heading\n- teaches: intro\n", units[1].replace("## U1 [l.1-10]", "## U2 [l.3-12]"),
           "## U3 [l.13-22] (important) block 2 again\n- teaches: corrected value\n", units[3].replace("## U3 [l.21-30]", "## U4 [l.23-32]")]
    write(extraction(root, "ch4/4.8-keep.md"), '---\nsource: sources/ch4/4.8 keep.md\nchapter: "4"\n---\n\n# Units\n\n' + "\n".join(new) + "\n# Key verbatim\n\nnone\n")
    rc, y = sync(root, "--stamp")
    r = (y.get("reextracted") or [{}])[0]
    check("G3: the stamp reports what the re-extraction kept, moved, replaced in place and added",
          r.get("extraction") == "ch4/4.8-keep.md" and (r["units"], r["kept"]) == (4, 2) and r["moved"] == ["U1 -> U2", "U3 -> U4"]
          and r["new"] == [1] and r["gone"] == [] and r["replaced"] == ["U2 -> U3 (no section)"], y.get("reextracted"))
    deck = os.path.join(root, "sources", "ch4", "4.7 deck.pptx")
    os.makedirs(os.path.dirname(deck), exist_ok=True)
    shutil.copyfile(os.path.join(FIX, "office", "deck.pptx"), deck)
    run("extract_office.py", "--all", root=root)
    sha = kitlib.file_sha256(deck)
    kind, slides, filled = kitlib.source_blocks(root, "sources/ch4/4.7 deck.pptx", sha)
    entry = {"kind": "s", "units": {str(n): [n, n, kitlib._digest(slides[n]), slides[n]] for n in sorted(slides)}}
    same = kitlib.unchanged_units(root, "sources/ch4/4.7 deck.pptx", sha, entry)
    check("G3: slides are compared the same way (a .pptx unit is located by its slides)",
          kind == "s" and len(slides) >= 2 and same and len(same["keep"]) == len(slides) and same["read_ranges"] == []
          and same["keep"][0]["at"] == "s.1", (kind, len(slides), same))

    # ---- G4: settings a writer acts on
    root = project("g4")
    set_config(root, raw={"ui": {"features": {"math_katex_cdn": True, "mermaid_cdn": True}}})
    edit(draft(root, "2"), "</h2>", "</h2>\n<p>ค่าเฉลี่ย \\( \\bar{x} = \\frac{1}{n}\\sum x_i \\)</p>\n<pre><code>\\( shown as code \\)</code></pre>\n"
         "<figure><pre class=\"mermaid\">graph TD; A-->B</pre><figcaption>flow</figcaption></figure>")
    build(root)
    ok_on = validate(root)[0] == 0
    set_config(root, raw={"ui": {"features": {"math_katex_cdn": False, "mermaid_cdn": False}}})
    rc, y = sync(root, "--plan")
    build(root)
    rc, v = validate(root)
    check("G4: TeX and Mermaid in a draft while the feature is off block validation and are listed for the writer",
          ok_on and rc == 1 and sorted(codes(v)) == ["draft.mermaid_off", "draft.raw_tex"]
          and y["write"]["2"]["mode"] == "delta" and y["write"]["2"]["form"] == ["raw_tex", "mermaid_off"]
          and y["write"]["2"]["changed"] == [] and set(y["write"]) == {"2"}, (codes(v), y.get("write")))
    edit(draft(root, "2"), "\\( \\bar{x} = \\frac{1}{n}\\sum x_i \\)", "<em>x̄</em> = Σ<em>x<sub>i</sub></em> / <em>n</em>")
    edit(draft(root, "2"), "<figure><pre class=\"mermaid\">graph TD; A-->B</pre><figcaption>flow</figcaption></figure>", "")
    touch_draft(root, "2")
    build(root)
    check("G4: TeX inside <pre>/<code> is content, not a formula", validate(root)[0] == 0 and sync(root, "--plan")[1]["write"] == {}, codes(validate(root)[1]))
    set_config(root, raw={"content": {"style_notes": "ใช้ภาษาทางการ"}})
    s = scan(root)
    check("G4: a changed audience/style rewrites nothing, but the user is told which chapters keep the old style",
          sync(root, "--plan")[1]["write"] == {} and s["level"]["style_outdated"]["chapters"] == ["1", "2", "3", "4"], s["level"])

    root = project("g4-recall", level=1)
    build(root)
    set_config(root, raw={"content": {"recall_questions": False}})
    build(root)
    check("G4: recall questions switched off are hidden by the build at no token cost",
          ".callout.recall{display:none}" in read(page(root, "assets/theme.css")) and validate(root)[0] == 0
          and sync(root, "--plan")[1]["write"] == {})
    set_config(root, raw={"content": {"recall_questions": True}})
    text = read(draft(root, "3", 1))
    write(draft(root, "3", 1), re.sub(r'<div class="callout recall">.*?</div>\s*', "", text, flags=re.S))
    build(root)
    y = sync(root, "--plan")[1]
    check("G4: switched on, a level-1 chapter without recall questions is listed for its writer",
          ".callout.recall{display:none}" not in read(page(root, "assets/theme.css"))
          and y["write"] == {"3": {"mode": "delta", "changed": [], "added": [], "removed": [], "reordered": False, "form": ["recall_missing"]}}, y.get("write"))

    # ---- G7: a slice never tells a repair to write the whole chapter
    root = project("g7")
    shutil.rmtree(os.path.join(root, ".book-state", "drafts", "L2"))
    sync(root, "--plan")
    sl = os.path.join(root, ".book-state", "plan", "slices", "ch-2.json")
    before = json.loads(read(sl))["write"]
    copy_drafts(root, 2)
    build(root)
    check("G7: once a chapter is built its slice no longer says 'write the whole chapter'",
          before == {"mode": "full"} and json.loads(read(sl))["write"] == {"mode": "none"} and validate(root)[0] == 0, before)

    P = lambda rel: read(os.path.join(PLUGIN, rel))   # noqa: E731
    check("prompts: the v11.3 mechanisms are named where an agent needs them",
          "audit.prior" in P("skills/rules/SKILL.md") and "interrupted" in P("skills/apply-fixes/SKILL.md")
          and "`keep`" in P("agents/source-analyst.md") and '"prior"' in P("agents/book-auditor.md")
          and "`form`" in P("agents/chapter-writer.md") and "reextracted" in P("agents/book-architect.md")
          and "as a repair" in P("skills/rules/SKILL.md") and "mode from its slice" not in P("skills/rules/SKILL.md"))


def reextract(root, rel, units, source=None, stamped=False):
    """Write the extraction `rel` anew, as an analyst would after a source changed: `units` is the
    new unit list in order — an int n re-uses the text of old unit n verbatim (new number, new
    locator), a string is a new unit with that title. Unstamped unless `stamped`."""
    path = extraction(root, rel)
    old = read(path)
    head = re.search(r"^source: (.+)$", old, re.M).group(1) if source is None else source
    chapter = re.search(r'^chapter: (.+)$', old, re.M).group(1)
    bodies = {int(m.group(1)): m.group(2) for m in re.finditer(r"^## U(\d+) \[[^\]]*\] (.*?)(?=^## U|\Z|^# )", old, re.M | re.S)}
    lines = ["---", f"source: {head}"]
    if stamped:
        sys.path.insert(0, SCRIPTS)
        import kitlib
        lines.append("sha256: " + kitlib.file_sha256(os.path.join(root, *head.split("/"))))
    lines += [f"chapter: {chapter}"] + ([f"units: {len(units)}"] if stamped else []) + ["---", "", "# Units", ""]
    for n, u in enumerate(units, 1):
        if isinstance(u, int):
            lines.append(f"## U{n} [§{n}] " + bodies[u].rstrip() + "\n")
        else:
            lines += [f"## U{n} [§{n}] (important) {u}", f"- teaches: {u}", "- visual: none", ""]
    write(path, "\n".join(lines) + "# Key verbatim\n\nnone\n")


def covers(root, sid, key="covers"):
    return section(load_plan(root), sid).get(key)


def hook(root, prompt, name=None, **extra):
    """Run the plugin's UserPromptExpansion hook as Claude Code does: the event as JSON on stdin."""
    data = dict({"hook_event_name": "UserPromptExpansion", "expansion_type": "slash_command", "cwd": root,
                 "command_name": name if name is not None else prompt.split()[0].lstrip("/"), "command_source": "plugin",
                 "prompt": prompt}, **extra)
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root)
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "gate_hook.py")], input=json.dumps(data), capture_output=True,
                          text=True, encoding="utf-8", env=env)


def gate(root):
    path = os.path.join(root, ".book-state", "audits", "gate.json")
    return json.loads(read(path)) if os.path.isfile(path) else None


def audit_with_finding(root, n=1):
    adir = os.path.join(root, ".book-state", "audits")
    write(os.path.join(adir, f"audit-{n}.part-ch-2.json"), json.dumps({"mode": "chapter", "chapter": "2", "level": 2, "findings": [
        {"severity": "major", "type": "accuracy", "location": "ch-2.html#sec-2-1", "description": "a condition is missing", "suggested_fix": "add it"}]}))
    return sync(root, "--merge-audit", "--mode", "scope", "--expect", "2")


def recheck(root, n, resolution):
    write(os.path.join(root, ".book-state", "audits", f"audit-{n}.part-recheck.json"),
          json.dumps({"mode": "recheck", "results": [{"id": "F1", "resolution": resolution}], "findings": []}))
    return sync(root, "--merge-audit")


def t_v114():
    """v11.4 — findings of the audit of v11.3.0 (H1, M1, M2, L1–L3): each reproduction case is a test."""
    sys.path.insert(0, SCRIPTS)
    import kitlib
    office = lambda root: sorted(os.listdir(os.path.join(root, ".book-state", "extracted-office")))  # noqa: E731

    # ---- H1: a changed .pptx / .docx keeps the path of the file its analyst opens
    root = project("h1")
    deck_rel = "sources/ch4/4.7 deck.pptx"
    deck = os.path.join(root, *deck_rel.split("/"))
    tiny_pptx(deck, ["first slide", "second slide", "third slide"])
    run("extract_office.py", "--all", root=root)
    slide_extraction(root, "ch4/4.7-deck.pptx.md", deck_rel, [1, 2, 3])
    sync(root, "--stamp")
    old_cache = office(root)
    tiny_pptx(deck, ["first slide", "second slide — corrected", "third slide"])
    run("extract_office.py", "--all", root=root)
    item = next(x for x in scan(root)["extract"] if x["path"] == deck_rel)
    target = os.path.join(root, *item["read"].split("/")) if isinstance(item.get("read"), str) else ""
    check("H1: a changed .pptx comes with the file to open AND the slides to read — two keys, never one",
          item["reason"] == "changed" and os.path.isfile(target) and kitlib.file_sha256(deck) in read(target)[:300]
          and item["read_ranges"] == ["s.2"] and item["keep"] == [{"unit": 1, "at": "s.1"}, {"unit": 3, "at": "s.3"}], item)
    slide_extraction(root, "ch4/4.7-deck.pptx.md", deck_rel, [1, 2, 3])
    rc, y = sync(root, "--stamp")
    check("H1: once the new version is stamped, the pre-extracted copy of the old version is gone (one source, one copy)",
          y.get("removedOfficeCache") == old_cache and len(office(root)) == 1 and office(root) != old_cache, (y.get("removedOfficeCache"), office(root)))

    notes_rel = "sources/ch4/4.6 notes.docx"
    notes = os.path.join(root, *notes_rel.split("/"))
    para = lambda t: f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>"  # noqa: E731
    tiny_docx(notes, para("alpha paragraph") + para("beta paragraph") + para("gamma paragraph"))
    run("extract_office.py", "--all", root=root)
    sha = kitlib.file_sha256(notes)
    copy = read(kitlib.office_cache_path(root, sha)).split("\n")
    at = {w: next(i for i, line in enumerate(copy, 1) if w in line) for w in ("alpha", "beta", "gamma")}
    header = sorted(kitlib.kit_header_lines(copy))
    line_extraction(root, "ch4/4.6-notes.docx.md", notes_rel, [f"l.1-{at['alpha']}", f"l.{at['beta']}", f"l.{at['gamma']}"])
    sync(root, "--stamp")
    tiny_docx(notes, para("alpha paragraph") + para("beta paragraph") + para("gamma paragraph — corrected"))
    run("extract_office.py", "--all", root=root)
    item = next(x for x in scan(root)["extract"] if x["path"] == notes_rel)
    check("H1: a changed .docx too — the path of its pre-extracted copy is not overwritten by the line ranges",
          isinstance(item.get("read"), str) and item["read"].endswith(kitlib.file_sha256(notes)[:12] + ".md")
          and item["read_ranges"] == [f"l.{at['gamma']}"], item)
    check("L1: the kit's own header lines are not content — a unit that starts at line 1 is kept, and no header line is on the read list",
          header and header[0] == 1 and item["keep"] == [{"unit": 1, "at": f"l.1-{at['alpha']}"}, {"unit": 2, "at": f"l.{at['beta']}"}]
          and not any(f"l.{h}" in item["read_ranges"] for h in header), (header, item))

    long_rel = "sources/ch4/4.5 long.md"
    long_src = os.path.join(root, *long_rel.split("/"))
    write(long_src, "# Long\n\n" + "word " * 700 + "\n\nshort line b\n\nshort line c\n")
    run("extract_office.py", "--all", root=root)
    item = next(x for x in scan(root)["extract"] if x["path"] == long_rel)
    wrapped = read(os.path.join(root, *item["read"].split("/"))).split("\n")
    b, c = (next(i for i, line in enumerate(wrapped, 1) if line == w) for w in ("short line b", "short line c"))
    line_extraction(root, "ch4/4.5-long.md", long_rel, [f"l.2-{b - 2}", f"l.{b}", f"l.{c}"])
    sync(root, "--stamp")
    write(long_src, "# Long\n\n" + "word " * 700 + "\n\nshort line b\n\nshort line c — corrected\n")
    run("extract_office.py", "--all", root=root)
    item = next(x for x in scan(root)["extract"] if x["path"] == long_rel)
    check("H1: a text source that is read through a wrapped copy keeps that path when it changes",
          isinstance(item.get("read"), str) and item["read"].startswith(".book-state/extracted-office/")
          and item["read_ranges"] == [f"l.{c}"] and [k["unit"] for k in item["keep"]] == [1, 2], item)
    analyst = read(os.path.join(PLUGIN, "agents", "source-analyst.md"))
    check("H1: the analyst prompt names both keys and never uses `read` for ranges",
          "`read_ranges`" in analyst and "ranges listed in `read`" not in analyst and "possibly `keep` and `read` " not in analyst)

    # ---- M1: the plan follows a re-extraction mechanically
    ext = "ch2/2.2-dispersion.md"
    src = "sources/ch2/2.2 dispersion.md"
    root = project("m1")
    build(root)
    sync(root, "--plan")
    write(os.path.join(root, *src.split("/")), read(os.path.join(root, *src.split("/"))) + "- a new point at the top\n")
    reextract(root, ext, ["inserted at the top", 1, 2, 3, 4, "point 5 corrected", 6, 7, 8, 9, 10])
    before = read(plan_path(root))
    rc, y = sync(root, "--stamp")
    r = (y.get("reextracted") or [{}])[0]
    check("M1: the stamp re-points the plan itself — moved units and a unit replaced in place keep their sections",
          rc == 0 and r.get("plan") == "re-pointed" and r["moved"] == ["U1-U4 -> U2-U5", "U6-U10 -> U7-U11"]
          and r["replaced"] == ["U5 -> U6 (section 2.2.1)"] and r["new"] == [1] and r["gone"] == []
          and covers(root, "2.2") == [f"ext:{ext}#U2-U3"] and covers(root, "2.2.1") == [f"ext:{ext}#U4-U7"]
          and covers(root, "2.2.2") == [f"ext:{ext}#U8-U10"] and covers(root, "2.2.2.1") == [f"ext:{ext}#U11"]
          and read(plan_path(root)) != before, (r, covers(root, "2.2"), covers(root, "2.2.1")))
    after = read(plan_path(root))
    rc, y = sync(root, "--stamp")
    check("M1: a second stamp shifts nothing again", rc == 0 and "reextracted" not in y and read(plan_path(root)) == after, y.get("reextracted"))
    rc, y = sync(root, "--plan")
    gap = [p["detail"] for p in y["problems"] if p["code"] == "coverage.gap"]
    check("M1: what is left for the architect is a blocking gap that names the new unit — and only the really changed section is stale",
          rc == 1 and codes(y) == ["coverage.gap"] and 'U1 "inserted at the top" is new' in gap[0] and "extracted again" in gap[0]
          and y["write"]["2"]["changed"] == ["2.2.1"] and os.path.isfile(os.path.join(root, ".book-state", "plan", "reextracted.json")),
          (codes(y), gap, y.get("write")))
    plan = load_plan(root)
    section(plan, "2.2")["covers"] = [f"ext:{ext}#U1-U3"]
    save_plan(root, plan)
    rc, y = sync(root, "--plan")
    sl = json.loads(read(os.path.join(root, ".book-state", "plan", "slices", "ch-2.json")))
    check("M1: once the plan accounts for the new unit nothing blocks, and the slices hand each section its own units "
          "(the unit replaced in place stays on record until the architect confirms it — F1 of v11.5)",
          rc == 0 and os.path.exists(os.path.join(root, ".book-state", "plan", "reextracted.json"))
          and codes(y, "warnings").count("plan.replaced_unreviewed") == 1
          and sorted(y["write"]["2"]["changed"]) == ["2.2", "2.2.1"]
          and [u["ref"].split("#")[1] for u in sl["units"]["2.2.1"]] == ["U4", "U5", "U6", "U7"]
          and any(u.get("keys") == ["quartile"] and u["ref"].endswith("#U4") for u in sl["units"]["2.2.1"]), (y.get("write"), sl["units"]["2.2.1"]))

    root = project("m1-resume")
    build(root)
    sync(root, "--plan")
    reextract(root, ext, ["inserted at the top", 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], stamped=True)   # stamped, then the run stopped
    check("M1: a run that stopped after the stamp — the scan has nothing to read or stamp, so nothing would call the architect",
          scan(root)["extract"] == [] and "stamp" not in scan(root))
    rc, y = sync(root, "--plan")
    check("M1: the plan step applies the map itself and blocks on the unplaced unit — the resume cannot pass with shifted numbers",
          rc == 1 and y["reextracted"][0]["plan"] == "re-pointed" and y["reextracted"][0]["moved"] == ["U1-U10 -> U2-U11"]
          and codes(y) == ["coverage.gap"] and covers(root, "2.2") == [f"ext:{ext}#U2-U3"] and y["write"] == {}, (y.get("reextracted"), codes(y), y.get("write")))
    rc, y = sync(root, "--plan")
    check("M1: running the plan step again repeats the gap and shifts nothing twice",
          rc == 1 and "reextracted" not in y and covers(root, "2.2") == [f"ext:{ext}#U2-U3"], y.get("reextracted"))

    ext4 = "ch4/4-normal.md"
    root = project("m1-gone")
    plan = load_plan(root)
    section(plan, "4.1")["covers"] = [f"ext:{ext4}#U1-U3"]
    section(plan, "4.2")["covers"] = [f"ext:{ext4}#U7"]
    plan["omitted"] = [{"ref": f"ext:{ext4}#U4-U6", "state": "omitted_justified", "reason": "worked examples repeated in 4.1"}]
    save_plan(root, plan)
    rc, y = sync(root, "--plan")
    reextract(root, ext4, [1, 2, "a new idea between two old ones", 3, 4, 5, 6])          # old U7 is gone
    rc, y = sync(root, "--stamp")
    r = y["reextracted"][0]
    plan = load_plan(root)
    check("M1: a range is split around a new unit, an omitted range moves with its reason, a vanished unit leaves the plan",
          r["moved"] == ["U3-U6 -> U4-U7"] and r["new"] == [3] and r["gone"] == ["U7 (was in: section 4.2)"] and r["emptied"] == ["4.2"]
          and covers(root, "4.1") == [f"ext:{ext4}#U1-U2", f"ext:{ext4}#U4"] and covers(root, "4.2") == []
          and plan["omitted"] == [{"ref": f"ext:{ext4}#U5-U7", "state": "omitted_justified", "reason": "worked examples repeated in 4.1"}],
          (r, covers(root, "4.1"), plan["omitted"]))
    rc, y = sync(root, "--plan")
    gap = [p["detail"] for p in y["problems"] if p["code"] == "coverage.gap"]
    check("M1: the gap says where the new unit sits, and a section that lost every unit blocks until it is decided",
          rc == 1 and sorted(codes(y)) == ["coverage.gap", "plan.section_emptied"] and 'U3 "a new idea between two old ones" is new and follows a unit of section 4.1' in gap[0], y["problems"])
    plan = load_plan(root)
    section(plan, "4.1")["covers"] = [f"ext:{ext4}#U1-U4"]
    plan["chapters"][3]["sections"] = [s for s in plan["chapters"][3]["sections"] if s["id"] != "4.2"]
    plan["removed"] = ["4.2"]
    save_plan(root, plan)
    rc, y = sync(root, "--plan")
    check("M1: both answered — the plan passes and the record is closed",
          rc == 0 and not os.path.exists(os.path.join(root, ".book-state", "plan", "reextracted.json")), y["problems"])

    root = project("m1-fix")
    build(root)
    sync(root, "--plan")
    before = read(plan_path(root))
    edit(extraction(root, ext), "- teaches: point 7", "- teaches: point 7 with the condition n > 1")
    kitlib.update_frontmatter(extraction(root, ext), {}, remove=("sha256",))
    rc, y = sync(root, "--stamp")
    r = (y.get("reextracted") or [{}])[0]
    rc2, y2 = sync(root, "--plan")
    check("M1: an extraction corrected in place (audit fix, same source) keeps every number — reported, nothing re-pointed, one section stale",
          rc == 0 and r.get("replaced") == ["U7 -> U7 (section 2.2.2)"] and r["moved"] == [] and r["new"] == [] and r["plan"] == "no reference had to change"
          and read(plan_path(root)) == before and rc2 == 0 and y2["write"]["2"]["changed"] == ["2.2.2"], (r, y2.get("write")))
    arch = read(os.path.join(PLUGIN, "agents", "book-architect.md"))
    check("M1: the architect is told that unit numbers are not its job",
          "never shift unit numbers yourself" in arch and "re-map `covers`" not in arch and "`replaced`" in arch and "plan.section_emptied" in arch)

    # ---- M2: one typed command, one fix batch
    root = project("m2")
    build(root)
    rc, y = audit_with_finding(root)
    a = scan(root)["audit"]
    check("M2: without the hook the gate says that it is not enforced — it does not refuse every approval",
          a["approval"]["enforced"] is False and "hook has not run" in a["approval"]["note"] and gate(root) is None, a)
    hook(root, "/book-kit:audit-book 2")
    check("M2: the hook records that it runs here; a command that is not apply-fixes is no approval",
          gate(root)["seen"] and gate(root)["grants"] == 0 and scan(root)["audit"]["approval"] == {
              "enforced": True, "batches": 0, "max_batches": 5, "on_record": False}, (gate(root), scan(root)["audit"]))
    rc, y = sync(root, "--set-audit", "approved")
    rep = json.loads(read(os.path.join(root, ".book-state", "audits", "audit-1.json")))
    check("M2: without a typed /book-kit:apply-fixes the report cannot be approved",
          rc == 1 and codes(y) == ["audit.gate"] and rep["status"] == "pending_approval" and "batches" not in rep, y)
    for prompt, name, extra in (("/other-plugin:apply-fixes", None, {}), ("apply the fixes please", "", {}),
                                ("/book-kit:apply-fixes", None, {"agent_id": "a1"}), ("/book-kit:apply-fixes", None, {"hook_event_name": "UserPromptSubmit"}),
                                ("/book-kit:apply-fixes", None, {"expansion_type": "mcp_prompt"})):
        hook(root, prompt, name, **extra)
    check("M2: another plugin's command, plain text, a subagent, another event — none of them is an approval", gate(root)["grants"] == 0, gate(root))
    p = hook(root, "/book-kit:apply-fixes critical+major")
    rc, y = sync(root, "--set-audit", "approved")
    check("M2: the typed command is the approval, and it is spent by the batch it starts",
          p.returncode == 0 and p.stdout == "" and rc == 0 and y["audit"]["status"] == "approved" and y["audit"]["batch"] == 1
          and "apply-fixes" in y["audit"]["gate"] and gate(root)["grants"] == 1 and gate(root)["used"] == 1, (p.stdout, p.stderr, y, gate(root)))
    rc, y = sync(root, "--set-audit", "approved")
    check("M2: an interrupted batch is resumed without a second approval (the same batch, already approved)",
          rc == 0 and "resumed" in y["audit"] and json.loads(read(os.path.join(root, ".book-state", "audits", "audit-1.json")))["batches"] == 1, y)
    rc, y = recheck(root, 1, "still_open")
    rc2, y2 = sync(root, "--set-audit", "approved")
    check("M2: after the recheck the report asks again — a second batch in the same turn is refused (the loop the gate exists for)",
          y["audit"]["status"] == "pending_approval" and rc2 == 1 and codes(y2) == ["audit.gate"]
          and json.loads(read(os.path.join(root, ".book-state", "audits", "audit-1.json")))["status"] == "pending_approval", (y, y2))
    hook(root, "/book-kit:apply-fixes", "apply-fixes")            # command_name without the plugin prefix: the typed text decides
    rc, y = sync(root, "--set-audit", "approved")
    check("M2: the user types the command again — the next batch starts", rc == 0 and y["audit"]["batch"] == 2, y)
    rc, y = recheck(root, 1, "fixed")
    check("M2: everything fixed — the report is applied", y["audit"]["status"] == "applied", y)

    root = project("m2-stale")
    build(root)
    hook(root, "/book-kit:apply-fixes")                            # typed while nothing was pending
    rc, y = audit_with_finding(root)
    rc, y = sync(root, "--set-audit", "approved")
    check("M2: an approval typed before the report asked is not an answer to it",
          gate(root)["grants"] == 1 and gate(root)["used"] == 1 and rc == 1 and codes(y) == ["audit.gate"], (gate(root), y))
    rc, y = sync(root, "--set-audit", "declined")
    hook(root, "/book-kit:apply-fixes")
    rc1, y1 = sync(root, "--set-audit", "pending_approval")
    rc2, y2 = sync(root, "--set-audit", "approved")
    check("M2: a declined report the user asks for by command is reopened and approved in one go",
          rc == 0 and rc1 == 0 and rc2 == 0 and y2["audit"]["batch"] == 1, (y1, y2))

    root = project("m2-cap")
    set_config(root, raw={"audit": {"approval_gate": "off", "max_fix_batches": 2}})
    build(root)
    hook(root, "/book-kit:build-book")
    audit_with_finding(root)
    seen = []
    for _ in range(3):
        rc, y = sync(root, "--set-audit", "approved")
        seen.append((rc, codes(y), (y.get("audit") or {}).get("gate")))
        if rc == 0:
            recheck(root, 1, "still_open")
    check("M2: with the gate switched off the approval is not checked — said so each time — and the batch limit still ends the loop",
          [x[0] for x in seen] == [0, 0, 1] and seen[2][1] == ["audit.batches"] and all("approval_gate" in x[2] for x in seen[:2])
          and scan(root)["audit"]["approval"]["enforced"] is False, seen)
    set_config(root, raw={"audit": {"approval_gate": "sometimes", "max_fix_batches": 0}})
    issues = scan(root)["config"].get("issues") or []
    check("M2: invalid gate settings are reported and replaced by the defaults",
          any("approval_gate" in i for i in issues) and any("max_fix_batches" in i for i in issues), issues)
    outside = os.path.join(TMP, "not-a-book")
    os.makedirs(outside, exist_ok=True)
    hook(outside, "/book-kit:apply-fixes")
    check("M2: outside a book project the hook writes nothing", not os.path.exists(os.path.join(outside, ".book-state")))
    hooks = json.loads(read(os.path.join(PLUGIN, "hooks", "hooks.json")))
    entry = hooks["hooks"]["UserPromptExpansion"][0]
    fixes = read(os.path.join(PLUGIN, "skills", "apply-fixes", "SKILL.md")).split("---")[1]
    rules = read(os.path.join(PLUGIN, "skills", "rules", "SKILL.md"))
    hook_src = read(os.path.join(SCRIPTS, "gate_hook.py"))
    check("M2: the plugin ships the hook for the event only a typed command fires; apply-fixes cannot be started by the model",
          list(hooks["hooks"]) == ["UserPromptExpansion"] and re.search(entry["matcher"], "book-kit:apply-fixes")
          and not re.fullmatch(r"[\w\-, |]*", entry["matcher"]) and "gate_hook.py" in entry["hooks"][0]["command"]
          and '"${CLAUDE_PLUGIN_ROOT}/scripts/gate_hook.py"' in entry["hooks"][0]["command"]
          and "disable-model-invocation: true" in fixes and "import kitlib" not in hook_src and "print(" not in hook_src, (entry, fixes))
    every = "".join(read(os.path.join(PLUGIN, rel)) for rel in ("skills/rules/SKILL.md", "skills/build-book/SKILL.md", "skills/update-book/SKILL.md",
                                                               "skills/audit-book/SKILL.md", "skills/apply-fixes/SKILL.md"))
    check("M2: no prompt offers a plain-language yes as an approval any more",
          "The approval is the command" in rules and "audit.gate" in rules and "audit.batches" in rules
          and not re.search(r"ตอบยืนยัน|answering yes|yes, apply the fixes\"|invoke the `book-kit:apply-fixes` skill yourself", every))

    # ---- L2: --rewrite is decided by script
    root = project("l2-rewrite")
    build(root)
    rc, y = sync(root, "--plan")
    rc2, y2 = sync(root, "--plan", "--rewrite")
    sl = json.loads(read(os.path.join(root, ".book-state", "plan", "slices", "ch-3.json")))
    check("L2: sync_state.py --plan --rewrite lists every chapter in full and the slices say so",
          y["write"] == {} and rc2 == 0 and y2.get("rewrite") is True and sorted(y2["write"]) == ["1", "2", "3", "4"]
          and all(w["mode"] == "full" and "--rewrite" in w["reason"] for w in y2["write"].values()) and y2["current"] == []
          and sl["write"]["mode"] == "full", (y.get("write"), y2.get("write"), sl["write"]))
    touch_draft(root, "3")
    build(root)
    rc, y = sync(root, "--plan")
    check("L2: the request holds until every chapter was written again (F7 of v11.5) — the written one is current, the others are still listed",
          rc == 0 and sorted(y["write"]) == ["1", "2", "4"] and y["current"] == ["3"]
          and all(w["mode"] == "full" and "--rewrite" in w["reason"] for w in y["write"].values()), (y.get("write"), y.get("current")))
    bb = read(os.path.join(PLUGIN, "skills", "build-book", "SKILL.md"))
    check("L2: the build command asks the script instead of a list the plan step never printed",
          "sync_state.py --plan --rewrite" in bb and "every chapter of `chapters`" not in bb)

    # ---- L3: the Claude Code version the kit needs is written down
    docs = read(os.path.join(REPO, "README.md")) + read(os.path.join(PLUGIN, "README.md")) + read(os.path.join(PLUGIN, "README_TH.md"))
    check("L3: the READMEs name the Claude Code version the kit was checked with and what older versions lack",
          docs.count("2.1.290") >= 3 and docs.count("2.1.271") >= 3, (docs.count("2.1.290"), docs.count("2.1.271")))


def t_v115():
    """v11.5 — findings of the audit of v11.4.0 (F1–F7 and two smaller points): each reproduction case is a test."""
    sys.path.insert(0, SCRIPTS)
    import kitlib
    record = lambda root: os.path.join(root, ".book-state", "plan", "reextracted.json")  # noqa: E731
    ext = "ch2/2.2-dispersion.md"
    src = "sources/ch2/2.2 dispersion.md"

    # ---- F1: a unit replaced in place stays on record until the architect confirms its place
    root = project("f1")
    build(root)
    sync(root, "--plan")
    write(os.path.join(root, *src.split("/")), read(os.path.join(root, *src.split("/"))) + "- point 5 was corrected\n")
    reextract(root, ext, [1, 2, 3, 4, "point 5 corrected", 6, 7, 8, 9, 10])
    rc, y = sync(root, "--stamp")
    r = (y.get("reextracted") or [{}])[0]
    check("F1: the stamp reports the replaced unit and says how the architect confirms it",
          rc == 0 and r.get("replaced") == ["U5 -> U5 (section 2.2.1)"] and "reextracted_reviewed" in r.get("architect", "")
          and os.path.isfile(record(root)), r)
    rc, y = sync(root, "--stamp")                                        # the run stopped here; a new session begins
    s = scan(root)
    check("F1: after an interruption the scan still says that the architect is due — nothing else would call it",
          "reextracted" not in y and s["extract"] == [] and "stamp" not in s
          and s.get("replan", {}).get("extractions") == [{"extraction": ext, "replaced": ["U5 -> U5 (section 2.2.1)"]}], s.get("replan"))
    rc, y = sync(root, "--plan")
    again = (y.get("reextracted") or [{}])[0]
    check("F1: the plan step does not block, but repeats the entry and warns until it is confirmed",
          rc == 0 and again.get("pending") is True and again.get("replaced") == ["U5 -> U5 (section 2.2.1)"]
          and codes(y, "warnings").count("plan.replaced_unreviewed") == 1 and os.path.isfile(record(root))
          and y["write"]["2"]["changed"] == ["2.2.1"], (again, codes(y, "warnings"), y.get("write")))
    touch_draft(root, "2")
    build(root)
    rc, v = validate(root)
    check("F1: the validator puts the unconfirmed unit before the auditor (a warning, not a block)",
          rc == 0 and "plan.replaced_unreviewed" in codes(v, "warnings"), (codes(v), codes(v, "warnings")))
    plan = load_plan(root)
    plan["reextracted_reviewed"] = [ext]
    save_plan(root, plan)
    rc, y = sync(root, "--plan")
    check("F1: the architect's confirmation closes the record, and the script takes the key out of the plan again",
          rc == 0 and y.get("reviewed") == [ext] and "reextracted" not in y and "plan.replaced_unreviewed" not in codes(y, "warnings")
          and not os.path.exists(record(root)) and "reextracted_reviewed" not in load_plan(root) and "replan" not in scan(root), y)

    root = project("f1-moved")
    build(root)
    sync(root, "--plan")
    write(os.path.join(root, *src.split("/")), read(os.path.join(root, *src.split("/"))) + "- point 5 is another topic now\n")
    reextract(root, ext, [1, 2, 3, 4, "a topic that belongs to 2.2.2", 6, 7, 8, 9, 10])
    sync(root, "--stamp")
    plan = load_plan(root)
    section(plan, "2.2.1")["covers"] = [f"ext:{ext}#U3-U4", f"ext:{ext}#U6"]
    section(plan, "2.2.2")["covers"] = [f"ext:{ext}#U5", f"ext:{ext}#U7-U9"]
    save_plan(root, plan)
    rc, y = sync(root, "--plan")
    check("F1: moving the replaced unit to another section is an answer too — no confirmation key needed",
          rc == 0 and "plan.replaced_unreviewed" not in codes(y, "warnings") and not os.path.exists(record(root)), (y["problems"], codes(y, "warnings")))

    root = project("f1-fix")
    build(root)
    sync(root, "--plan")
    edit(extraction(root, ext), "- teaches: point 7", "- teaches: point 7 with the condition n > 1")
    kitlib.update_frontmatter(extraction(root, ext), {}, remove=("sha256",))
    rc, y = sync(root, "--stamp")
    rc2, y2 = sync(root, "--plan")
    check("F1: an extraction corrected in place for the same source version (an audit fix) needs no review — the source did not move",
          rc == 0 and rc2 == 0 and "reextracted_reviewed" not in y["reextracted"][0]["architect"]
          and "plan.replaced_unreviewed" not in codes(y2, "warnings") and "replan" not in scan(root) and not os.path.exists(record(root)),
          (y.get("reextracted"), codes(y2, "warnings")))

    # ---- F2: an invalid content.level stops the plan step before anything is listed for a writer
    root = project("f2")
    shutil.rmtree(os.path.join(root, ".book-state", "drafts"))
    set_config(root, level=3)
    rc, y = sync(root, "--plan")
    check("F2: sync_state.py --plan blocks on an invalid content.level instead of listing the book for level 2",
          rc == 1 and codes(y) == ["config.level"] and "write" not in y
          and not os.path.isdir(os.path.join(root, ".book-state", "plan", "slices")), y)
    set_config(root, level=1)
    rc, y = sync(root, "--plan")
    check("F2: with a valid level the same call lists the chapters at that level", rc == 0 and y["level"] == 1 and sorted(y["write"]) == ["1", "2", "3", "4"], y)

    # ---- F3: what is left to read after a change is given as ranges, not line by line
    root = project("f3")
    rel = "sources/ch4/4.8 lines.md"
    path = os.path.join(root, *rel.split("/"))
    body = ["# Title", "", "alpha one", "", "alpha two", "", "## Beta", "", "beta one", "", "beta two", "", "beta three", "", "## Gamma", "", "gamma one"]
    write(path, "\n".join(body) + "\n")
    line_extraction(root, "ch4/4.8-lines.md", rel, ["l.1-6", "l.7-14", "l.15-17"])
    sync(root, "--stamp")
    body[8], body[12] = "beta one — corrected", "beta three — corrected"
    write(path, "\n".join(body) + "\n")
    item = next(x for x in scan(root)["extract"] if x["path"] == rel)
    check("F3: a changed passage is one range that bridges its blank lines, and never reaches into a kept unit",
          item["keep"] == [{"unit": 1, "at": "l.1-6"}, {"unit": 3, "at": "l.15-17"}] and item["read_ranges"] == ["l.7-13"], item)
    check("F3: ranges do not join across a line that belongs to a kept unit",
          kitlib._all_ranges([5, 7, 11], bridge=lambda i: i != 9) == ["5-7", "11"] and kitlib._all_ranges([5, 7, 9]) == ["5", "7", "9"])

    # ---- F4: no file carries a version label of its own that can be left behind
    stale = []
    for base, _, names in os.walk(PLUGIN):
        for name in names:
            if name.endswith((".py", ".js", ".css", ".html")) or (name == "SKILL.md") or base.endswith("agents"):
                head = "\n".join(read(os.path.join(base, name)).split("\n")[:12])
                for m in re.finditer(r"\bv(\d+\.\d+)\b", head):
                    if not kitlib.KIT_VERSION.startswith(m.group(1) + "."):
                        stale.append(f"{name}: v{m.group(1)}")
    check("F4: headers of scripts, templates, skills and agents name no other kit version than the current one", not stale, stale)

    # ---- F5: an extraction that stopped before its source did is offered again — not planned around
    root = project("f5")
    pdf = "sources/ch4/4.3 long.pdf"
    tiny_pdf(os.path.join(root, *pdf.split("/")), 25)
    if kitlib.pdf_page_count(os.path.join(root, *pdf.split("/"))) is None:
        print("SKIP  F5 PDF checks (the page count of the test PDF cannot be read)")
    else:
        def pdf_units(last):
            lines = ["---", f"source: {pdf}", 'chapter: "4"', "---", "", "# Units", ""]
            for n in range(1, last + 1):
                lines += [f"## U{n} [p.{n}] (important) page {n}", f"- teaches: page {n}", ""]
            write(extraction(root, "ch4/4.3-long.pdf.md"), "\n".join(lines) + "# Key verbatim\n\nnone\n")
        pdf_units(20)
        rc, y = sync(root, "--stamp")
        item = next((x for x in scan(root)["extract"] if x["path"] == pdf), None)
        check("F5: stamped but truncated — the next scan hands the source to its analyst again, with the place to resume",
              rc == 1 and "extraction.truncated" in codes(y) and item is not None and item["reason"] == "truncated"
              and item["resume_after"] == "p.20" and item["previous_units"] == 20 and item["pages"] == 25, item)
        pdf_units(25)                                               # the analyst read on (and dropped the sha256 line)
        rc, y = sync(root, "--stamp")
        check("F5: once the units reach the last page the source is no longer listed",
              "extraction.truncated" not in codes(y) and not [x for x in scan(root)["extract"] if x["path"] == pdf], codes(y))
    analyst = read(os.path.join(PLUGIN, "agents", "source-analyst.md"))
    check("F5: the analyst prompt says what to do with a truncated entry", "`reason: truncated`" in analyst and "`resume_after`" in analyst)

    # ---- F6: a draft carries content only — no code, no styles, no colours of its own
    root = project("f6")
    build(root)
    base = read(draft(root, "2"))
    marker = '<div class="callout summary">'
    assert marker in base
    write(draft(root, "2"), base.replace(marker, '<script>alert(1)</script><p onclick="x()">a</p>' + marker, 1))
    build(root)
    rc, v = validate(root)
    detail = next((p["detail"] for p in v["problems"] if p["code"] == "draft.foreign_markup"), "")
    check("F6: a <script> or an event attribute in a draft blocks validation", rc == 1 and "<script>" in detail and "onclick= attribute" in detail, v["problems"])
    write(draft(root, "2"), base.replace(marker, '<figure id="fig-2-9-z"><svg viewBox="0 0 64 30" role="img" aria-label="x">'
                                         '<rect width="10" height="5" fill="#000000"/><text x="1" y="9" fill="black">a</text>'
                                         '<path d="M0 0L5 5" stroke="var(--fig-1)" fill="none"/></svg><figcaption>c</figcaption></figure>'
                                         '<p style="color: #ffffff; margin: 0">b</p>' + marker, 1))
    build(root)
    rc, v = validate(root)
    detail = next((w["detail"] for w in v["warnings"] if w["code"] == "draft.hard_colour"), "")
    check("F6: colours written as literals are put before the writer and the auditor — CSS variables, none and currentColor are not",
          rc == 0 and "3 colour(s)" in detail and 'fill="#000000"' in detail and 'fill="black"' in detail and "style color: #ffffff" in detail, v["warnings"])
    write(draft(root, "2"), base)
    build(root)
    rc, v = validate(root)
    clean = True
    for level in (1, 2):
        for name in sorted(os.listdir(os.path.join(HERE, "fixtures", "drafts", f"L{level}"))):
            m = kitlib.draft_markup_issues(read(os.path.join(HERE, "fixtures", "drafts", f"L{level}", name)))
            clean = clean and not m["foreign"] and not m["colours"]
    check("F6: the sample book itself has neither (both levels), and prose or code samples about colours are not attributes",
          rc == 0 and clean and "draft.hard_colour" not in codes(v, "warnings")
          and kitlib.draft_markup_issues('<p>red, #fff</p><pre><code>&lt;rect fill="#000"/&gt; fill="#000"</code></pre><!-- <script> -->') == {"foreign": [], "colours": []})
    rules = read(os.path.join(PLUGIN, "skills", "rules", "SKILL.md"))
    check("F6: writer, auditor and rules know the two codes",
          "draft.hard_colour" in rules and "draft.foreign_markup" in rules
          and all(c in read(os.path.join(PLUGIN, "agents", "chapter-writer.md")) for c in ("draft.hard_colour", "draft.foreign_markup"))
          and "draft.hard_colour" in read(os.path.join(PLUGIN, "agents", "book-auditor.md")))

    # ---- F7: a rewrite that was asked for is owed until it happened
    root = project("f7")
    build(root)
    sync(root, "--plan")
    sync(root, "--plan", "--rewrite")
    build(root)                                                     # no writer ran (interrupted, or they failed)
    rc, v = validate(root)
    rc2, y = sync(root, "--plan")                                   # the next run, without the flag
    check("F7: a rewrite nobody carried out blocks validation and is listed again by a plain plan step and by the scan",
          rc == 1 and codes(v).count("draft.stale") == 4 and sorted(y["write"]) == ["1", "2", "3", "4"]
          and scan(root)["level"]["write_full"] == ["1", "2", "3", "4"], (codes(v), y.get("write")))
    for cid in "1234":
        touch_draft(root, cid)
    build(root)
    rc, v = validate(root)
    rc2, y = sync(root, "--plan")
    check("F7: once every chapter was written again the request is spent", rc == 0 and y["write"] == {} and y["current"] == ["1", "2", "3", "4"], (codes(v), y.get("write")))

    # ---- smaller points: facts the merge establishes are not doubled; a supplement is marked once
    root = project("merge-dup")
    build(root)
    adir = os.path.join(root, ".book-state", "audits")
    ok_part = lambda n, c: write(os.path.join(adir, f"audit-{n}.part-ch-{c}.json"), json.dumps({"mode": "chapter", "chapter": c, "level": 2, "findings": []}))  # noqa: E731
    ok_part(1, "1")
    write(draft(root, "2"), read(draft(root, "2")) + "<!-- edited while the audit ran -->\n")
    rc, y = sync(root, "--merge-audit", "--mode", "scope", "--expect", "1", "2")
    first = y["audit"]["findings"]
    ok_part(2, "1")
    ok_part(2, "2")
    rc, y = sync(root, "--merge-audit", "--mode", "scope", "--expect", "1", "2")
    second = y["audit"]["findings"]
    check("merge: a part that reported this time closes 'did not report'; a draft that still differs is raised once, not carried on top",
          len(first) == 2 and len(second) == 1 and "changed after its page was built" in second[0] and "carried" not in second[0]
          and len(y["audit"]["closed_prior"]) == 1, (first, second, y["audit"].get("closed_prior")))
    root = project("supp-twice")
    build(root)
    text = read(draft(root, "2"))
    m = re.search(r'data-supplement="([^"]+)"', text)
    write(draft(root, "2"), text.replace(marker, f'<div data-supplement="{m.group(1)}"><p>again</p></div>' + marker, 1))
    build(root)
    rc, v = validate(root)
    check("supplement: the same planned supplement marked twice is reported",
          any(w["code"] == "supplement.misplaced" and "2 times" in w["detail"] for w in v["warnings"]), v["warnings"])


def t_static_contract():
    """Hooks shared by templates, stylesheet, script and build — cheap guards against drift."""
    css = read(os.path.join(TEMPLATES, "assets", "style.css"))
    js = read(os.path.join(TEMPLATES, "assets", "app.js"))
    shells = read(os.path.join(TEMPLATES, "chapter-shell.html")) + read(os.path.join(TEMPLATES, "book-shell.html"))
    for hook in ('id="toc-open"', 'id="theme-toggle"', 'id="progress"', 'id="appearance-open"', 'id="main"',
                 'name="book-kit:template" content="11"', "assets/theme.css", "assets/book-data.js"):
        check(f"shells carry {hook}", shells.count(hook) == 2, shells.count(hook))
    check("stylesheet: no hard-coded text/background colours outside tokens",
          not re.search(r"(?<![-\w])(?:color|background(?:-color)?)\s*:\s*#[0-9a-fA-F]{3,8}", css))
    check("stylesheet: focus-visible, reduced-motion and print rules present",
          ":focus-visible" in css and "prefers-reduced-motion" in css and "@media print" in css)
    check("stylesheet: no hover state changes a solved colour pair; where-lines and muted highlights are styled",
          "brightness(" not in css and ".where" in css and "figcaption strong" in css)
    check("script: reading progress follows renumbered ids", "idHistory" in js and "idEpoch" in js)
    for cls in ("toc-ch", "toc-count", "twisty", "book-progress", "agenda-bar", "agenda-progress", "table-wrap", "copy-btn", "swatch"):
        check(f"class .{cls} is known to both stylesheet and script/build", cls in css and (cls in js or cls in read(os.path.join(SCRIPTS, "build_book.py"))))
    fonts = set(re.findall(r"url\(fonts/([\w.-]+)\)", css))
    check("fonts: every @font-face file is bundled (with its licence)", fonts and all(
        os.path.isfile(os.path.join(TEMPLATES, "assets", "fonts", f)) for f in fonts)
        and os.path.isfile(os.path.join(TEMPLATES, "assets", "fonts", "LICENSE.txt")), fonts)
    prompts = ["skills/rules/SKILL.md", "skills/content/SKILL.md", "skills/build-book/SKILL.md", "skills/update-book/SKILL.md",
               "skills/audit-book/SKILL.md", "skills/apply-fixes/SKILL.md", "skills/design/SKILL.md", "skills/init/SKILL.md",
               "agents/source-analyst.md", "agents/book-architect.md", "agents/chapter-writer.md", "agents/book-builder.md",
               "agents/book-auditor.md"]
    texts = {}
    for rel in prompts:
        path = os.path.join(PLUGIN, rel)
        texts[rel] = read(path) if os.path.isfile(path) else ""
        check(f"prompt {rel}: frontmatter + no references to retired pieces",
              texts[rel].startswith("---\nname: ") and not re.search(
                  r"CLAUDE\.md UI principles|ui\.accent|prune_state|rewrite_chapters|python-pptx|drafts/ch-<", texts[rel]), rel)
    allp = "".join(texts.values())
    scripts = set(re.findall(r"scripts/(\w+\.py)", allp)) | set(re.findall(r"\b(\w+_\w+\.py)\b", allp))
    check("every script a prompt names exists", scripts and all(os.path.isfile(os.path.join(SCRIPTS, s)) for s in scripts), scripts)
    flags = set(re.findall(r"sync_state\.py[^\n`]*?(--[a-z-]+)", allp)) | set(re.findall(r"`(--(?:sources|stamp|plan|renumber|merge-audit))`", allp))
    helptext = run("sync_state.py", "--help", root=TMP).stdout
    check("every sync_state.py action a prompt names exists", flags and all(f in helptext for f in flags), flags)
    rules = texts["skills/rules/SKILL.md"]
    check("rules skill stays compaction-safe (< 16 KB) with the gate near the top",
          len(rules.encode("utf-8")) < 16000 and 0 <= rules.find("REPORT → ASK → STOP") < 2500, len(rules.encode("utf-8")))
    content = texts["skills/content/SKILL.md"]
    check("content skill: preloadable into agents (not user-invocable, model may load it) and small",
          "user-invocable: false" in content and "disable-model-invocation" not in content and len(content.encode("utf-8")) < 9000, len(content.encode("utf-8")))
    fm = {rel: texts[rel].split("---")[1] for rel in prompts if rel.startswith("agents/")}
    check("agents: judgment agents preload the content rules only; nobody but the builder has a shell",
          all('skills: ["book-kit:content"]' in fm[f"agents/{a}.md"] for a in ("book-architect", "chapter-writer", "book-auditor"))
          and all("Bash" not in fm[f"agents/{a}.md"] for a in ("source-analyst", "book-architect", "chapter-writer", "book-auditor"))
          and "Bash" in fm["agents/book-builder.md"] and "book-kit:rules" not in "".join(fm.values()), fm)
    manifest = json.loads(read(os.path.join(PLUGIN, ".claude-plugin", "plugin.json")))
    kit = re.search(r'KIT_VERSION = "([^"]+)"', read(os.path.join(SCRIPTS, "kitlib.py"))).group(1)
    check("version: plugin.json, kitlib and the changelog agree", manifest["version"] == kit
          and f"## v{kit} " in read(os.path.join(PLUGIN, "CHANGELOG.md")), (manifest["version"], kit))


def t_v116():
    """v11.6 — findings of the audit of v11.5.0 (F1–F4, F6): each reproduction case is a test."""
    def drop_chapter(root, cid):
        plan = load_plan(root)
        gone = [s["id"] for ch in plan["chapters"] if ch["id"] == cid for s in ch["sections"]]
        plan["chapters"] = [ch for ch in plan["chapters"] if ch["id"] != cid]
        plan["removed"] = gone
        save_plan(root, plan)

    def new_extraction(root, rel, src, chapter, units):
        lines = ["---", f"source: {src}", f'chapter: "{chapter}"', "---", "", "# Overview", "", "New.", "", "# Units", ""]
        for n, title in enumerate(units, 1):
            lines += [f"## U{n} [l.{n + 2}] (important) {title}", f"- teaches: {title}", "- visual: none", ""]
        write(extraction(root, rel), "\n".join(lines + ["# Key verbatim", "", "none", ""]))

    # ---- F1: a chapter number that is used again never inherits its predecessor's draft
    root = project("v116-f1")
    build(root)
    run("scan_sources.py", "--commit", root=root)
    old_text = read(draft(root, "4"))
    shutil.rmtree(os.path.join(root, "sources", "ch4"))
    sync(root, "--sources")
    drop_chapter(root, "4")
    rc, y = sync(root, "--plan")
    retired = os.path.join(root, ".book-state", "drafts", "removed", "L2", "ch-4.html")
    check("F1: the draft of a chapter that left the plan is moved out of the store (kept under drafts/removed/)",
          y.get("status") == "OK" and not os.path.exists(draft(root, "4")) and os.path.isfile(retired)
          and read(retired) == old_text and y.get("drafts_retired") == ["L2/ch-4.html -> removed/L2/ch-4.html"], y)
    build(root)
    rc, v = validate(root)
    check("F1: the book without the chapter validates", rc == 0 and not os.path.exists(page(root, "ch-4.html")), v.get("problems"))
    # the pre-v11.6 state: the predecessor's draft is still lying in the store
    shutil.copyfile(retired, draft(root, "4"))
    write(os.path.join(root, "sources", "ch4", "4 regression.md"), "# regression\n\n- line\n- residual\n")
    new_extraction(root, "ch4/4-regression.md", "sources/ch4/4 regression.md", "4", ["regression", "residual"])
    sync(root, "--stamp")
    plan = load_plan(root)
    plan.pop("removed", None)
    plan["chapters"].append({"id": "4", "title_th": "การถดถอย", "page": "ch-4.html", "sections": [
        {"id": "4.1", "title_th": "พื้นฐาน", "priority": "important", "covers": ["ext:ch4/4-regression.md#U1"]},
        {"id": "4.2", "title_th": "ส่วนเหลือ", "priority": "important", "covers": ["ext:ch4/4-regression.md#U2"]}]})
    save_plan(root, plan)
    s = scan(root)
    rc, y = sync(root, "--plan")
    check("F1: a draft nothing is on record for is not current — the new chapter 4 is listed in mode full",
          y.get("write", {}).get("4", {}).get("mode") == "full" and "not written for this chapter" in y["write"]["4"].get("reason", "")
          and "4" not in y.get("current", []) and "4" in s["level"]["write_full"], (y.get("write"), y.get("current"), s["level"]))
    build(root)
    rc, v = validate(root)
    check("F1: … and until it is written, validation blocks (draft.stale) instead of passing on the old text",
          rc == 1 and "draft.stale" in codes(v) and any("nothing is on record" in p["detail"] for p in v["problems"]), v.get("problems"))
    rc, y = sync(root, "--plan")
    check("F1: … and the next plan step lists it again (the briefing alone does not make it current)",
          y.get("write", {}).get("4", {}).get("mode") == "full", y.get("write"))
    write(draft(root, "4"), '<!-- book-kit:draft chapter="4" level="2" rev="1" -->\n<p class="lead">การถดถอยอธิบายความสัมพันธ์ของสองตัวแปร</p>\n'
          '<h2 id="sec-4-1">4.1 พื้นฐาน</h2>\n<p>เส้นถดถอย (regression) คือเส้นตรงที่อธิบายข้อมูลได้ดีที่สุด ใช้ทำนายค่าของตัวแปรหนึ่งจากอีกตัวแปรหนึ่ง</p>\n'
          '<h2 id="sec-4-2">4.2 ส่วนเหลือ</h2>\n<p>ส่วนเหลือ (residual) คือผลต่างระหว่างค่าจริงกับค่าที่เส้นถดถอยทำนาย ยิ่งเล็กเส้นยิ่งอธิบายข้อมูลได้ดี</p>\n'
          '<div class="callout summary"><ul><li>เส้นถดถอยสรุปความสัมพันธ์</li><li>ส่วนเหลือวัดความคลาดเคลื่อน</li><li>ใช้ทำนายค่า</li></ul></div>\n')
    build(root)
    rc, v = validate(root)
    rc2, y = sync(root, "--plan")
    check("F1: once written from the briefing the chapter validates and is current", rc == 0 and y.get("write") == {}
          and "4" in y.get("current", []), (v.get("problems"), y.get("write")))
    fresh = project("v116-f1-legacy")
    os.remove(os.path.join(fresh, ".book-state", "drafts", "L2", "inputs.json")) if os.path.exists(
        os.path.join(fresh, ".book-state", "drafts", "L2", "inputs.json")) else None
    rc, y = sync(fresh, "--plan")
    check("F1: drafts from before the ledger (no inputs.json yet) are still adopted, not rewritten",
          y.get("write") == {} and len(y.get("current", [])) == 4, y.get("write"))

    # ---- F2: a renumbering puts chapters and sections where their new number belongs
    root = project("v116-f2")
    build(root)
    run("scan_sources.py", "--commit", root=root)
    src = os.path.join(root, "sources")
    os.rename(os.path.join(src, "ch3"), os.path.join(src, "chX"))
    os.rename(os.path.join(src, "ch4"), os.path.join(src, "ch3"))
    os.rename(os.path.join(src, "chX"), os.path.join(src, "ch4"))
    os.rename(os.path.join(src, "ch3", "4 normal.md"), os.path.join(src, "ch3", "3 normal.md"))
    os.rename(os.path.join(src, "ch4", "3 probability.md"), os.path.join(src, "ch4", "4 probability.md"))
    rc, y = sync(root, "--sources")
    plan = load_plan(root)
    check("F2: swapping two source chapters renumbers the book and keeps its chapters in number order",
          y.get("renumbered") == [{"3": "4", "4": "3"}] and [ch["id"] for ch in plan["chapters"]] == ["1", "2", "3", "4"]
          and plan["chapters"][2]["title_th"] == "การแจกแจงปกติ", [ch["id"] for ch in plan["chapters"]])
    rc, y = sync(root, "--plan")
    rcb, b = build(root)
    rc, v = validate(root)
    check("F2: … nothing is rewritten, the pages follow in number order and the book validates",
          y.get("write") == {} and b.get("pages") == ["index.html", "ch-1.html", "ch-2.html", "ch-3.html", "ch-4.html"]
          and rc == 0 and v["warningCount"] == 0, (b.get("pages"), v.get("problems"), v.get("warnings")))
    plan = load_plan(root)
    plan["chapters"] = [plan["chapters"][i] for i in (0, 1, 3, 2)]
    save_plan(root, plan)
    rc, v = validate(root)
    check("F2: chapters out of number order in the plan are put before the auditor (plan.order)",
          "plan.order" in codes(v, "warnings") and any("chapter 3 comes after chapter 4" in w["detail"] for w in v["warnings"]), v.get("warnings"))
    rc, y = sync(root, "--plan")
    check("F2: … and the plan step sorts them (chapter numbers follow the source folders)",
          y.get("chapters_sorted") == ["1", "2", "3", "4"] and [ch["id"] for ch in load_plan(root)["chapters"]] == ["1", "2", "3", "4"], y.get("chapters_sorted"))
    root = project("v116-f2-sections")
    build(root)
    plan = load_plan(root)
    section(plan, "3.3")["covers"] = ["ext:ch3/3-probability.md#U9-U11"]
    plan["chapters"][2]["sections"].append({"id": "3.4", "title_th": "หัวข้อใหม่", "priority": "important",
                                            "covers": ["ext:ch3/3-probability.md#U12"]})
    plan["renumber_request"] = ["3.4=3.2", "3.2=3.3", "3.3=3.4"]
    save_plan(root, plan)
    rc, y = sync(root, "--plan")
    plan = load_plan(root)
    ids = [s["id"] for s in plan["chapters"][2]["sections"]]
    check("F2: a section the architect asks to have between two others moves there (the new 3.2 follows 3.1)",
          ids == ["3.1", "3.2", "3.3", "3.4"] and plan["chapters"][2]["sections"][1]["title_th"] == "หัวข้อใหม่"
          and "plan.order" not in codes(y, "warnings"), (ids, y.get("warnings")))
    w = y.get("write", {}).get("3", {})
    check("F2: … the writer adds the new section and rewrites the one that lost a unit; the others keep their text",
          w.get("mode") == "delta" and w.get("added") == ["3.2"] and w.get("changed") == ["3.4"] and not w.get("reordered")
          and '<h2 id="sec-3-3">3.3 กฎการบวกและกฎการคูณ' in read(draft(root, "3")), w)

    # ---- F6: delete a middle chapter and shift the later ones, in one step
    root = project("v116-f6")
    build(root)
    run("scan_sources.py", "--commit", root=root)
    src = os.path.join(root, "sources")
    shutil.rmtree(os.path.join(src, "ch2"))
    os.rename(os.path.join(src, "ch3"), os.path.join(src, "ch2"))
    os.rename(os.path.join(src, "ch2", "3 probability.md"), os.path.join(src, "ch2", "2 probability.md"))
    os.rename(os.path.join(src, "ch4"), os.path.join(src, "ch3"))
    os.rename(os.path.join(src, "ch3", "4 normal.md"), os.path.join(src, "ch3", "3 normal.md"))
    prob_text, central_text = read(draft(root, "3")), read(draft(root, "2"))
    rc, y = sync(root, "--sources")
    check("F6: the renumbering cannot happen while chapter 2 is in the plan — said, with what happens next",
          "chapter 2 already exists" in y.get("renumber_skipped", "") and "renumbers by itself" in y["renumber_skipped"], y.get("renumber_skipped"))
    rc, y = sync(root, "--plan")
    drift = [w["detail"] for w in y.get("warnings", []) if w["code"] == "plan.chapter_drift"]
    check("F6: until then the plan step says which chapter has to leave the plan (plan.chapter_drift)",
          rc == 1 and "plan.covers_ref" in codes(y) and len(drift) == 1 and "3 -> 2, 4 -> 3" in drift[0]
          and "removes chapter 2" in drift[0], y.get("warnings"))
    drop_chapter(root, "2")                                      # the architect's answer
    rc, y = sync(root, "--plan")
    plan = load_plan(root)
    check("F6: once the chapter has left the plan the book follows the source folders by itself",
          y.get("status") == "OK" and y.get("renumbered_from_sources") == {"3": "2", "4": "3"}
          and [ch["id"] for ch in plan["chapters"]] == ["1", "2", "3"] and y.get("write") == {}
          and [s["id"] for s in plan["chapters"][1]["sections"]] == ["2.1", "2.2", "2.3"], (y.get("problems"), y.get("write")))
    moved = read(draft(root, "2"))
    check("F6: … the drafts moved with their chapters; the removed chapter's draft is kept aside, not overwritten",
          '<h2 id="sec-2-1">2.1 ' in moved and moved.split("\n", 2)[1] == prob_text.split("\n", 2)[1]
          and read(os.path.join(root, ".book-state", "drafts", "removed", "L2", "ch-2.html")) == central_text
          and y.get("drafts_retired") == ["L2/ch-2.html -> removed/L2/ch-2.html"], (moved[:160], y.get("drafts_retired")))
    check("F6: … and no draft is left for a chapter that is not in the plan", not os.path.exists(draft(root, "4")), os.listdir(os.path.dirname(draft(root, "4"))))
    build(root)
    rc, v = validate(root)
    fm = read(extraction(root, "ch3/3-probability.md"))
    check("F6: the book validates as chapters 1–3 and the extractions name their new chapter",
          rc == 0 and v["warningCount"] == 0 and 'chapter: "2"' in fm and sorted(n for n in os.listdir(os.path.join(root, "book")) if n.endswith(".html")) ==
          ["ch-1.html", "ch-2.html", "ch-3.html", "index.html"], (rc, v.get("warnings"), sorted(os.listdir(os.path.join(root, "book")))))
    s = scan(root)
    check("F6: … and the next scan has nothing left to do", "state" not in s and s["extract"] == [] and s["level"]["current"] == ["1", "2", "3"], s.get("state"))

    # ---- F4: a source outside a numbered chapter folder is named
    root = project("v116-f4")
    write(os.path.join(root, "sources", "misc", "notes.md"), "# notes\n\n- one\n")
    s = scan(root)
    check("F4: the scan names sources that carry no chapter number", s.get("unnumbered", {}).get("files") == ["sources/misc/notes.md"]
          and "architect" in s["unnumbered"]["tell_user"], s.get("unnumbered"))
    check("F4: a normal project has no such entry", "unnumbered" not in scan(project("v116-f4-clean")))

    # ---- F3 + models: prompts
    bb = read(os.path.join(PLUGIN, "skills", "build-book", "SKILL.md"))
    check("F3: --rewrite writes from the same plan; planning again is its own flag (--replan)",
          "do not contain `--replan`" in bb and "do not contain `--rewrite`" not in bb and "[--rewrite] [--replan]" in bb)
    want = {"source-analyst": ("opus", "high"), "book-architect": ("opus", "xhigh"), "chapter-writer": ("opus", "high"),
            "book-builder": ("sonnet", "high"), "book-auditor": ("opus", "xhigh")}
    got = {}
    for name in want:
        fm = read(os.path.join(PLUGIN, "agents", f"{name}.md")).split("---")[1]
        got[name] = (re.search(r"^model: (\S+)$", fm, re.M).group(1), (re.search(r"^effort: (\S+)$", fm, re.M) or [None, None])[1])
    check("agents: model and effort of every agent are the configured ones", got == want, got)
    readme = read(os.path.join(PLUGIN, "README.md")) + read(os.path.join(PLUGIN, "README_TH.md"))
    check("agents: the READMEs state the same defaults", "analyst `opus`/high, architect `opus`/xhigh, writer `opus`/high, builder `sonnet`/high, auditor `opus`/xhigh" in readme
          and "analyst = opus / high, architect = opus / xhigh, writer = opus / high, builder = sonnet / high, auditor = opus / xhigh" in readme)


# ----------------------------------------------------------------------------- browser
def t_browser(root, renumbered):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP  browser tests (Playwright is not installed)")
        return
    base = "file://" + os.path.join(root, "book").replace(os.sep, "/")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1360, "height": 900}, color_scheme="light", reduced_motion="reduce")
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(base + "/ch-2.html")
        pg.wait_for_timeout(300)
        html = pg.locator("html")
        check("browser: page boots (js class, theme resolved, fonts loaded)", "js" in (html.get_attribute("class") or "")
              and html.get_attribute("data-theme") == "light"
              and pg.evaluate("document.fonts.check('600 16px \"BK Head\"', 'ก') && document.fonts.check('400 16px \"BK Text\"', 'กa')"))
        check("browser: tables are wrapped and the highlighter stroke is applied",
              pg.evaluate("document.querySelectorAll('main table').length === document.querySelectorAll('main .table-wrap > table').length")
              and pg.evaluate("getComputedStyle(document.querySelector('main strong')).textDecorationLine") == "underline")
        pg.click("#theme-toggle")
        check("browser: first click on the theme button changes the theme and is stored",
              html.get_attribute("data-theme") == "dark" and pg.evaluate("Object.keys(localStorage).filter(k => k.endsWith(':theme')).length") == 1)
        pg.click("#appearance-open")
        check("browser: appearance popover opens", pg.locator("#appearance").is_visible())
        pg.click('.swatch[data-palette="ocean"]')
        pg.click('[data-fs-step="1"]')
        bg_ocean = pg.evaluate("getComputedStyle(document.body).backgroundColor")
        pg.keyboard.press("Escape")
        check("browser: palette + text size apply, Escape closes the popover",
              html.get_attribute("data-palette") == "ocean" and html.get_attribute("data-fs") == "1" and not pg.locator("#appearance").is_visible())
        pg.reload()
        pg.wait_for_timeout(250)
        check("browser: theme, palette and text size persist across reloads without a flash script error",
              html.get_attribute("data-theme") == "dark" and html.get_attribute("data-palette") == "ocean"
              and html.get_attribute("data-fs") == "1" and pg.evaluate("getComputedStyle(document.body).backgroundColor") == bg_ocean)
        check("browser: nothing is marked read just by opening a page", pg.locator("#toc a.read").count() == 0)
        pg.evaluate("document.getElementById('sec-2-2-1').scrollIntoView({behavior: 'instant'})")
        pg.wait_for_timeout(250)
        check("browser: scrollspy marks the current section", "2.2.1" in (pg.locator("#toc a.current").first.text_content() or ""))
        pg.click('#toc a[href$="#sec-2-2-2"]')
        pg.wait_for_timeout(300)
        top = pg.evaluate("document.getElementById('sec-2-2-2').getBoundingClientRect().top")
        check("browser: a TOC link lands its heading just below the top bar and makes it current",
              60 <= top <= 110 and (pg.locator("#toc a.current").first.text_content() or "").startswith("2.2.2"), top)
        pg.evaluate("window.scrollTo({top: document.documentElement.scrollHeight, behavior: 'instant'})")
        pg.wait_for_timeout(350)
        label = pg.locator(".book-progress .label").text_content() or ""
        check("browser: reaching the end marks the chapter's sections read and fills its progress segment",
              "6" in label and "12" in label and pg.locator('.toc-ch[data-id="2"] .toc-count').text_content() == "\u2713"
              and pg.evaluate("document.querySelector('.book-progress .seg[data-id=\"2\"] i').style.width") == "100%", label)
        check("browser: page progress bar reaches 100; the last section is current at the end of the page",
              pg.get_attribute("#progress", "aria-valuenow") == "100"
              and (pg.locator("#toc a.current").first.text_content() or "").startswith("2.3"))
        pg.fill("#toc-filter", "เบส")
        visible = pg.evaluate("[...document.querySelectorAll('.toc-ch')].filter(c => !c.hidden).map(c => c.dataset.id)")
        check("browser: TOC filter narrows to matching chapters and expands them", visible == ["3"]
              and pg.locator('.toc-ch[data-id="3"]').get_attribute("class").find("collapsed") < 0, visible)
        pg.fill("#toc-filter", "zzzz")
        check("browser: empty filter result is explained", pg.locator(".toc-empty").is_visible())
        pg.fill("#toc-filter", "")
        pg.click('.toc-ch[data-id="4"] .twisty')
        check("browser: chapters expand and collapse", pg.locator('.toc-ch[data-id="4"] .twisty').get_attribute("aria-expanded") == "true")
        pg.click("#toc-open")
        check("browser: the sidebar can be hidden on wide screens", "toc-hidden" in (html.get_attribute("class") or ""))
        pg.click("#toc-open")
        pg.goto(base + "/ch-3.html")
        pg.wait_for_timeout(250)
        check("browser: code blocks get a copy button; figures follow the palette",
              pg.locator("main pre .copy-btn").count() == 1
              and pg.evaluate("getComputedStyle(document.querySelector('figure svg rect')).fill") != "rgb(0, 0, 0)")
        pg.goto(base + "/index.html")
        pg.wait_for_timeout(250)
        check("browser: index shows per-chapter progress and offers to continue reading",
              pg.locator("#resume-link").is_visible() and "6/6" in (pg.locator('.agenda-ch[data-id="2"] .agenda-progress').text_content() or "")
              and pg.locator(".agenda-secs a.read").count() == 6)
        pg.once("dialog", lambda d: d.accept())
        pg.click("#appearance-open")
        pg.click("#reset-progress")
        check("browser: reading progress can be reset", pg.locator(".agenda-secs a.read").count() == 0 and not pg.locator("#resume-link").is_visible())
        ctx.close()
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark", reduced_motion="reduce")
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(base + "/ch-1.html")
        pg.wait_for_timeout(300)
        box = pg.locator("#toc").bounding_box()
        check("mobile: follows the system dark theme; sidebar starts off-canvas", pg.locator("html").get_attribute("data-theme") == "dark" and box["x"] + box["width"] <= 1)
        pg.click("#toc-open")
        pg.wait_for_timeout(300)
        check("mobile: drawer opens with a scrim", pg.locator("#toc").bounding_box()["x"] >= 0 and pg.locator(".scrim").is_visible())
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        check("mobile: Escape closes the drawer", not pg.locator(".scrim").is_visible())
        check("mobile: no horizontal overflow", pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"))
        pg2 = ctx.new_page()
        pg2.goto(base + "/ch-2.html")
        pg2.wait_for_timeout(200)
        fig = pg2.evaluate("(() => { const s = document.querySelector('figure svg'); if (!s) return null; const f = s.closest('figure');"
                           " return [s.getBoundingClientRect().width, f.scrollWidth > f.clientWidth + 1, getComputedStyle(f).overflowX,"
                           " document.documentElement.scrollWidth <= window.innerWidth + 1]; })()")
        check("mobile: a figure keeps a legible size and scrolls inside its own frame, not the page",
              fig is not None and fig[0] >= 470 and fig[1] and fig[2] == "auto" and fig[3], fig)
        pg2.close()
        pg.evaluate("window.scrollTo({top: document.documentElement.scrollHeight, behavior: 'instant'})")
        pg.wait_for_timeout(350)
        check("mobile: a chapter without subsections is tracked through its h1 anchor",
              pg.evaluate("JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k => k.endsWith(':read')))).includes('1')"))
        check("browser: no console or page errors", not errors, errors[:3])
        ctx.close()
        # hover on the primary button must not touch the colour pair that was solved for contrast
        ctx = browser.new_context(viewport={"width": 1360, "height": 900}, color_scheme="light", reduced_motion="reduce")
        pg = ctx.new_page()
        pg.goto(base + "/index.html")
        pg.wait_for_timeout(250)
        bg = pg.evaluate("getComputedStyle(document.getElementById('start-link')).backgroundColor")
        pg.hover("#start-link")
        pg.wait_for_timeout(150)
        st = pg.evaluate("(() => { const s = getComputedStyle(document.getElementById('start-link')); return [s.backgroundColor, s.filter, s.boxShadow]; })()")
        check("browser: hovering the primary button keeps its colours (ring only)", st[0] == bg and st[1] == "none" and st[2] != "none", st)
        ctx.close()
        # JavaScript off + system dark theme: the page still follows the system
        ctx = browser.new_context(viewport={"width": 1360, "height": 900}, color_scheme="dark", java_script_enabled=False)
        pg = ctx.new_page()
        pg.goto(base + "/ch-2.html")
        pg.wait_for_timeout(250)
        rgb = [int(x) for x in re.findall(r"\d+", pg.evaluate("getComputedStyle(document.body).backgroundColor"))[:3]]
        check("no-JS: dark system theme is followed, every TOC entry is visible", max(rgb) < 80
              and pg.locator('.toc-ch[data-id="3"] ol a').first.is_visible(), rgb)
        ctx.close()
        # ids renumbered after a reader stored progress: the marks move with the content
        ctx = browser.new_context(viewport={"width": 1360, "height": 900}, reduced_motion="reduce")
        pg = ctx.new_page()
        rbase = "file://" + os.path.join(renumbered, "book").replace(os.sep, "/")
        pg.goto(rbase + "/ch-4.html")
        pg.wait_for_timeout(250)
        pg.evaluate("""() => { const k = Object.keys(localStorage).find(x => x.endsWith(':idEpoch')).replace(/idEpoch$/, '');
            localStorage.setItem(k + 'read', JSON.stringify(['3.1', '2.1', '4.2'])); localStorage.setItem(k + 'last', JSON.stringify({href: 'ch-3.html#sec-3-1', id: '3.1', title: 'x'}));
            localStorage.removeItem(k + 'idEpoch'); }""")
        pg.reload()
        pg.wait_for_timeout(300)
        got = pg.evaluate("""() => { const g = n => JSON.parse(localStorage.getItem(Object.keys(localStorage).find(x => x.endsWith(':' + n))));
            return [g('read'), g('last').href, g('idEpoch')]; }""")
        check("browser: stored reading progress follows a chapter renumbering (3 -> 4, 4 -> 5)",
              sorted(got[0])[:3] == ["2.1", "4.1", "5.2"] and got[1] == "ch-4.html#sec-4-1" and got[2] == 1, got)
        browser.close()


def main():
    t_guards()
    t_init()
    t_build_level2()
    t_level_store()
    t_freshness_and_supplements()
    t_level1_form()
    t_config()
    t_structure_changes()
    t_template_override()
    t_coverage()
    t_integrity()
    t_pdf_and_paths()
    t_structure()
    t_stale()
    t_scan_lifecycle()
    t_renumber()
    t_fuzz()
    t_office()
    t_evidence()
    t_audit_merge()
    t_v112()
    t_v113()
    t_v114()
    t_v115()
    t_v116()
    t_static_contract()
    if "--browser" in sys.argv:
        fresh = project("browser")
        build(fresh)
        ren = project("browser-renumbered")
        build(ren)
        sync(ren, "--renumber", "3=4", "4=5")
        build(ren)
        t_browser(fresh, ren)
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed" + (f"; FAILED: {failed}" if failed else ""))
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
