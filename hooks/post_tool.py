#!/usr/bin/env python3
"""Claude Code hook — appends one normalized event to the session buffer.

Activated by the plugin's hooks/hooks.json (UserPromptSubmit + PostToolUse).
Exits silently if /dev-diary:enable hasn't been run yet (no ~/.dev-diary/state.json),
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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


FILE_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def event_type_for(tool: str | None) -> str:
    if tool in FILE_EDIT_TOOLS:
        return "file_edit"
    if tool == "Bash":
        return "command"
    return "tool_use"


def _push_pending(diary_root: Path) -> None:
    """Push unpushed diary commits if push.when == session_end.

    Called at the start of each new session (UserPromptSubmit) so the previous
    session's commits are sent in one push rather than after every turn.
    """
    if yaml is None:
        return
    config_file = diary_root / "dev-diary.config.yaml"
    try:
        config = yaml.safe_load(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
    except Exception:
        config = {}
    push_cfg = (config or {}).get("push") or {}
    push_on = push_cfg.get("when") or push_cfg.get("on") or push_cfg.get(True)
    if push_on != "session_end":
        return
    try:
        ahead = subprocess.run(
            ["git", "rev-list", "--count", "@{u}..HEAD"],
            cwd=diary_root, capture_output=True, text=True, check=False, timeout=10,
        )
        if ahead.returncode != 0 or int(ahead.stdout.strip() or "0") == 0:
            return
        remote = push_cfg.get("remote", "origin")
        branch = push_cfg.get("branch", "main")
        subprocess.run(
            ["git", "push", remote, branch, "--quiet"],
            cwd=diary_root, capture_output=True, check=False, timeout=30,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass


def _cleanup_stale_buffers(buffer_dir: Path, current_session_id: str) -> None:
    """Delete buffer files from sessions that have already been committed."""
    if not buffer_dir.exists():
        return
    reg_file = buffer_dir / "registry.json"
    try:
        registry = json.loads(reg_file.read_text(encoding="utf-8")) if reg_file.exists() else {}
    except (json.JSONDecodeError, OSError):
        registry = {}
    for jsonl_file in buffer_dir.glob("*.jsonl"):
        sid = jsonl_file.stem
        if sid != current_session_id and sid in registry:
            jsonl_file.unlink(missing_ok=True)
            (buffer_dir / f"{sid}.meta.json").unlink(missing_ok=True)


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

    if args.event == "prompt":
        _push_pending(diary_root)
        _cleanup_stale_buffers(buffer_dir, session_id)

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
