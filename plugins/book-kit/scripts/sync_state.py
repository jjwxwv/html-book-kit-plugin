#!/usr/bin/env python3
"""Deterministic state maintenance — everything about .book-state/ that needs no judgment.
Zero tokens: the orchestrator runs these instead of editing state by hand.

Usage (project = current directory, or --root <dir>); actions can be combined, they run in this order:
  --sources        after a scan that reports "state": remap extractions of moved sources (same SHA-256),
                   renumber the book when the user renumbered whole source chapters, delete extractions
                   and office caches of removed sources
  --renumber A=B … renumber chapters or sections everywhere (plan, drafts of every level, ledgers);
                   e.g. --renumber 3=4 4=5   or   --renumber 2.4=2.2 2.2=2.3 2.3=2.4
  --stamp          after extraction: write sha256 / units / pages|slides / extractor into the frontmatter
                   of new extractions (agents never copy hashes or count units) and check every
                   extraction (numbering, unfinished files, sources not read to the end). For a source
                   that was extracted again it re-points the plan to the new unit numbers itself
                   (units that only moved, units replaced in place) — nobody shifts unit numbers by hand
  --plan           after planning: apply the architect's renumber_request, check the plan against the
                   extractions, generate plan/coverage.json and plan/slices/ch-<id>.json, and print what
                   has to be written at content.level   [--rewrite: every chapter is written again in full]
  --merge-audit    after auditing: merge audits/audit-<n>.part-*.json into audits/audit-<n>.json and
                   print the summary the orchestrator shows   [--expect 1 2 3 cross] [--mode full|scope].
                   Open findings of the earlier report about the same level are carried over unless
                   the auditor of their part reports them fixed ("prior"); reports about another
                   level's edition are left alone. A single part
                   named audit-<n>.part-recheck.json is applied to the existing report instead.
  --set-audit S    approved | declined | pending_approval — the only way a report's status changes
                   by hand   [--audit N, default: the latest report about the edition of content.level].
                   "approved" starts a fix batch: it needs an approval the user gave by typing
                   /book-kit:apply-fixes (recorded by the plugin's hook, scripts/gate_hook.py) and is
                   refused after audit.max_fix_batches batches on one report

Prints one JSON object. Exit 0 = done, 1 = blocking problems listed in "problems", 2 = not a book project.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitlib  # noqa: E402

SEVERITIES = ("critical", "major", "minor")
FINDING_TYPES = ("accuracy", "coverage", "extraction", "level", "clarity", "consistency", "supplement", "ui")


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    try:
        with open(path, "r", encoding="utf-8") as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


# ----------------------------------------------------------------------------- renumber
def _dashed(sid):
    return sid.replace(".", "-")


def rewrite_draft(text, mapping):
    """A draft with every id-derived token renumbered: stamp, heading numbers, anchors, links and
    their visible numbers, figure ids, supplement ids, page names."""
    m = lambda sid: kitlib.remap_id(sid, mapping)      # noqa: E731

    def stamp(mo):
        return mo.group(0).replace(f'chapter="{mo.group(1)}"', f'chapter="{m(mo.group(1))}"')
    text = kitlib.DRAFT_STAMP_RE.sub(stamp, text, count=1)

    def heading(mo):
        sid = mo.group(2).replace("-", ".")
        return mo.group(1) + (m(sid) if mo.group(3) == sid else mo.group(3))
    text = re.sub(r'(<h[1-6]\b[^>]*\bid="sec-([0-9-]+)"[^>]*>\s*(?:<span[^>]*>\s*)?)(\d+(?:\.\d+)*)', heading, text)

    def link_text(mo):
        sid = mo.group(2).replace("-", ".")
        return mo.group(1) + (m(sid) if mo.group(3) == sid else mo.group(3)) + mo.group(4)
    text = re.sub(r'(<a\b[^>]*\bhref="[^"]*#sec-([0-9-]+)"[^>]*>\s*)(\d+(?:\.\d+)*)(\s*</a>)', link_text, text)

    text = re.sub(r'(?<![\w-])(sec|fig)-(\d+(?:-\d+)*)',
                  lambda mo: f"{mo.group(1)}-{_dashed(m(mo.group(2).replace('-', '.')))}", text)
    text = re.sub(r'(data-supplement="S-)(\d+(?:\.\d+)*)(-)', lambda mo: mo.group(1) + m(mo.group(2)) + mo.group(3), text)
    text = re.sub(r'(?<![\w-])ch-(\d+)\.html', lambda mo: f"ch-{m(mo.group(1))}.html", text)
    return text


def renumber(root, mapping, out):
    """Apply {old id: new id} (chapters and/or sections) to the plan, every level's drafts and
    ledgers, and the extraction frontmatter. All-or-nothing: validates first, then writes."""
    mapping = {str(a).strip(): str(b).strip() for a, b in mapping.items() if str(a).strip() != str(b).strip()}
    if not mapping:
        return True
    id_re = re.compile(r"\d+(?:\.\d+)*")
    for a, b in mapping.items():
        if not id_re.fullmatch(a) or not id_re.fullmatch(b) or a.count(".") != b.count("."):
            out["problems"].append({"code": "renumber.map", "detail": f"{a}={b}: ids must be dotted numbers of the same depth"})
            return False
        if "." in a and a.split(".")[0] != b.split(".")[0] and a.split(".")[0] not in mapping:
            out["problems"].append({"code": "renumber.map",
                                    "detail": f"{a}={b}: a section cannot move to another chapter by renumbering"})
            return False
    plan = read_json(kitlib.plan_path(root))
    if not isinstance(plan, dict) or not isinstance(plan.get("chapters"), list):
        out["problems"].append({"code": "renumber.plan", "detail": "no readable plan to renumber"})
        return False
    m = lambda sid: kitlib.remap_id(str(sid).strip(), mapping)      # noqa: E731
    # what every draft was written from is settled under the old ids first, so the renumbering
    # can never be mistaken for (or hide) a change of content
    old_plan, old_ext = kitlib.normalize_plan(plan)[0], kitlib.extraction_index(root)
    for level in kitlib.LEVELS:
        if os.path.isdir(kitlib.drafts_dir(root, level)):
            kitlib.settle_ledger(root, old_plan, old_ext, level)
    chapter_map, new_ids, new_chapters = {}, [], []
    for ch in plan["chapters"]:
        if not isinstance(ch, dict):
            continue
        old = str(ch.get("id", "")).strip()
        chapter_map[old] = m(old)
        new_chapters.append(m(old))
        for s in ch.get("sections") or []:
            if isinstance(s, dict):
                new_ids.append(m(s.get("id", "")))
    if len(set(new_chapters)) != len(new_chapters) or len(set(new_ids)) != len(new_ids):
        out["problems"].append({"code": "renumber.collision",
                                "detail": f"{mapping} would give two chapters or sections the same id — nothing was changed"})
        return False

    # 1) plan
    for ch in plan["chapters"]:
        if not isinstance(ch, dict):
            continue
        old = str(ch.get("id", "")).strip()
        if ch.get("page") in (None, "", f"ch-{old}.html"):
            ch["page"] = f"ch-{m(old)}.html"
        ch["id"] = m(old)
        for s in ch.get("sections") or []:
            if not isinstance(s, dict):
                continue
            s["id"] = m(s.get("id", ""))
            for sp in s.get("supplements") or []:
                if isinstance(sp, dict) and isinstance(sp.get("id"), str):
                    sp["id"] = re.sub(r"^S-(\d+(?:\.\d+)*)-", lambda mo: f"S-{m(mo.group(1))}-", sp["id"])
    if isinstance(plan.get("removed"), list):
        plan["removed"] = [m(x) if isinstance(x, str) else x for x in plan["removed"]]
    history = plan.get("idHistory") if isinstance(plan.get("idHistory"), list) else []
    history.append({"map": mapping, "date": date.today().isoformat()})
    plan["idHistory"] = history
    plan.pop("renumber_request", None)

    # 2) drafts and ledgers of every level (two-phase rename so permutations cannot collide)
    renamed = []
    for level in kitlib.LEVELS:
        ddir = kitlib.drafts_dir(root, level)
        if not os.path.isdir(ddir):
            continue
        ledger, briefed = kitlib.load_ledger(root, level), kitlib.load_briefed(root, level)
        new_ledger, staged, sha_map = {}, [], {}
        for name in sorted(os.listdir(ddir)):
            mo = re.fullmatch(r"ch-(\d+)\.html", name)
            if not mo:
                continue
            old_cid = mo.group(1)
            path = os.path.join(ddir, name)
            with open(path, "rb") as f:
                old_bytes = f.read()
            new_bytes = rewrite_draft(old_bytes.decode("utf-8", "replace"), mapping).encode("utf-8")
            new_cid = chapter_map.get(old_cid, m(old_cid))
            sha_map[hashlib.sha256(old_bytes).hexdigest()] = hashlib.sha256(new_bytes).hexdigest()
            entry = ledger.get(old_cid)
            if entry:
                fresh = entry.get("draft_sha") == hashlib.sha256(old_bytes).hexdigest()
                secs = entry.get("sections") if isinstance(entry.get("sections"), dict) else {}
                new_ledger[new_cid] = dict(
                    {k: entry[k] for k in ("fp", "lang", "style") if k in entry},
                    draft_sha=hashlib.sha256(new_bytes).hexdigest() if fresh else None,
                    sections={m(k): v for k, v in secs.items()},
                    order=[m(x) for x in entry.get("order", [])] if isinstance(entry.get("order"), list) else [])
            if new_bytes != old_bytes or new_cid != old_cid:
                staged.append((path, os.path.join(ddir, f"ch-{new_cid}.html"), new_bytes))
        for path, _, _ in staged:
            os.remove(path)
        for path, dst, data in staged:
            with open(dst, "wb") as f:
                f.write(data)
            if path != dst:
                renamed.append(f"L{level}/{os.path.basename(path)} -> {os.path.basename(dst)}")
        new_briefed = {}
        for cid, b in briefed.items():
            new_briefed[chapter_map.get(cid, m(cid))] = dict(
                {k: b[k] for k in ("fp", "lang", "style") if k in b},
                before=sha_map.get(b.get("before"), b.get("before")),
                sections={m(k): v for k, v in b["sections"].items()},
                order=[m(x) for x in b.get("order", [])] if isinstance(b.get("order"), list) else [])
        if ledger or briefed:
            kitlib.save_ledger(root, level, new_ledger, new_briefed)

    # 3) open audit reports: their finding locations must keep pointing at the same content
    adir = kitlib.audits_dir(root)
    for name in sorted(os.listdir(adir)) if os.path.isdir(adir) else []:
        if not re.fullmatch(r"audit-\d+\.json", name):
            continue
        report = read_json(os.path.join(adir, name))
        if not isinstance(report, dict) or report.get("status") not in ("pending_approval", "approved") \
                or not isinstance(report.get("findings"), list):
            continue
        for f in report["findings"]:
            if isinstance(f, dict) and isinstance(f.get("location"), str):
                loc = re.sub(r"(?<![\w-])sec-(\d+(?:-\d+)*)", lambda mo: "sec-" + _dashed(m(mo.group(1).replace("-", "."))), f["location"])
                f["location"] = re.sub(r"(?<![\w-])ch-(\d+)(\.html|\b)", lambda mo: f"ch-{m(mo.group(1))}{mo.group(2)}", loc)
        if write_json(os.path.join(adir, name), report):
            out.setdefault("audits_relocated", []).append(name)

    # 4) extraction frontmatter (chapter-level maps only) and the plan itself
    for epath, e in kitlib.extraction_index(root).items():
        if e["chapter"] in mapping and "." not in e["chapter"]:
            kitlib.update_frontmatter(e["path"], {"chapter": f'"{mapping[e["chapter"]]}"'})
    write_json(kitlib.plan_path(root), plan)
    out.setdefault("renumbered", []).append(mapping)
    if renamed:
        out.setdefault("drafts_renamed", []).extend(renamed)
    return True


# ----------------------------------------------------------------------------- --sources
def do_sources(root, out):
    sources, _ = kitlib.walk_sources(root)
    if not sources:
        out["refused"] = ("sources/ contains no source files — refusing to prune everything; "
                          "delete .book-state/ manually if this is intentional")
        return
    shas = kitlib.source_shas(sources)
    ext_idx = kitlib.extraction_index(root)
    renames = kitlib.pending_renames(shas, ext_idx)
    plan_raw, _ = kitlib.load_plan(root)
    mapping, why_not = ({}, None)
    if plan_raw is not None:
        mapping, why_not = kitlib.suggest_renumber(kitlib.normalize_plan(plan_raw)[0], ext_idx, renames, shas)
    out["remapped"] = []
    for epath, old, new in renames:
        kitlib.update_frontmatter(ext_idx[epath]["path"], {"source": new})
        out["remapped"].append({"extraction": epath, "from": old, "to": new})
    if mapping:
        renumber(root, mapping, out)
    elif why_not:
        out["renumber_skipped"] = why_not + " — the architect restructures the affected chapters instead"

    # delete what belongs to sources that are gone
    all_shas = set(shas.values())
    out["removedExtractions"], out["removedOfficeCache"] = [], []
    base = os.path.join(root, ".book-state", "extractions")
    for epath, e in sorted(kitlib.extraction_index(root).items()):
        if e["source"] and e["source"] not in shas and not (e["sha256"] and e["sha256"] in all_shas):
            os.remove(e["path"])
            out["removedExtractions"].append(epath)
    if os.path.isdir(base):
        for dirpath, _, _ in os.walk(base, topdown=False):
            if dirpath != base and not os.listdir(dirpath):
                os.rmdir(dirpath)
    out["removedOfficeCache"] = prune_office_cache(root, all_shas)


def prune_office_cache(root, all_shas):
    """Delete pre-extracted copies of source versions that no longer exist (a removed source, or
    the previous version of a changed one) — so one source never has two copies lying around."""
    removed = []
    office = os.path.join(root, ".book-state", "extracted-office")
    if os.path.isdir(office):
        for name in sorted(os.listdir(office)):
            if not name.endswith(".md"):
                continue
            full = os.path.join(office, name)
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                mo = re.search(r"sha256:\s*([0-9a-fA-F]{64})", f.read(800))
            if mo and mo.group(1).lower() not in all_shas:
                os.remove(full)
                removed.append(name)
    return removed


# ----------------------------------------------------------------------------- re-extracted sources
replan_path, load_replan = kitlib.replan_path, kitlib.load_replan
REVIEW_KEY = "reextracted_reviewed"


def save_replan(root, pending):
    path = replan_path(root)
    if pending:
        write_json(path, {"kit": kitlib.KIT_VERSION, "extractions": dict(sorted(pending.items()))})
    elif os.path.exists(path):
        os.remove(path)


def _file_sha(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def _unit_refs(epath, nums):
    """[3, 4, 5, 9] -> ["ext:<epath>#U3-U5", "ext:<epath>#U9"] (order kept, neighbours joined)."""
    out, run = [], None
    for n in list(nums) + [None]:
        if run and n is not None and n == run[1] + 1:
            run[1] = n
            continue
        if run:
            out.append(f"ext:{epath}#U{run[0]}" + (f"-U{run[1]}" if run[1] != run[0] else ""))
        run = [n, n] if n is not None else None
    return out


def repoint_plan(plan, epath, mapping):
    """Rewrite every reference to a unit of `epath` in a raw plan to the unit's new number
    ({old: new}); a reference to an old unit that has no successor is removed. Returns
    (changed, where, emptied): where = {old unit: "section 2.2" | "section 2.2 (merged)" |
    "omitted"}, emptied = ids of sections that covered units of this extraction and now cover none."""
    where, emptied, changed = {}, [], False

    def rewrite(ref, label):
        try:
            path, nums = kitlib.expand_ref(ref)
        except ValueError:
            return None
        if path != epath:
            return None
        for n in nums:
            where.setdefault(n, label)
        return _unit_refs(epath, [mapping[n] for n in nums if n in mapping])

    def rewrite_list(refs, label):
        nonlocal changed
        out, touched = [], False
        for ref in refs:
            new = rewrite(ref, label) if isinstance(ref, str) else None
            if new is None:
                out.append(ref)
                continue
            touched = True
            if new != [ref]:
                changed = True
            out += new
        return out, touched

    all_ids = [str(s.get("id", "")).strip() for ch in plan.get("chapters") or [] if isinstance(ch, dict)
               for s in ch.get("sections") or [] if isinstance(s, dict)]
    for ch in plan.get("chapters") or []:
        if not isinstance(ch, dict):
            continue
        for s in ch.get("sections") or []:
            if not isinstance(s, dict):
                continue
            sid = str(s.get("id", "")).strip()
            had = False
            for key, label in (("covers", f"section {sid}"), ("merged", f"section {sid} (merged)")):
                if isinstance(s.get(key), list):
                    s[key], touched = rewrite_list(s[key], label)
                    had = had or touched
            if had and not s.get("covers") and not s.get("merged") \
                    and not any(x.startswith(sid + ".") for x in all_ids):
                emptied.append(sid)
    if isinstance(plan.get("omitted"), list):
        out = []
        for entry in plan["omitted"]:
            ref = entry.get("ref") if isinstance(entry, dict) else entry
            new = rewrite(ref, "omitted") if isinstance(ref, str) else None
            if new is None:
                out.append(entry)
                continue
            if new != [ref]:
                changed = True
            out += [dict(entry, ref=r) if isinstance(entry, dict) else r for r in new]
        plan["omitted"] = out
    return changed, where, emptied


def apply_reextractions(root, out, sources, shas, ext_idx):
    """A source that was extracted again numbers its units anew. The scripts know exactly which
    old unit became which new one (unit-sources.json holds what every unit said), so they re-point
    the plan themselves — the same rule as for section ids: nobody shifts numbers by hand. What
    needs judgment is left for the architect and stays on record until the plan answers it:
    units that are new (a coverage.gap until they are placed) and sections that lost every unit.
    "Extracted again" is read from the units themselves (their texts differ from the record), so
    it also covers an extraction corrected in place for the same source version. Runs at --stamp
    and again at --plan, so an interrupted run cannot lose the map; applying it twice is prevented
    by the record in plan/reextracted.json."""
    store = kitlib.load_unit_sources(root)
    pending = load_replan(root)
    plan_file = kitlib.plan_path(root)
    for epath, e in sorted(ext_idx.items()):
        old = store.get(epath)
        if not old or not e["sha256"] or e["incomplete"] or not e["count"] \
                or e["source"] not in sources or e["sha256"] != shas.get(e["source"]) \
                or not isinstance(old.get("fp"), dict) or not old["fp"]:
            continue
        fp_now = {str(n): kitlib._digest(u["fp_text"], 12) for n, u in e["units"].items()}
        if old["fp"] == fp_now:                        # the units say what the record says: nothing was re-extracted
            continue
        fp_sha = kitlib._digest(json.dumps(fp_now, sort_keys=True), 16)
        m = kitlib.unit_map(old, e)
        entry = dict({"extraction": epath}, **kitlib.reextraction_report(old, e))
        plan = read_json(plan_file)
        if not isinstance(plan, dict) or not isinstance(plan.get("chapters"), list):
            entry["plan"] = "there is no plan yet — nothing to re-point"
            out.setdefault("reextracted", []).append(entry)
            continue
        before = _file_sha(plan_file)
        rec = pending.get(epath)
        if rec and rec.get("units_fp") == fp_sha and rec.get("plan_before") != before:
            entry["plan"] = "already re-pointed by an earlier run"
        else:
            changed, where, emptied = repoint_plan(plan, epath, dict(m["kept"] + m["replaced"]))
            titles = {n: kitlib._PRIORITY_RE.sub("", kitlib._UNIT_HEAD_RE.sub("", (u.get("text") or "").split("\n")[0]), 1).strip()
                      for n, u in e["units"].items()}
            pending[epath] = {
                "sha256": e["sha256"], "units_fp": fp_sha, "plan_before": before, "date": date.today().isoformat(),
                "new": [{"unit": n, "title": titles.get(n, "")[:80]} for n in m["new"]],
                "replaced": [{"old": o, "new": n, "in": where.get(o, "no section")} for o, n in m["replaced"]],
                "gone": [{"unit": o, "was": where.get(o, "no section")} for o in m["gone"]],
                "emptied": emptied}
            if old.get("sha256") == e["sha256"]:
                # the same source version, corrected in place (an audit fix): the source did not
                # move, so there is no placement to review
                pending[epath]["reviewed"] = True
            save_replan(root, pending)                 # the record first: it is what prevents a second shift
            if changed:
                write_json(plan_file, plan)
            entry["plan"] = "re-pointed" if changed else "no reference had to change"
        rec = pending.get(epath, {})
        if rec.get("replaced"):
            entry["replaced"] = [f"U{r['old']} -> U{r['new']} ({r['in']})" for r in rec["replaced"]]
        if rec.get("gone"):
            entry["gone"] = [f"U{g['unit']} (was in: {g['was']})" for g in rec["gone"]]
        if rec.get("emptied"):
            entry["emptied"] = rec["emptied"]
        todo = []
        if entry.get("new"):
            todo.append("cover, merge or omit the new unit(s)")
        if entry.get("replaced") and not rec.get("reviewed"):
            todo.append("check that each replaced unit still belongs where its predecessor was, then list "
                        f"this extraction under \"{REVIEW_KEY}\" in the plan")
        if entry.get("emptied"):
            todo.append("give the emptied section(s) units or remove them")
        entry["architect"] = "; ".join(todo) if todo else "nothing to decide — the units only moved"
        out.setdefault("reextracted", []).append(entry)


def _replan_followup(root, plan, ext_idx, ledger, problems, out):
    """Keep what a re-extraction left for the architect on the table until the plan answers it:
    say where each still-unplaced new unit sits, block while an emptied section is still empty,
    and drop the record of an extraction once nothing is open."""
    pending = load_replan(root)
    if not pending:
        return
    sections = {s["id"]: s for ch in plan["chapters"] for s in ch["sections"]}
    ids = list(sections)
    for epath in list(pending):
        rec, e = pending[epath], ext_idx.get(epath)
        if e is None or rec.get("sha256") != e["sha256"]:
            del pending[epath]
            continue
        open_items = False
        unplaced = [x["unit"] for x in rec.get("new") or [] if isinstance(x, dict)
                    and x.get("unit") in e["units"] and f"ext:{epath}#U{x['unit']}" not in ledger]
        if unplaced:
            open_items = True
            hints = []
            titles = {x.get("unit"): x.get("title") or "" for x in rec.get("new") or [] if isinstance(x, dict)}
            for n in unplaced[:8]:
                prev = next((ledger[f"ext:{epath}#U{k}"] for k in range(n - 1, 0, -1) if f"ext:{epath}#U{k}" in ledger), None)
                sid = (prev.get("section") or prev.get("into")) if prev else None
                where = (f" and follows a unit of section {sid}" if sid in sections
                         else f" and follows a unit that is left out ({prev['state']})" if prev else "")
                hints.append(f"U{n}" + (f" \"{titles[n]}\"" if titles.get(n) else "") + " is new" + where)
            for p in problems:
                if p["code"] == "coverage.gap" and p["detail"].startswith(f"ext:{epath}:"):
                    p["detail"] += " — " + "; ".join(hints) + " (the source was extracted again)"
        # A unit replaced in place took its predecessor's place in the plan by script. Whether it
        # still belongs there is the architect's call, and it stays on record until the architect
        # says so ("reextracted_reviewed" in the plan, consumed by do_plan) or has moved the unit.
        waiting = []
        for r in ([] if rec.get("reviewed") else rec.get("replaced") or []):
            if not (isinstance(r, dict) and r.get("new") in e["units"]):
                continue
            now = ledger.get(f"ext:{epath}#U{r['new']}")
            here = (f"section {now['section']}" if now and now.get("state") == "represented"
                    else f"section {now['into']} (merged)" if now and now.get("state") == "merged"
                    else "omitted" if now else "no section")
            if here == r.get("in"):
                waiting.append(r)
        if not waiting and rec.get("replaced"):
            rec["reviewed"] = True
        if waiting:
            open_items = True
            shown = [f"U{r['old']} -> U{r['new']} ({r['in']})" for r in waiting]
            if not any(x.get("extraction") == epath for x in out.get("reextracted", [])):
                out.setdefault("reextracted", []).append({
                    "extraction": epath, "replaced": shown, "pending": True,
                    "architect": "check that each replaced unit still belongs where its predecessor was, then "
                                 f"list this extraction under \"{REVIEW_KEY}\" in the plan"})
            out["warnings"].append({
                "code": "plan.replaced_unreviewed",
                "detail": f"{epath}: {', '.join(shown[:8])}{' …' if len(shown) > 8 else ''} — the unit(s) changed in "
                          "place and kept their predecessor's place in the plan by script; the architect has not "
                          f"confirmed that they still belong there (\"{REVIEW_KEY}\")"})
        still = [sid for sid in rec.get("emptied") or [] if sid in sections and not sections[sid]["covers"]
                 and not sections[sid]["merged"] and not any(x.startswith(sid + ".") for x in ids)]
        for sid in still:
            open_items = True
            problems.append({"code": "plan.section_emptied",
                             "detail": f"section {sid} covers no unit any more — every unit it covered disappeared when "
                                       f"{e['source']} was extracted again. Give it units, or remove the section "
                                       "(list its id under \"removed\")"})
        if not open_items:
            del pending[epath]
    save_replan(root, pending)


# ----------------------------------------------------------------------------- --stamp
def do_stamp(root, out):
    sources, unsupported = kitlib.walk_sources(root)
    shas = kitlib.source_shas(sources)
    out["stamped"], out["refreshed"], out["unfinished"] = [], 0, []
    # A source extracted again under a new file name: the fresh text takes over the established
    # path (the one the plan references) instead of leaving two files that claim one source.
    claims = {}
    for epath, e in sorted(kitlib.extraction_index(root).items()):
        if e["source"] in sources:
            claims.setdefault(e["source"], []).append(e)
    for source, group in claims.items():
        fresh = [e for e in group if not e["sha256"] and not e["incomplete"]]
        old = [e for e in group if e["sha256"] and e["sha256"] != shas[source]]
        if len(group) > 1 and len(fresh) == 1 and len(old) == len(group) - 1:
            keep = old[0]
            os.replace(fresh[0]["path"], keep["path"])
            for extra in old[1:]:
                os.remove(extra["path"])
            out.setdefault("adopted", []).append({"from": fresh[0]["rel"], "to": keep["rel"]})
    for epath, e in sorted(kitlib.extraction_index(root).items()):
        if not e["source"] or e["source"] not in sources:
            continue
        if e["incomplete"]:
            out["unfinished"].append(epath)
            continue
        updates = {}
        fresh = not e["sha256"]
        sha = e["sha256"] or shas[e["source"]]
        if fresh:                    # also for an "# Error" extraction: the same unreadable file is not retried
            updates["sha256"] = sha
            updates["extracted"] = date.today().isoformat()
        if e["units_field"] != e["count"]:
            updates["units"] = e["count"]
        kind, size = kitlib.source_size(root, e["source"], sha)
        if kind and size and e.get(kind) != size:
            updates[kind] = size
        ext = os.path.splitext(e["source"])[1].lower()
        if (ext in kitlib.OFFICE_EXT or ext in kitlib.TEXT_EXT) and (e["extractor"] or 1) < kitlib.OFFICE_EXTRACTOR:
            # "extractor" says which pre-extraction the notes were written from. An older extraction
            # moves up without a re-read only when the newer extractor added nothing to its source.
            cache = kitlib.office_cache_info(root, sha)
            if cache and cache.get("extractor", 1) >= kitlib.OFFICE_EXTRACTOR and (
                    fresh or kitlib.office_recovered(cache, e["extractor"] or 1) == 0):
                updates["extractor"] = kitlib.OFFICE_EXTRACTOR
        if updates and kitlib.update_frontmatter(e["path"], updates):
            if "sha256" in updates:
                out["stamped"].append(epath)
            else:
                out["refreshed"] += 1
    ext_idx = kitlib.extraction_index(root)
    problems, warnings, _, _ = kitlib.check_extractions(root, sources, ext_idx, unsupported)
    # a source that was extracted again: the plan follows its new unit numbers mechanically
    apply_reextractions(root, out, sources, shas, ext_idx)
    kitlib.refresh_unit_sources(root, sources, shas, ext_idx)
    pruned = prune_office_cache(root, set(shas.values()))
    if pruned:
        out["removedOfficeCache"] = pruned
    out["problems"] += problems
    out["warnings"] += [w for w in warnings if not w["code"].startswith("sources.")]
    out["extractions"] = len(ext_idx)
    out["units"] = sum(e["count"] for e in ext_idx.values())


# ----------------------------------------------------------------------------- --plan
def coverage_path(root):
    return os.path.join(root, ".book-state", "plan", "coverage.json")


def do_plan(root, out, rewrite=False):
    plan_raw, err = kitlib.load_plan(root)
    if err:
        out["problems"].append({"code": "plan.missing", "detail": err})
        return
    # a setting that decides WHAT is written must be valid before anything is listed for a writer:
    # falling back to the default level here would have a whole edition written at the wrong one
    fatal = [i for i in kitlib.effective_config(kitlib.load_config(root)[0])[1] if i["fatal"]]
    if fatal:
        out["problems"] += [{"code": i["code"], "detail": i["detail"] + " — fix book.config.json; nothing is "
                             "listed for writing until then"} for i in fatal]
        return
    src0, _ = kitlib.walk_sources(root)                 # a run that stopped between stamp and plan
    apply_reextractions(root, out, src0, kitlib.source_shas(src0), kitlib.extraction_index(root))
    plan_raw, _ = kitlib.load_plan(root)
    if isinstance(plan_raw, dict) and REVIEW_KEY in plan_raw:
        # the architect's answer to "does each replaced unit still belong where it is?" — a request
        # key like renumber_request: applied to the record, then taken out of the plan
        reviewed = plan_raw.pop(REVIEW_KEY)
        reviewed = [reviewed] if isinstance(reviewed, str) else reviewed if isinstance(reviewed, list) else []
        names = {str(x).strip()[4:] if str(x).strip().startswith("ext:") else str(x).strip() for x in reviewed}
        pending = load_replan(root)
        done = sorted(k for k in pending if k in names and pending[k].get("replaced") and not pending[k].get("reviewed"))
        for k in done:
            pending[k]["reviewed"] = True
        save_replan(root, pending)
        write_json(kitlib.plan_path(root), plan_raw)
        if done:
            out["reviewed"] = done
    req = kitlib.normalize_plan(plan_raw)[0]["renumber_request"]
    if req:
        pairs = {}
        for item in req:
            a, sep, b = item.partition("=")
            if not sep:
                out["problems"].append({"code": "renumber.map", "detail": f"renumber_request entry {item!r} is not old=new"})
                return
            pairs[a.strip()] = b.strip()
        if not renumber(root, pairs, out):
            return
        plan_raw, _ = kitlib.load_plan(root)
    plan, shape = kitlib.normalize_plan(plan_raw)
    sources, unsupported = kitlib.walk_sources(root)
    ext_idx = kitlib.extraction_index(root)
    _, _, stale, _ = kitlib.check_extractions(root, sources, ext_idx, unsupported)
    kitlib.refresh_unit_sources(root, sources, kitlib.source_shas(sources), ext_idx)
    problems, warnings, info = kitlib.check_plan(plan)
    ledger, cov_problems, cov_warnings, by_section = kitlib.derive_coverage(
        plan, ext_idx, stale, read_json(coverage_path(root)))
    _replan_followup(root, plan, ext_idx, ledger, cov_problems, out)
    out["problems"] += shape + problems + cov_problems
    out["warnings"] += warnings + cov_warnings
    if not shape:
        write_json(coverage_path(root), ledger)
    raw, _ = kitlib.load_config(root)
    cfg, _ = kitlib.effective_config(raw)
    level = cfg["content"]["level"]
    kitlib.settle_ledger(root, plan, ext_idx, level)
    write = kitlib.write_plan(root, plan, ext_idx, level)
    if rewrite:                                         # the user asked for every chapter to be written again
        write = {cid: (w if w["mode"] == "full" else {"mode": "full", "reason": kitlib.REWRITE_REASON, "rewrite": True})
                 for cid, w in write.items()}
        out["rewrite"] = True
    kitlib.brief_writers(root, plan, ext_idx, level, write)   # what each writer is handed, recorded now

    # one small file per chapter, so a writer or auditor never loads the whole plan
    slices_dir = os.path.join(root, ".book-state", "plan", "slices")
    raw_by_id = {str(ch.get("id", "")).strip(): ch for ch in plan_raw.get("chapters", []) if isinstance(ch, dict)}
    keep = set()
    for ch in plan["chapters"]:
        cid = ch["id"]
        if cid not in info["pages"]:
            continue
        units, paths = {}, []
        for s in ch["sections"]:
            rows = []
            for epath, n, state in by_section.get(s["id"], []):
                u = ext_idx[epath]["units"][n]
                row = {"ref": f"ext:{epath}#U{n}", "state": state}
                if u["priority"]:
                    row["priority"] = u["priority"]
                if u["keys"]:
                    row["keys"] = u["keys"]
                if "procedure" in u["flags"]:
                    row["procedure"] = True
                rows.append(row)
                p = ".book-state/extractions/" + epath
                if p not in paths:
                    paths.append(p)
            units[s["id"]] = rows
        name = f"ch-{cid}.json"
        keep.add(name)
        write_json(os.path.join(slices_dir, name), {
            "kit": kitlib.KIT_VERSION, "level": level, "language": cfg["book"]["language"],
            "book_title": cfg["book"]["title"], "chapter": raw_by_id.get(cid, {}),
            "units": units, "extractions": paths,
            "draft": f".book-state/drafts/L{level}/ch-{cid}.html",
            "write": write.get(cid, {"mode": "full"})})
    if os.path.isdir(slices_dir):
        for name in os.listdir(slices_dir):
            if name.endswith(".json") and name not in keep:
                os.remove(os.path.join(slices_dir, name))
    out["plan"] = {"chapters": len(info["pages"]), "sections": len(info["sections"]),
                   "supplements": info["supplement_count"], "units": len(ledger)}
    out["level"] = level
    out["write"] = {cid: w for cid, w in write.items() if w["mode"] != "none"}
    out["current"] = [cid for cid, w in write.items() if w["mode"] == "none"]


# ----------------------------------------------------------------------------- audits
OPEN_STATES = kitlib.OPEN_AUDIT
_finding_part, _open = kitlib.finding_part, kitlib.finding_open


def _clean_finding(f, label):
    sev, typ = str(f.get("severity") or "").lower(), str(f.get("type") or "").lower()
    item = {"severity": sev if sev in SEVERITIES else "major", "type": typ if typ in FINDING_TYPES else "accuracy",
            "location": str(f.get("location") or label), "description": str(f.get("description") or "").strip(),
            "suggested_fix": str(f.get("suggested_fix") or "").strip(), "part": label}
    if isinstance(f.get("source"), str) and f["source"].strip():
        item["source"] = f["source"].strip()
    return item


def _edited_drafts(root, level):
    """Chapters whose draft no longer is the file its page was built from. Nothing may edit a draft
    while an audit or a recheck runs, so at merge time this means an agent overstepped. Only pages
    built at `level` can tell: a book built at another level says nothing about these drafts."""
    out = []
    plan, _ = kitlib.load_plan(root)
    for ch in kitlib.normalize_plan(plan)[0]["chapters"] if plan else []:
        try:
            with open(os.path.join(root, "book", ch["page"] or f"ch-{ch['id']}.html"), "r", encoding="utf-8", errors="replace") as f:
                head = f.read(2500)
        except OSError:
            continue
        built = re.search(r'<html[^>]*\bdata-level="(\d+)"', head)
        mo = re.search(r'name="book-kit:draft-sha" content="([0-9a-f]{64})"', head)
        if not built or int(built.group(1)) != level:
            continue
        info = kitlib.draft_info(kitlib.draft_path(root, ch["id"], level))
        if mo and info["exists"] and info["sha"] != mo.group(1):
            out.append(ch)
    return out


def _line(f):
    text = f["description"]
    tail = ""
    if f.get("carried_from"):
        tail = f" [carried from {f['carried_from']}" + ("; not re-examined by this audit" if f.get("unconfirmed") else "") + "]"
    return f"{f['id']} {f['severity']} {f['type']} {f['location']} — " + text[:140] + ("…" if len(text) > 140 else "") + tail


def _next_id(findings):
    return max([int(str(f.get("id", "F0"))[1:]) for f in findings if re.fullmatch(r"F\d+", str(f.get("id", "")))] + [0]) + 1


def void_grants(root):
    """A report is asking for approval (again): whatever the user typed before this question is
    not an answer to it. Only a /book-kit:apply-fixes typed from now on approves a batch."""
    gate = kitlib.load_gate(root)
    if gate.get("seen") and gate["grants"] > gate["used"]:
        gate["used"] = gate["grants"]
        kitlib.save_gate(root, gate)


def do_recheck(root, out, n, path, cfg):
    """Apply audit-<n>.part-recheck.json to audit-<n>.json: the auditor reports, the script edits."""
    adir = kitlib.audits_dir(root)
    rpath = os.path.join(adir, f"audit-{n}.json")
    report, part = read_json(rpath), read_json(path)
    if not isinstance(report, dict) or not isinstance(report.get("findings"), list):
        out["problems"].append({"code": "audit.recheck", "detail": f"audit-{n}.json is missing or unreadable — nothing to recheck"})
        return
    if not isinstance(part, dict) or not isinstance(part.get("results"), list):
        os.remove(path)
        report["status"] = "pending_approval"
        void_grants(root)
        write_json(rpath, report)
        out["problems"].append({"code": "audit.recheck", "detail": f"{os.path.basename(path)} is unreadable — the recheck did "
                                                                   "not happen; the report is pending_approval again"})
        return
    by_id = {f.get("id"): f for f in report["findings"] if isinstance(f, dict)}
    fixed, still, unknown = [], [], []
    for r in part["results"]:
        f = by_id.get(r.get("id")) if isinstance(r, dict) else None
        if f is None:
            unknown.append(str(r.get("id") if isinstance(r, dict) else r))
            continue
        ok = str(r.get("resolution") or "").lower() == "fixed"
        f["resolution"] = "fixed" if ok else "still_open"
        f.pop("unconfirmed", None)
        if str(r.get("note") or "").strip():
            f["recheck_note"] = str(r["note"]).strip()
        (fixed if ok else still).append(f["id"])
    new = []
    for raw in part.get("findings") or []:
        if isinstance(raw, dict):
            new.append(dict(_clean_finding(raw, _finding_part(raw)), introduced_by_fix=True))
    level = report.get("level") if report.get("level") in kitlib.LEVELS else cfg["content"]["level"]
    for ch in _edited_drafts(root, level):
        new.append({"severity": "critical", "type": "consistency", "location": ch["page"], "part": f"ch-{ch['id']}",
                    "description": f"the draft of chapter {ch['id']} changed after its page was built, while the recheck "
                                   "ran — an auditor must never edit a draft",
                    "suggested_fix": "review the change (it is not in the book yet), then rebuild or rewrite the chapter"})
    nxt = _next_id(report["findings"])
    for i, f in enumerate(new):
        report["findings"].append(dict({"id": f"F{nxt + i}"}, **f, resolution="open"))
    open_now = [f for f in report["findings"] if isinstance(f, dict) and _open(f)]
    report["status"] = "pending_approval" if open_now else "applied"
    if open_now:
        void_grants(root)
    report["open"] = {s: sum(1 for f in open_now if f.get("severity") == s) for s in SEVERITIES}
    for r in part.get("sourceReads") or []:
        if isinstance(r, dict):
            report.setdefault("sourceReads", []).append(r)
    write_json(rpath, report)
    os.remove(path)
    out["audit"] = {"report": f".book-state/audits/audit-{n}.json", "status": report["status"], "level": level,
                    "recheck": {"fixed": fixed, "still_open": still, "new": [f"F{nxt + i}" for i in range(len(new))]},
                    "open": report["open"], "findings": [_line(f) for f in open_now]}
    if unknown:
        out["warnings"].append({"code": "audit.recheck_id", "detail": f"the recheck named unknown finding ids: {', '.join(unknown)}"})


def do_merge_audit(root, out, expect, mode):
    adir = kitlib.audits_dir(root)
    parts = {}
    for name in sorted(os.listdir(adir)) if os.path.isdir(adir) else []:
        mo = re.fullmatch(r"audit-(\d+)\.part-([\w.-]+)\.json", name)
        if mo:
            parts.setdefault(int(mo.group(1)), []).append((mo.group(2), os.path.join(adir, name)))
    if not parts:
        out["problems"].append({"code": "audit.no_parts", "detail": "no audits/audit-<n>.part-*.json files to merge"})
        return
    n = max(parts)
    leftovers = [p for m, group in parts.items() if m < n for _, p in group]
    for p in leftovers:                         # parts of an audit that was abandoned midway
        os.remove(p)
    if leftovers:
        out["stale_parts_removed"] = [os.path.basename(p) for p in leftovers]
    raw, _ = kitlib.load_config(root)
    cfg, _ = kitlib.effective_config(raw)
    level = cfg["content"]["level"]
    if [label for label, _ in parts[n]] == ["recheck"]:
        do_recheck(root, out, n, parts[n][0][1], cfg)
        return
    findings, reads, labels = [], [], []
    verdicts = {}                               # id of an earlier open finding -> (resolution, note)

    def synthetic(label, text, fix="run the audit for this part again", typ="coverage", location=None):
        findings.append({"severity": "critical", "type": typ, "location": location or label, "description": text,
                         "suggested_fix": fix, "part": label, "by": "script"})

    for label, path in parts[n]:
        if label == "recheck":
            os.remove(path)
            out["warnings"].append({"code": "audit.recheck_misplaced",
                                    "detail": f"{os.path.basename(path)} arrived together with audit parts and was ignored"})
            continue
        labels.append(label)
        data = read_json(path)
        if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
            synthetic(label, f"audit part {os.path.basename(path)} is unreadable — this part of the book was not audited")
            continue
        if data.get("level") in kitlib.LEVELS and data["level"] != level:
            synthetic(label, f"audit part {os.path.basename(path)} examined the level-{data['level']} edition but "
                             f"content.level is {level} — this part of the current edition was not audited")
            continue
        for r in data.get("sourceReads") or []:
            if isinstance(r, dict):
                reads.append(r)
        for v in data.get("prior") or []:
            if isinstance(v, dict) and v.get("id"):
                verdicts[str(v["id"]).split("/")[-1]] = (str(v.get("resolution") or "").lower(), str(v.get("note") or "").strip())
        findings.extend(_clean_finding(f, label) for f in data["findings"] if isinstance(f, dict))
    for label in expect or []:
        label = label if label == "cross" else (label if label.startswith("ch-") else f"ch-{label}")
        if label not in labels:
            synthetic(label, f"no audit part for {label} — the auditor for it did not report; this part was not audited")
            labels.append(label)
    for ch in _edited_drafts(root, level):
        synthetic(f"ch-{ch['id']}", f"the draft of chapter {ch['id']} changed after its page was built, while the audit ran — "
                                    "an auditor must never edit a draft", typ="consistency", location=ch["page"],
                  fix="review the change (it is not in the book yet), then rebuild or rewrite the chapter")

    # A finding stays on the table until it is fixed or declined. Open findings of the earlier report
    # ABOUT THE SAME LEVEL move into this report — unless the auditor of that part looked at the
    # finding again and reports it fixed ("prior" in its part file). A part that was audited again
    # without a word about an old finding does not make it disappear: it is carried and marked.
    # Reports about another level's edition are not touched: their findings point at other drafts.
    carried, closed = 0, []
    for name in sorted(os.listdir(adir)):
        mo = re.fullmatch(r"audit-(\d+)\.json", name)
        if not mo or int(mo.group(1)) >= n:
            continue
        old = read_json(os.path.join(adir, name))
        if not isinstance(old, dict) or old.get("status") not in OPEN_STATES or not isinstance(old.get("findings"), list):
            continue
        if old.get("level") not in (None, level):
            out.setdefault("other_levels_open", []).append(f"A{mo.group(1)} (level {old.get('level')})")
            continue
        for f in old["findings"]:
            if not isinstance(f, dict) or not _open(f):
                continue
            part = _finding_part(f)
            verdict, note = verdicts.get(str(f.get("id")), ("", "")) if part in labels else ("", "")
            if f.get("by") == "script" and part in labels:
                # a fact the merge itself establishes (a part that did not report, a draft edited
                # during the audit): this merge looked at the same part again, so it is either raised
                # anew above — then the old copy would only double it — or no longer true
                again = any(x.get("by") == "script" and x.get("part") == part and x.get("description") == f.get("description")
                            for x in findings)
                if not again:
                    f["resolution"], f["closed_by"] = "fixed", f"A{n}"
                    closed.append(f"A{mo.group(1)}/{f.get('id', '?')}")
                continue
            if verdict == "fixed":
                f["resolution"], f["closed_by"] = "fixed", f"A{n}"
                closed.append(f"A{mo.group(1)}/{f.get('id', '?')}")
                continue
            item = _clean_finding(f, part)
            item["carried_from"] = f.get("carried_from") or f"A{mo.group(1)}/{f.get('id', '?')}"
            item["resolution"] = f.get("resolution") or "open"
            if f.get("by") == "script":
                item["by"] = "script"
            if part in labels and verdict != "still_open":
                item["unconfirmed"] = True
            if note:
                item["recheck_note"] = note
            findings.append(item)
            carried += 1
        old["status"], old["superseded_by"] = "superseded", f"A{n}"
        write_json(os.path.join(adir, name), old)
        out.setdefault("superseded", []).append(f"A{mo.group(1)}")

    findings.sort(key=lambda f: (SEVERITIES.index(f["severity"]), f["location"]))
    for i, f in enumerate(findings, 1):
        f["id"] = f"F{i}"
        f.setdefault("resolution", "open")
    summary = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITIES}
    chapters = sorted((x[3:] for x in labels if x.startswith("ch-")), key=lambda c: int(c) if c.isdigit() else 0)
    report = {"id": f"A{n}", "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "mode": mode or "full", "level": level,
              "scope": "book" if (mode or "full") == "full" else chapters,
              "status": "pending_approval" if findings else "clean",
              "summary": summary, "sourceReads": reads,
              "findings": [dict({"id": f["id"]}, **{k: v for k, v in f.items() if k != "id"}) for f in findings]}
    path = os.path.join(adir, f"audit-{n}.json")
    write_json(path, report)
    if findings:
        void_grants(root)
    for _, part in parts[n]:
        if os.path.exists(part):
            os.remove(part)
    out["audit"] = {"report": f".book-state/audits/audit-{n}.json", "status": report["status"], "level": level,
                    "summary": summary, "parts": labels, "carried": carried, "closed_prior": closed,
                    "findings": [_line(f) for f in findings]}


def do_set_audit(root, out, status, number):
    """The gate's bookkeeping: approve (before a fix batch), decline, or reopen a declined report.
    Without --audit it is the latest report about the edition of content.level — a report about
    another level's edition is never picked by default."""
    raw, _ = kitlib.load_config(root)
    level = kitlib.effective_config(raw)[0]["content"]["level"]
    n = number or kitlib.audit_latest(root, level)[0]
    path = os.path.join(kitlib.audits_dir(root), f"audit-{n}.json")
    report = read_json(path)
    if not n or not isinstance(report, dict):
        others = kitlib.audit_overview(root, level).get("other_levels")
        out["problems"].append({"code": "audit.status",
                                "detail": f"there is no audit report about the level-{level} edition to update"
                                          + (f" (open reports about other levels: {others} — set content.level back "
                                             "to work on them)" if others else "")})
        return
    now = report.get("status")
    allowed = {"approved": ("pending_approval", "approved"), "declined": ("pending_approval", "approved"),
               "pending_approval": ("declined", "approved")}[status]
    if now not in allowed:
        out["problems"].append({"code": "audit.status",
                                "detail": f"audit A{n} is {now!r} — it cannot become {status!r} "
                                          f"(only from: {', '.join(allowed)})"})
        return
    if status == "approved" and report.get("level") not in (None, level):
        out["problems"].append({"code": "audit.level",
                                "detail": f"audit A{n} examined the level-{report['level']} edition but content.level is "
                                          f"{level} — its findings point at other drafts. Set content.level back to "
                                          f"{report['level']} to apply them, or decline it and audit the current edition"})
        return
    gate_note = None
    if status == "approved" and now == "pending_approval":
        # Starting a fix batch. Two mechanical limits, so that a loop cannot come from the model alone:
        # (1) an approval is something the USER typed — /book-kit:apply-fixes, recorded by the plugin's
        #     hook; one typed command = one batch; (2) a report takes a bounded number of batches.
        acfg = kitlib.effective_config(raw)[0]["audit"]
        batches = report.get("batches") if isinstance(report.get("batches"), int) else 0
        if batches >= acfg["max_fix_batches"]:
            out["problems"].append({"code": "audit.batches",
                                    "detail": f"audit A{n} already had {batches} fix batches (audit.max_fix_batches = "
                                              f"{acfg['max_fix_batches']}). Findings that survive that many rounds need "
                                              "a decision, not another round: stop and tell the user — "
                                              "/book-kit:audit-book makes a fresh report that carries what is still open"})
            return
        gate = kitlib.load_gate(root)
        if acfg["approval_gate"] == "off":
            gate_note = "not enforced (audit.approval_gate is \"off\")"
        elif not gate.get("seen"):
            gate_note = ("not enforced — the plugin's hook has not run in this project (hooks disabled, or a "
                         "Claude Code without the UserPromptExpansion event); the approval rests on the rules alone")
        elif gate["grants"] <= gate["used"]:
            out["problems"].append({"code": "audit.gate",
                                    "detail": f"audit A{n} is not approved: no unused approval is on record. An "
                                              "approval is recorded when the USER types /book-kit:apply-fixes — one "
                                              "typed command, one fix batch. Stop, print the open findings and ask "
                                              "the user to run /book-kit:apply-fixes; do not approve in any other way "
                                              "(if hooks cannot run on this machine, the user may set "
                                              "audit.approval_gate to \"off\" in book.config.json)"})
            return
        else:
            gate["used"] = gate["grants"]
            kitlib.save_gate(root, gate)
            gate_note = "approval by the user's /book-kit:apply-fixes"
        report["batches"] = batches + 1
    report["status"] = status
    write_json(path, report)
    open_now = [f for f in report.get("findings", []) if isinstance(f, dict) and _open(f)]
    out["audit"] = {"report": f".book-state/audits/audit-{n}.json", "status": status, "level": report.get("level"),
                    "open": len(open_now)}
    if gate_note:
        out["audit"]["gate"] = gate_note
        out["audit"]["batch"] = report["batches"]
    if status == "approved" and now == "approved":
        out["audit"]["resumed"] = "an earlier fix batch was approved but did not finish — continue with the open findings"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources", action="store_true")
    ap.add_argument("--renumber", nargs="+", metavar="OLD=NEW")
    ap.add_argument("--stamp", action="store_true")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--rewrite", action="store_true", help="with --plan: every chapter is to be written again in full")
    ap.add_argument("--merge-audit", action="store_true")
    ap.add_argument("--expect", nargs="*", metavar="PART", help="with --merge-audit: parts that must exist (chapter ids, 'cross')")
    ap.add_argument("--mode", choices=("full", "scope"), help="with --merge-audit: the audit mode to record")
    ap.add_argument("--set-audit", choices=("approved", "declined", "pending_approval"), metavar="STATUS",
                    help="approved | declined | pending_approval")
    ap.add_argument("--audit", type=int, metavar="N", help="with --set-audit: the report number (default: the latest)")
    ap.add_argument("--root", help="book project root (default: current directory or $BOOK_ROOT)")
    args = ap.parse_args()
    if not (args.sources or args.renumber or args.stamp or args.plan or args.merge_audit or args.set_audit):
        ap.error("nothing to do — pass at least one action")
    root = kitlib.resolve_root(args.root)
    kitlib.require_book_project(root)
    out = {"kit": kitlib.KIT_VERSION, "problems": [], "warnings": []}
    migrated = kitlib.migrate_layout(root)
    if migrated:
        out["migrated"] = migrated
    try:
        if args.sources:
            do_sources(root, out)
        if args.renumber:
            pairs = {}
            for item in args.renumber:
                a, sep, b = item.partition("=")
                if not sep:
                    out["problems"].append({"code": "renumber.map", "detail": f"{item!r} is not old=new"})
                pairs[a.strip()] = b.strip()
            if not out["problems"]:
                renumber(root, pairs, out)
        if args.stamp:
            do_stamp(root, out)
        if args.plan:
            do_plan(root, out, rewrite=args.rewrite)
        if args.merge_audit:
            do_merge_audit(root, out, args.expect, args.mode)
        if args.set_audit:
            do_set_audit(root, out, args.set_audit, args.audit)
    except Exception as e:                                   # never leave the orchestrator with a bare traceback
        out["problems"].append({"code": "script.crash", "detail": f"sync_state.py: {type(e).__name__}: {e}"})
    failed = bool(out["problems"])
    out["status"] = "FAIL" if failed else "OK"
    for key in ("problems", "warnings"):                    # keep the console short; validate_book.py has it all
        if len(out[key]) > 40:
            codes = {}
            for x in out[key]:
                codes[x["code"]] = codes.get(x["code"], 0) + 1
            out[key + "Codes"] = codes
            out[key + "Truncated"] = f"{len(out[key]) - 40} more — run validate_book.py for the complete report"
            out[key] = out[key][:40]
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
