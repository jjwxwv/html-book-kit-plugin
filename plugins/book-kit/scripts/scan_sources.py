#!/usr/bin/env python3
"""Compare sources/ with the committed manifest and with the kit's state, and say what to do next.

Usage (project = current directory, or --root <dir>):
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan_sources.py" --status   # report only
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan_sources.py" --commit   # also write .book-state/manifest.json

Prints one JSON object the orchestrator routes from, so it never has to read state files itself:
  summary / diff   sources added, changed, removed, renamed (same SHA-256, new path) since the last commit
  unsupported      files under sources/ the kit cannot read (not part of the book)
  office.refresh   .pptx/.docx that need extract_office.py --all first
  state            what sync_state.py --sources will do: path remaps, stale state to delete, renumbering
  extract          sources without a current extraction — the ONLY files an analyst has to read
                   (decided by SHA-256 of the extraction, so an interrupted run resumes without re-reading)
  stamp            extractions waiting for sync_state.py --stamp
  chapters         chapter ids of the plan, in order
  level            at content.level: write_full (chapters without a draft), write_delta (chapters whose
                   inputs changed since the draft was written, with the sections), current
  audit            latest report and its status, the number the next audit gets
  config           effective values of book.config.json
--status never touches sources or content. One exception to "no write": a v11.0 project's drafts are
moved once into the per-level folders (.book-state/drafts/L<level>/), losslessly.
Exit 0 always (informational); 2 when the directory is not a book project.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitlib  # noqa: E402


def load_manifest(path):
    """{path: {"sha256", "size"}} of the last commit; {} when absent or unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            files = json.load(f).get("files", {})
    except (OSError, ValueError, AttributeError) as e:
        if os.path.isfile(path):
            print(f"warning: could not read manifest ({e}); treating all as new", file=sys.stderr)
        return {}
    if not isinstance(files, dict):
        return {}
    return {p: m for p, m in files.items() if isinstance(m, dict) and isinstance(m.get("sha256"), str)}


def diff(old, new):
    added, changed, renamed, unchanged = [], [], [], []
    old_by_sha = {}
    for p, meta in old.items():
        old_by_sha.setdefault(meta["sha256"], []).append(p)
    consumed_old = set()
    for p, meta in sorted(new.items()):
        if p in old:
            consumed_old.add(p)
            (unchanged if old[p]["sha256"] == meta["sha256"] else changed).append(p)
        else:
            candidates = [q for q in old_by_sha.get(meta["sha256"], []) if q not in new and q not in consumed_old]
            if candidates:
                consumed_old.add(candidates[0])
                renamed.append({"from": candidates[0], "to": p})
            else:
                added.append(p)
    removed = sorted(p for p in old if p not in consumed_old)
    return {"added": added, "changed": changed, "removed": removed, "renamed": renamed, "unchanged": unchanged}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true", help="report only")
    g.add_argument("--commit", action="store_true", help="write the manifest")
    ap.add_argument("--root", help="book project root (default: current directory or $BOOK_ROOT)")
    args = ap.parse_args()
    root = kitlib.resolve_root(args.root)
    kitlib.require_book_project(root)
    migrated = kitlib.migrate_layout(root)

    sources, unsupported = kitlib.walk_sources(root)
    shas = kitlib.source_shas(sources)
    new = {rel: {"sha256": shas[rel], "size": os.path.getsize(full)} for rel, full in sources.items()}
    manifest = os.path.join(root, ".book-state", "manifest.json")
    d = diff(load_manifest(manifest), new)
    out = {"kit": kitlib.KIT_VERSION, "root": root, "sourceCount": len(new),
           "summary": {k: len(v) for k, v in d.items()},
           "diff": {k: v for k, v in d.items() if k != "unchanged"}}
    if not new:
        out["note"] = "no source files found under sources/ — see sources/README.md for the expected layout"
    if unsupported:
        out["unsupported"] = unsupported
    if args.commit:
        os.makedirs(os.path.dirname(manifest), exist_ok=True)
        with open(manifest, "w", encoding="utf-8") as f:
            json.dump({"committed": datetime.now(timezone.utc).isoformat(timespec="seconds"), "files": new},
                      f, indent=2, ensure_ascii=False)
        out["committed"] = True

    # state: what has to be read, remapped, deleted
    ext_idx = kitlib.extraction_index(root)
    needs = kitlib.extraction_needs(root, sources, shas, ext_idx)
    plan_raw, _ = kitlib.load_plan(root)
    plan, _ = kitlib.normalize_plan(plan_raw) if plan_raw is not None else ({"chapters": [], "omitted": [],
                                                                            "has_omitted": False}, [])
    if needs["refresh"]:
        out["office"] = {"refresh": needs["refresh"],
                         "do": "run extract_office.py --all, then scan again (slide and line counts and recovered content appear)"}
    state = {}
    if needs["renames"]:
        state["renames"] = [{"from": old, "to": new_} for _, old, new_ in needs["renames"]]
        mapping, why_not = kitlib.suggest_renumber(plan, ext_idx, needs["renames"], shas) if plan_raw is not None else ({}, None)
        if mapping:
            state["renumber"] = mapping
        elif why_not:
            state["renumber_skipped"] = why_not
    if needs["stale"]:
        state["stale"] = needs["stale"]
    if state:
        state["do"] = "run sync_state.py --sources"
        out["state"] = state
    out["extract"] = needs["extract"]
    if any(x.get("pages") is None for x in needs["extract"] if x["path"].lower().endswith(".pdf")):
        out["pdf_pages"] = "unknown — pip install pypdf lets the kit check that long PDFs were read to the end"
    if needs["errors"]:
        out["extraction_errors"] = needs["errors"]
    if needs["unstamped"]:
        out["stamp"] = {"count": len(needs["unstamped"]), "do": "run sync_state.py --stamp"}
    replan = kitlib.replan_open(root, ext_idx, plan) if plan_raw is not None else []
    if replan:
        # a source was extracted again and the plan has not answered everything yet (a run that
        # stopped between the stamp and the architect): the architect is due before the next plan check
        out["replan"] = {"extractions": replan,
                         "do": "delegate book-kit:book-architect (delta) with these entries, then run sync_state.py --plan"}
    if needs["unread_visuals"]:
        out["unread_visuals"] = {"files": needs["unread_visuals"],
                                 "tell_user": "pictures and embedded objects in these files cannot be read; export the "
                                              "file to PDF and put the PDF in sources/ if they carry teaching content"}

    # config, level, audit
    raw, cfg_error = kitlib.load_config(root)
    cfg, issues = kitlib.effective_config(raw)
    level = cfg["content"]["level"]
    config = {"level": level, "level_name": kitlib.LEVELS[level]["key"],
              "language": cfg["book"]["language"],
              "recall_questions": cfg["content"]["recall_questions"],
              "palette": cfg["ui"]["palette"],
              "max_parallel_agents": cfg["pipeline"]["max_parallel_agents"],
              "max_source_spot_checks": cfg["audit"]["max_source_spot_checks"]}
    if cfg["pipeline"]["models"]:
        config["models"] = cfg["pipeline"]["models"]
    notes = ([cfg_error] if cfg_error else []) + [i["detail"] for i in issues]
    if notes:
        config["issues"] = notes
    out["config"] = config

    lv = {"config": level, "book": None, "book_exists": False, "write_full": [], "write_delta": {}, "current": []}
    out["plan"] = plan_raw is not None
    out["chapters"] = [ch["id"] for ch in plan["chapters"] if re.fullmatch(r"\d+", ch["id"])]
    if plan_raw is not None:
        for cid, w in kitlib.write_plan(root, plan, ext_idx, level).items():
            if w["mode"] == "full":
                lv["write_full"].append(cid)
            elif w["mode"] == "delta":
                lv["write_delta"][cid] = {k: v for k, v in w.items() if k != "mode" and v}
            else:
                lv["current"].append(cid)
        cached = {}
        for other in kitlib.LEVELS:
            if other != level:
                have = [ch["id"] for ch in plan["chapters"]
                        if kitlib.draft_info(kitlib.draft_path(root, ch["id"], other))["exists"]]
                if have:
                    cached[str(other)] = have
        if cached:
            lv["other_levels_cached"] = cached
        outdated = kitlib.style_outdated(root, plan, level)
        if outdated:
            lv["style_outdated"] = {"chapters": outdated,
                                    "tell_user": "content.audience / content.style_notes changed after these chapters "
                                                 "were written; they keep their wording until they are next written — "
                                                 "/book-kit:build-book --rewrite applies the new style to the whole book"}
    try:
        with open(os.path.join(root, "book", "index.html"), "r", encoding="utf-8", errors="replace") as f:
            m = re.search(r'<html[^>]*\bdata-level="(\d+)"', f.read(1000))
        lv["book_exists"] = True
        lv["book"] = int(m.group(1)) if m else None
    except OSError:
        pass
    out["level"] = lv

    audit = kitlib.audit_overview(root, level)
    # audit.max_source_spot_checks is the budget of one audit: it is shared out, never exceeded
    # (except that every chapter auditor keeps one, so a book with more chapters than budget
    # reads one location per chapter)
    n_chapters = max(1, len([ch for ch in plan["chapters"] if ch["id"]]))
    total = cfg["audit"]["max_source_spot_checks"]
    audit["spot_checks_per_chapter"] = 0 if total == 0 else max(1, total // n_chapters)
    if audit.get("status") in kitlib.OPEN_AUDIT:
        # what the approval gate will say (sync_state.py --set-audit approved decides; this only shows it)
        gate, _, rep = kitlib.load_gate(root), *kitlib.audit_latest(root, level)
        batches = rep.get("batches") if rep and isinstance(rep.get("batches"), int) else 0
        enforced = cfg["audit"]["approval_gate"] != "off" and bool(gate.get("seen"))
        audit["approval"] = {"enforced": enforced, "batches": batches, "max_batches": cfg["audit"]["max_fix_batches"]}
        if enforced:
            audit["approval"]["on_record"] = gate["grants"] > gate["used"]
        else:
            audit["approval"]["note"] = ("audit.approval_gate is off" if cfg["audit"]["approval_gate"] == "off" else
                                         "the plugin's hook has not run in this project — approvals rest on the rules alone")
    out["audit"] = audit
    if migrated:
        out["migrated"] = migrated
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
