#!/usr/bin/env python3
"""The plugin's UserPromptExpansion hook: the approval gate of the audit.

Claude Code runs this when the USER types a book-kit command (never when the model starts a skill
itself — that goes through the Skill tool and fires no UserPromptExpansion). In a book project it
writes .book-state/audits/gate.json:

  seen    when the hook last ran here — proof that hooks work in this project. Without it,
          sync_state.py does not enforce the gate (it says so) instead of refusing every approval.
  grants  how often the user typed /book-kit:apply-fixes. One typed command = one approval =
          one fix batch: `sync_state.py --set-audit approved` spends it, and a report that
          (again) asks for approval voids whatever was typed before the question.

Standard library only, no import of the kit: it runs on every typed kit command and must be fast.
Prints nothing (stdout of this event would be added to the conversation) and always exits 0 — a
broken gate must never block the user's command. Outside a book project it does nothing.

This is a guard against a loop that starts by accident, not a security boundary: the session can
write under .book-state/, so a model that deliberately edits gate.json is not stopped by it.
"""
import json
import os
import sys
from datetime import datetime, timezone

PLUGIN = "book-kit"
GRANTING = "apply-fixes"


def command_name(data):
    """The typed command without its leading slash, or "" when it is not one of this plugin's."""
    name = str(data.get("command_name") or "").strip().lstrip("/")
    typed = str(data.get("prompt") or "").strip().split(None, 1)
    typed = typed[0].lstrip("/") if typed and typed[0].startswith("/") else ""
    for candidate in (name, typed):
        if candidate.startswith(PLUGIN + ":"):
            return candidate.split(":", 1)[1]
    return ""


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(data, dict) or data.get("hook_event_name") != "UserPromptExpansion":
        return 0
    if data.get("expansion_type") not in (None, "slash_command") or data.get("agent_id"):
        return 0
    cmd = command_name(data)
    if not cmd:
        return 0
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    state = os.path.join(root, ".book-state")
    if not (os.path.isfile(os.path.join(root, "book.config.json")) and os.path.isdir(state)):
        return 0
    path = os.path.join(state, "audits", "gate.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            gate = json.load(f)
        if not isinstance(gate, dict):
            gate = {}
    except (OSError, ValueError):
        gate = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    count = lambda key: gate[key] if isinstance(gate.get(key), int) and not isinstance(gate.get(key), bool) and gate[key] >= 0 else 0  # noqa: E731
    gate = {"seen": now, "grants": count("grants"), "used": count("used"), "last_command": cmd,
            **({"granted_at": gate["granted_at"]} if isinstance(gate.get("granted_at"), str) else {})}
    if cmd == GRANTING:
        gate["grants"] += 1
        gate["granted_at"] = now
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(gate, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)
    return 0


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
