#!/usr/bin/env python3
"""Claude Code Stop hook — buffer JSONL -> session yaml + md, then commit.

Reads the per-session buffer written by post_tool.py, groups events into
conversation turns, derives git context, and writes the canonical pair under:

    <diary_root>/entries/YYYY/MM/DD/{session_id[:8]}.{yaml,md}

YAML holds the technical record (diffs, command output, file changes).
Markdown holds the human-readable narrative (prompts, step-by-step, Claude replies).

Requires PyYAML:  pip install pyyaml
"""
from __future__ import annotations

import difflib
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write(
        "dev-diary: PyYAML is required. Install with: pip install pyyaml\n"
    )
    sys.exit(0)  # don't fail the agent; just skip the flush


# ---------- path resolution ------------------------------------------------

def resolve_session_paths(diary_root: Path, session_id: str) -> tuple[Path, Path]:
    """Return (yaml_path, md_path) for this session.

    Checks the last two calendar days so a session that starts before midnight
    and flushes after midnight still finds its existing file.
    """
    short_id = session_id[:8]
    now = datetime.now()
    for days_back in range(2):
        d = now - timedelta(days=days_back)
        candidate = diary_root / "entries" / f"{d:%Y}" / f"{d:%m}" / f"{d:%d}" / f"{short_id}.yaml"
        if candidate.exists():
            return candidate, candidate.with_suffix(".md")
    folder = diary_root / "entries" / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{short_id}.yaml", folder / f"{short_id}.md"


# ---------- constants ------------------------------------------------------

EXT_LANG = {
    ".py": "python",     ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".go": "go",
    ".rs": "rust",       ".java": "java",     ".kt": "kotlin",
    ".rb": "ruby",       ".cs": "csharp",     ".cpp": "cpp",
    ".c": "c",           ".h": "c",           ".swift": "swift",
    ".php": "php",       ".md": "markdown",   ".yaml": "yaml",
    ".yml": "yaml",      ".xml": "xml",       ".html": "html",
    ".css": "css",       ".sh": "bash",       ".ps1": "powershell",
    ".sql": "sql",       ".scala": "scala",   ".lua": "lua",
    ".dart": "dart",
}

YAML_NEEDS_QUOTE = re.compile(r'[:#\[\]\{\}&\*!\|>\'"%@`]|^\s|\s$|^[-?]')

DEFAULT_GIT_OPS_PATTERN = r'(?:^|[\n;&|(])\s*(?:git|gh)(?:\s|$)'


# ---------- helpers --------------------------------------------------------

def load_diary_root() -> Path | None:
    state = Path.home() / ".dev-diary" / "state.json"
    if not state.exists():
        return None
    try:
        diary = Path(json.loads(state.read_text(encoding="utf-8"))["diary_root"])
    except (KeyError, json.JSONDecodeError):
        return None
    return diary if diary.exists() else None


def git(cwd: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=False,
        )
        return out.stdout.strip().splitlines()[0] if out.stdout.strip() else None
    except (FileNotFoundError, OSError):
        return None


def log_flush(diary_root: Path, message: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
    sys.stderr.write(f"dev-diary: {line}\n")
    try:
        log_dir = diary_root / ".dev-diary-buffer"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "flush.log").open("a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")
    except OSError:
        pass


def log_flush_error(diary_root: Path, step: str, result: subprocess.CompletedProcess) -> None:
    detail = (result.stderr or result.stdout or "").strip()
    log_flush(diary_root, f"{step} failed (exit {result.returncode}): {detail}")


def redact(text: str | None, patterns: list[str], max_chars: int) -> str | None:
    if not text:
        return text
    for pat in patterns:
        text = re.sub(pat, "[REDACTED]", text)
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars] + " …[truncated]"
    return text


def redact_event(e: dict, patterns: list[str], max_chars: int) -> None:
    """In-place redaction of all user-visible text fields in an event."""
    e["command"] = redact(e.get("command"), patterns, max_chars)
    e["summary"] = redact(e.get("summary"), patterns, max_chars)
    detail = e.get("detail")
    if detail:
        for key in ("output", "old", "new", "content"):
            if key in detail:
                detail[key] = redact(detail[key], patterns, max_chars)
        for ed in detail.get("edits") or []:
            ed["old"] = redact(ed.get("old"), patterns, max_chars) or ""
            ed["new"] = redact(ed.get("new"), patterns, max_chars) or ""


def read_meta(meta_file: Path) -> tuple[Path | None, str | None]:
    if not meta_file.exists():
        return None, None
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    tp = meta.get("transcript_path")
    return (Path(tp) if tp else None), meta.get("cwd")


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def scan_transcript(transcript_path: Path | None, since: str | None) -> tuple[str | None, list[dict]]:
    """Single pass over the session transcript JSONL.
    Returns (model, message_events) where message_events carry Claude's text replies.
    """
    model: str | None = None
    messages: list[dict] = []
    if not transcript_path or not transcript_path.exists():
        return model, messages
    since_dt = parse_ts(since)
    try:
        lines = transcript_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return model, messages
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") != "assistant":
            continue
        msg = rec.get("message") or {}
        if msg.get("model"):
            model = msg["model"]
        ts = parse_ts(rec.get("timestamp"))
        if since_dt and ts and ts < since_dt:
            continue
        local_ts = ts.astimezone().isoformat(timespec="seconds") if ts else rec.get("timestamp")
        for block in msg.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                text = (block.get("text") or "").strip()
                if text:
                    messages.append({
                        "timestamp": local_ts,
                        "type": "message",
                        "actor": "ai",
                        "summary": text,
                    })
    return model, messages


def _sanitize(text: str) -> str:
    """Replace lone surrogates that Windows tools leave in captured output."""
    return text.encode("utf-8", errors="replace").decode("utf-8")


def yaml_str(s: object) -> str:
    if s is None:
        return "~"
    s = str(s)
    if s == "":
        return '""'
    if YAML_NEEDS_QUOTE.search(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def make_diff(old: str, new: str) -> str:
    """Compact unified diff without the --- +++ file-name header lines."""
    lines = list(difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        lineterm="",
    ))
    if len(lines) <= 2:
        return ""
    return "".join(lines[2:])  # strip --- +++ header


# ---------- turn grouping --------------------------------------------------

def group_into_turns(events: list[dict]) -> list[dict]:
    """Group flat event list into turns, each starting at a prompt event.

    Each turn has:
      id, prompt, started_at, ended_at, actions (file_edit/command/tool_use),
      messages (Claude's text replies — MD only, not YAML actions).
    """
    turns: list[dict] = []
    current: dict | None = None
    turn_num = 0

    def close_turn() -> None:
        if current is not None:
            turns.append(current)

    for e in events:
        if e["type"] == "prompt":
            close_turn()
            turn_num += 1
            current = {
                "id": f"turn-{turn_num}",
                "prompt": e["summary"],
                "started_at": e["timestamp"],
                "ended_at": e["timestamp"],
                "actions": [],
                "messages": [],
            }
        else:
            if current is None:
                turn_num += 1
                current = {
                    "id": f"turn-{turn_num}",
                    "prompt": None,
                    "started_at": e["timestamp"],
                    "ended_at": e["timestamp"],
                    "actions": [],
                    "messages": [],
                }
            current["ended_at"] = e["timestamp"]
            if e["type"] == "message":
                current["messages"].append(e.get("summary") or "")
            else:
                current["actions"].append(e)

    close_turn()
    return turns


# ---------- emit helpers ---------------------------------------------------

def _block_literal(text: str, base_indent: str) -> list[str]:
    """Render text as a YAML literal block scalar (|)."""
    inner = base_indent + "  "
    lines = [f"|\n"]
    for line in text.splitlines():
        lines.append(f"{inner}{line}\n")
    return ["".join(lines).rstrip()]


def action_yaml_lines(e: dict, pad: str = "      ") -> list[str]:
    """Render one action event as YAML lines at the given indent."""
    t = e.get("type")
    detail = e.get("detail") or {}
    L: list[str] = []

    if t == "file_edit":
        tool = e.get("tool", "")
        L += [f"{pad}- type: file_edit", f"{pad}  tool: {yaml_str(tool)}",
              f"{pad}  file: {yaml_str(e.get('file'))}"]
        if tool == "Edit":
            diff = make_diff(detail.get("old") or "", detail.get("new") or "")
            if diff:
                L.append(f"{pad}  diff: |")
                for dl in diff.splitlines():
                    L.append(f"{pad}    {dl}")
        elif tool == "Write":
            if detail.get("total_lines"):
                L.append(f"{pad}  lines: {detail['total_lines']}")
            snippet = (detail.get("content") or "")
            if snippet:
                first20 = "\n".join(snippet.splitlines()[:20])
                L.append(f"{pad}  snippet: |")
                for sl in first20.splitlines():
                    L.append(f"{pad}    {sl}")
        elif tool == "MultiEdit":
            edits = detail.get("edits") or []
            if edits:
                L.append(f"{pad}  edits:")
                for ed in edits:
                    diff = make_diff(ed.get("old") or "", ed.get("new") or "")
                    if diff:
                        L.append(f"{pad}    - diff: |")
                        for dl in diff.splitlines():
                            L.append(f"{pad}        {dl}")

    elif t == "command":
        L += [f"{pad}- type: command", f"{pad}  cmd: {yaml_str(e.get('command'))}"]
        output = (detail.get("output") or "").strip()
        if output:
            L.append(f"{pad}  output: |")
            for ol in output.splitlines()[:30]:
                L.append(f"{pad}    {ol}")

    elif t == "tool_use":
        L += [f"{pad}- type: tool_use", f"{pad}  tool: {yaml_str(e.get('tool'))}"]
        if e.get("summary"):
            L.append(f"{pad}  summary: {yaml_str(e.get('summary'))}")

    return L


# ---------- emit -----------------------------------------------------------

def emit_yaml(path: Path, *, session_id: str, model: str | None,
              git_name: str | None, git_email: str | None,
              repo_url: str | None, branch: str | None, issue_ref: str | None,
              languages: list[str], started_at: str, ended_at: str,
              turns: list[dict], files_touched: list[str]) -> None:
    L = [f"session_id: {session_id}", "",
         "agent:",
         "  name: claude-code",
         f"  model: {yaml_str(model)}",
         "",
         "user:",
         f"  git_name: {yaml_str(git_name)}",
         f"  git_email: {yaml_str(git_email)}",
         ""]
    if repo_url or branch:
        L.append("project:")
        if repo_url: L.append(f"  repo: {yaml_str(repo_url)}")
        if branch:   L.append(f"  branch: {yaml_str(branch)}")
        L.append("")
    if issue_ref:
        L += ["issue:", f"  ref: {yaml_str(issue_ref)}", ""]
    if languages:
        L += ["languages: [" + ", ".join(yaml_str(x) for x in languages) + "]", ""]
    L += [f"started_at: {started_at}", f"ended_at:   {ended_at}", "", "turns:"]

    for turn in turns:
        L.append(f"  - id: {turn['id']}")
        if turn.get("prompt"):
            L.append(f"    prompt: {yaml_str(turn['prompt'])}")
        L += [f"    started_at: {turn['started_at']}", f"    ended_at:   {turn['ended_at']}"]
        actions = [a for a in turn.get("actions", [])
                   if a.get("type") in ("file_edit", "command", "tool_use")]
        if actions:
            L.append("    actions:")
            for a in actions:
                L.extend(action_yaml_lines(a))

    cmd_count = sum(
        len([a for a in t.get("actions", []) if a.get("type") == "command"])
        for t in turns
    )
    L += ["", "summary:"]
    if files_touched:
        L.append("  files_changed:")
        for f in files_touched:
            L.append(f"    - {yaml_str(f)}")
    if cmd_count:
        L.append(f"  commands_run: {cmd_count}")
    L.append(f"  turns: {len(turns)}")

    path.write_text(_sanitize("\n".join(L) + "\n"), encoding="utf-8", newline="\n")


def emit_md(path: Path, *, date: str, short_id: str,
            git_name: str | None, git_email: str | None,
            repo_url: str | None, branch: str | None, issue_ref: str | None,
            started_at: str, ended_at: str,
            turns: list[dict], files_touched: list[str]) -> None:
    L = [f"# {date} — {short_id}", ""]
    L.append("- **Agent:** claude-code")
    if git_name or git_email: L.append(f"- **User:** {git_name} <{git_email}>")
    if repo_url:              L.append(f"- **Repo:** {repo_url} @ `{branch}`")
    if issue_ref:             L.append(f"- **Issue:** {issue_ref}")
    L.append(f"- **Span:** {started_at} → {ended_at}")
    L.append("")

    for turn in turns:
        header = turn.get("prompt") or "(no prompt)"
        L += [f"## {turn['id']} — {header}", ""]

        step = 1
        for a in turn.get("actions", []):
            try:
                hhmm = datetime.fromisoformat(a["timestamp"]).strftime("%H:%M")
            except (ValueError, KeyError):
                hhmm = "??"
            t = a.get("type")
            tool = a.get("tool", "")
            if t == "file_edit":
                label = f"**{tool}** `{a.get('file', '')}`"
            elif t == "command":
                cmd = (a.get("command") or "")
                cmd_short = cmd[:80] + ("…" if len(cmd) > 80 else "")
                label = f"**$** `{cmd_short}`"
            else:
                label = f"**{tool}** {a.get('summary', '')}"
            L.append(f"{step}. **{hhmm}** — {label}")
            step += 1

        for msg in turn.get("messages", []):
            preview = (msg or "")[:300].replace("\n", " ")
            if preview:
                L += ["", f"> {preview}{'…' if len(msg) > 300 else ''}"]
        L.append("")

    if files_touched:
        L += ["## Files touched", ""]
        L.extend(f"- `{f}`" for f in files_touched)
    L.append("")
    path.write_text(_sanitize("\n".join(L)), encoding="utf-8", newline="\n")


# ---------- main -----------------------------------------------------------

def main() -> None:
    payload = json.load(sys.stdin)
    session_id = payload.get("session_id")
    if not session_id:
        return

    diary_root = load_diary_root()
    if not diary_root:
        return

    buffer_dir  = diary_root / ".dev-diary-buffer"
    buffer_file = buffer_dir / f"{session_id}.jsonl"
    meta_file   = buffer_dir / f"{session_id}.meta.json"
    if not buffer_file.exists():
        return

    events: list[dict] = []
    for line in buffer_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    if not events:
        return

    turn_start = events[0]["timestamp"]

    # ---- config -----------------------------------------------------------
    config_file = diary_root / "dev-diary.config.yaml"
    config = yaml.safe_load(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
    redaction   = config.get("redaction") or {}
    patterns    = redaction.get("patterns") or []
    capture_cfg = config.get("capture") or {}
    max_chars   = int(capture_cfg.get("max_payload_chars") or 0)

    for e in events:
        redact_event(e, patterns, max_chars)

    # Drop git/gh plumbing commands
    if capture_cfg.get("ignore_git_ops", True):
        git_ops_re = re.compile(capture_cfg.get("git_ops_pattern") or DEFAULT_GIT_OPS_PATTERN)
        events = [
            e for e in events
            if not (e.get("type") == "command" and e.get("command")
                    and git_ops_re.search(e["command"]))
        ]

    # ---- meta -------------------------------------------------------------
    transcript_path, session_cwd = read_meta(meta_file)

    # ---- git context (from the session's working repo) --------------------
    git_dir = Path(session_cwd) if session_cwd and Path(session_cwd).is_dir() else diary_root
    git_name  = git(git_dir, "config", "user.name")
    git_email = git(git_dir, "config", "user.email")
    repo_url  = git(git_dir, "config", "--get", "remote.origin.url")
    branch    = git(git_dir, "rev-parse", "--abbrev-ref", "HEAD")

    issue_ref = None
    issue_cfg = config.get("issue_detection") or {}
    branch_pat = issue_cfg.get("branch_pattern")
    if branch and branch_pat:
        m = re.search(branch_pat, branch)
        if m:
            issue_ref = f"#{m.group(1)}"

    # ---- transcript: model + Claude's text replies ------------------------
    model, message_events = scan_transcript(transcript_path, turn_start)
    for e in message_events:
        e["summary"] = redact(e.get("summary"), patterns, max_chars)

    events = sorted(
        events + message_events,
        key=lambda e: parse_ts(e.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc),
    )
    if not events:
        return

    # ---- languages --------------------------------------------------------
    languages = sorted({
        EXT_LANG[Path(e["file"]).suffix.lower()]
        for e in events
        if e.get("file") and Path(e["file"]).suffix.lower() in EXT_LANG
    })

    # ---- destination + grouping ------------------------------------------
    short_id = session_id[:8]
    yaml_path, md_path = resolve_session_paths(diary_root, session_id)
    turns = group_into_turns(events)

    started_at    = events[0]["timestamp"]
    ended_at      = events[-1]["timestamp"]
    files_touched = sorted({e["file"] for e in events if e.get("file")})

    # ---- emit -------------------------------------------------------------
    emit_yaml(
        yaml_path,
        session_id=session_id, model=model,
        git_name=git_name, git_email=git_email,
        repo_url=repo_url, branch=branch, issue_ref=issue_ref,
        languages=languages, started_at=started_at, ended_at=ended_at,
        turns=turns, files_touched=files_touched,
    )
    emit_md(
        md_path,
        date=yaml_path.parent.name, short_id=short_id,
        git_name=git_name, git_email=git_email,
        repo_url=repo_url, branch=branch, issue_ref=issue_ref,
        started_at=started_at, ended_at=ended_at,
        turns=turns, files_touched=files_touched,
    )

    # ---- commit + push ----------------------------------------------------
    push_cfg = config.get("push") or {}
    push_on  = push_cfg.get("when") or push_cfg.get("on") or push_cfg.get(True)
    if push_on in ("session_end", "every_n_minutes"):
        msg      = f"dev-diary: claude-code {short_id} on {branch}"
        rel_yaml = str(yaml_path.relative_to(diary_root))
        rel_md   = str(md_path.relative_to(diary_root))

        commit_cmd = ["git"]
        if not push_cfg.get("sign_commits", False):
            commit_cmd += ["-c", "commit.gpgsign=false"]
        commit_cmd += ["commit", "-m", msg, "--quiet"]

        def run(cmd: list[str]) -> subprocess.CompletedProcess:
            return subprocess.run(cmd, cwd=diary_root, capture_output=True, text=True)

        add_res = run(["git", "add", rel_yaml, rel_md])
        if add_res.returncode != 0:
            log_flush_error(diary_root, "git add", add_res)
        elif run(["git", "diff", "--cached", "--quiet"]).returncode != 0:
            commit_res = run(commit_cmd)
            if commit_res.returncode != 0:
                log_flush_error(diary_root, "git commit", commit_res)
            elif push_on == "every_n_minutes":
                remote = push_cfg.get("remote", "origin")
                target_branch = push_cfg.get("branch", "main")
                push_res = run(["git", "push", remote, target_branch, "--quiet"])
                if push_res.returncode != 0:
                    log_flush_error(diary_root, "git push", push_res)
    elif push_on != "manual":
        log_flush(
            diary_root,
            f"push.when is missing or invalid (got {push_on!r}); entries written "
            f"but not committed. Set push.when to session_end, every_n_minutes, "
            f"or manual in dev-diary.config.yaml.",
        )

    # Buffer kept — subsequent turns append to it; cleanup at next session start.


if __name__ == "__main__":
    main()
