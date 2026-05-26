#!/usr/bin/env python3
"""Claude Code hook — appends one normalized event to the session buffer.

Activated by the plugin's hooks/hooks.json (UserPromptSubmit + PostToolUse).
Exits silently if /enable-dev-diary hasn't been run yet (no ~/.dev-diary/state.json),
so an installed-but-not-enabled plugin is harmless.

Claude Code passes the event payload as JSON on stdin:
  PostToolUse      -> { session_id, transcript_path, cwd, tool_name, tool_input, tool_response }
  UserPromptSubmit -> { session_id, transcript_path, cwd, prompt }

We normalize each into { timestamp, type, actor, tool, file, command, summary }
and append to a per-session JSONL buffer under <diary_root>/.dev-diary-buffer/.
The Stop hook (flush.py) turns the buffer into yaml + md.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


FILE_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def event_type_for(tool: str | None) -> str:
    if tool in FILE_EDIT_TOOLS:
        return "file_edit"
    if tool == "Bash":
        return "command"
    return "tool_use"


def load_diary_root() -> Path | None:
    state = Path.home() / ".dev-diary" / "state.json"
    if not state.exists():
        return None
    try:
        diary = Path(json.loads(state.read_text(encoding="utf-8"))["diary_root"])
    except (KeyError, json.JSONDecodeError):
        return None
    return diary if diary.exists() else None


def build_prompt_event(payload: dict, ts: str) -> dict:
    return {
        "timestamp": ts,
        "type": "prompt",
        "actor": "human",
        "summary": payload.get("prompt"),
    }


def build_tool_event(payload: dict, ts: str) -> dict:
    tool = payload.get("tool_name")
    etype = event_type_for(tool)
    tin = payload.get("tool_input") or {}

    summary = tin.get("description")
    if not summary:
        if etype == "command":
            summary = f"Ran: {tin.get('command', '')}"
        elif etype == "file_edit":
            summary = f"Edited {tin.get('file_path', '')}"
        else:
            fp = tin.get("file_path")
            summary = f"{tool} {fp}" if fp else tool

    return {
        "timestamp": ts,
        "type": etype,
        "actor": "ai",
        "tool": tool,
        "file": tin.get("file_path"),
        "command": tin.get("command"),
        "summary": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", default="tool_use", choices=["tool_use", "prompt"])
    args = parser.parse_args()

    payload = json.load(sys.stdin)
    session_id = payload.get("session_id")
    if not session_id:
        return

    diary_root = load_diary_root()
    if not diary_root:
        return

    buffer_dir = diary_root / ".dev-diary-buffer"
    buffer_dir.mkdir(parents=True, exist_ok=True)
    buffer_file = buffer_dir / f"{session_id}.jsonl"
    meta_file = buffer_dir / f"{session_id}.meta.json"

    # Stash transcript_path + cwd once per session — flush.py reads the model
    # name from the transcript JSONL since Claude Code doesn't pass it.
    transcript = payload.get("transcript_path")
    if transcript and not meta_file.exists():
        meta_file.write_text(
            json.dumps({"transcript_path": transcript, "cwd": payload.get("cwd")}),
            encoding="utf-8",
        )

    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    event = build_prompt_event(payload, ts) if args.event == "prompt" \
        else build_tool_event(payload, ts)

    with buffer_file.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(event, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
