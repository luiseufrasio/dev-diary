#!/usr/bin/env python3
"""Claude Code Stop hook — buffer JSONL -> session yaml + md, then commit.

Reads the per-session buffer written by post_tool.py, redacts secrets, derives
git context (user, repo, branch, issue ref), detects languages from touched
files, and writes the canonical pair under:

    <diary_root>/entries/YYYY/MM/YYYY-MM-DD/session-NNN.{yaml,md}

Then (per config.push.when) commits and pushes.

Requires PyYAML for reading the user's dev-diary.config.yaml — install via:
    pip install pyyaml
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write(
        "dev-diary: PyYAML is required. Install with: pip install pyyaml\n"
    )
    sys.exit(0)  # don't fail the agent; just skip the flush


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


def git(diary_root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=diary_root, capture_output=True, text=True, check=False,
        )
        return out.stdout.strip().splitlines()[0] if out.stdout.strip() else None
    except (FileNotFoundError, OSError):
        return None


def log_flush_error(diary_root: Path, step: str, result: subprocess.CompletedProcess) -> None:
    """Record a failed git step so silent commit/push failures are diagnosable.

    Writes to <diary_root>/.dev-diary-buffer/flush.log (gitignored) and stderr.
    The Stop hook runs non-interactively, so a failing commit/push would
    otherwise vanish — this surfaces the actual git error."""
    detail = (result.stderr or result.stdout or "").strip()
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {step} failed " \
           f"(exit {result.returncode}): {detail}"
    sys.stderr.write(f"dev-diary: {line}\n")
    try:
        log_dir = diary_root / ".dev-diary-buffer"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "flush.log").open("a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")
    except OSError:
        pass


def redact(text: str | None, patterns: list[str], max_chars: int) -> str | None:
    if not text:
        return text
    for pat in patterns:
        text = re.sub(pat, "[REDACTED]", text)
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars] + " …[truncated]"
    return text


def resolve_model(meta_file: Path) -> str | None:
    """Walk the session transcript JSONL and return the model from the last
    assistant turn. Best-effort — transcript shape may shift between releases."""
    if not meta_file.exists():
        return None
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        transcript = Path(meta.get("transcript_path", ""))
        if not transcript.exists():
            return None
        last_model = None
        for line in transcript.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") == "assistant":
                model = (rec.get("message") or {}).get("model")
                if model:
                    last_model = model
        return last_model
    except (OSError, json.JSONDecodeError):
        return None


def yaml_str(s) -> str:
    if s is None:
        return "~"
    s = str(s)
    if s == "":
        return '""'
    if YAML_NEEDS_QUOTE.search(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def next_session_num(folder: Path) -> int:
    nums = []
    for p in folder.glob("session-*.yaml"):
        m = re.match(r"session-(\d+)", p.stem)
        if m:
            nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1


# ---------- emit -----------------------------------------------------------

def emit_yaml(path: Path, *, session_id, model, git_name, git_email,
              repo_url, branch, issue_ref, languages, started_at, ended_at,
              events, prompt, files_touched) -> None:
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
        L.append("issue:")
        L.append(f"  ref: {yaml_str(issue_ref)}")
        L.append("")
    if languages:
        L.append("languages: [" + ", ".join(yaml_str(x) for x in languages) + "]")
        L.append("")
    L.append(f"started_at: {started_at}")
    L.append(f"ended_at:   {ended_at}")
    L.append("")
    L.append("events:")
    for e in events:
        L.append(f"  - timestamp: {e['timestamp']}")
        L.append(f"    type: {e['type']}")
        L.append(f"    actor: {e['actor']}")
        if e.get("tool"):    L.append(f"    tool: {yaml_str(e['tool'])}")
        if e.get("file"):    L.append(f"    file: {yaml_str(e['file'])}")
        if e.get("command"): L.append(f"    command: {yaml_str(e['command'])}")
        if e.get("summary"): L.append(f"    summary: {yaml_str(e['summary'])}")
    L.append("")
    L.append("summary:")
    if prompt: L.append(f"  prompt: {yaml_str(prompt)}")
    if files_touched:
        L.append("  files_touched:")
        for f in files_touched:
            L.append(f"    - {yaml_str(f)}")

    path.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")


def emit_md(path: Path, *, date, session_tag, git_name, git_email, repo_url,
            branch, issue_ref, started_at, ended_at, prompt, events,
            files_touched) -> None:
    L = [f"# {date} — Session {session_tag}", ""]
    L.append("- **Agent:** claude-code")
    if git_name or git_email: L.append(f"- **User:** {git_name} <{git_email}>")
    if repo_url:              L.append(f"- **Repo:** {repo_url} @ `{branch}`")
    if issue_ref:             L.append(f"- **Issue:** {issue_ref}")
    L.append(f"- **Span:** {started_at} → {ended_at}")
    L.append("")
    if prompt:
        L.extend(["## Prompt", "", f"> {prompt}", ""])
    L.extend(["## Step by step", ""])
    for i, e in enumerate(events, start=1):
        try:
            hhmm = datetime.fromisoformat(e["timestamp"]).strftime("%H:%M")
        except ValueError:
            hhmm = e["timestamp"][:5]
        label = (e.get("summary")
                 or (f"$ {e['command']}" if e.get("command") else None)
                 or (f"{e.get('tool')} {e.get('file')}" if e.get("file") else None)
                 or f"{e['type']} ({e.get('tool')})")
        L.append(f"{i}. **{hhmm}** — *{e['actor']}* {label}")
    if files_touched:
        L.extend(["", "## Files touched", ""])
        L.extend(f"- `{f}`" for f in files_touched)
    L.append("")
    path.write_text("\n".join(L), encoding="utf-8", newline="\n")


# ---------- main -----------------------------------------------------------

def main() -> None:
    payload = json.load(sys.stdin)
    session_id = payload.get("session_id")
    if not session_id:
        return

    diary_root = load_diary_root()
    if not diary_root:
        return

    buffer_file = diary_root / ".dev-diary-buffer" / f"{session_id}.jsonl"
    meta_file   = diary_root / ".dev-diary-buffer" / f"{session_id}.meta.json"
    if not buffer_file.exists():
        return

    events = []
    for line in buffer_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    if not events:
        buffer_file.unlink(missing_ok=True)
        meta_file.unlink(missing_ok=True)
        return

    # ---- config -----------------------------------------------------------
    config_file = diary_root / "dev-diary.config.yaml"
    config = yaml.safe_load(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
    redaction = config.get("redaction") or {}
    patterns  = redaction.get("patterns") or []
    max_chars = int((config.get("capture") or {}).get("max_payload_chars") or 0)
    for e in events:
        e["command"] = redact(e.get("command"), patterns, max_chars)
        e["summary"] = redact(e.get("summary"), patterns, max_chars)

    # ---- git + issue ------------------------------------------------------
    git_name  = git(diary_root, "config", "user.name")
    git_email = git(diary_root, "config", "user.email")
    repo_url  = git(diary_root, "config", "--get", "remote.origin.url")
    branch    = git(diary_root, "rev-parse", "--abbrev-ref", "HEAD")

    issue_ref = None
    issue_cfg = config.get("issue_detection") or {}
    branch_pat = issue_cfg.get("branch_pattern")
    if branch and branch_pat:
        m = re.search(branch_pat, branch)
        if m:
            issue_ref = f"#{m.group(1)}"

    # ---- languages --------------------------------------------------------
    languages = sorted({
        EXT_LANG[Path(e["file"]).suffix.lower()]
        for e in events
        if e.get("file") and Path(e["file"]).suffix.lower() in EXT_LANG
    })

    # ---- model from transcript -------------------------------------------
    model = resolve_model(meta_file)

    # ---- destination ------------------------------------------------------
    now = datetime.now()
    folder = diary_root / "entries" / f"{now:%Y}" / f"{now:%m}" / f"{now:%Y-%m-%d}"
    folder.mkdir(parents=True, exist_ok=True)
    session_tag = f"session-{next_session_num(folder):03d}"
    yaml_path = folder / f"{session_tag}.yaml"
    md_path   = folder / f"{session_tag}.md"

    # ---- summary fields ---------------------------------------------------
    started_at = events[0]["timestamp"]
    ended_at   = events[-1]["timestamp"]
    prompt = next((e["summary"] for e in events if e["type"] == "prompt"), None)
    files_touched = sorted({e["file"] for e in events if e.get("file")})

    # ---- emit -------------------------------------------------------------
    emit_yaml(
        yaml_path,
        session_id=session_id, model=model,
        git_name=git_name, git_email=git_email,
        repo_url=repo_url, branch=branch, issue_ref=issue_ref,
        languages=languages, started_at=started_at, ended_at=ended_at,
        events=events, prompt=prompt, files_touched=files_touched,
    )
    emit_md(
        md_path,
        date=now.strftime("%Y-%m-%d"), session_tag=session_tag,
        git_name=git_name, git_email=git_email,
        repo_url=repo_url, branch=branch, issue_ref=issue_ref,
        started_at=started_at, ended_at=ended_at,
        prompt=prompt, events=events, files_touched=files_touched,
    )

    # ---- commit + push ----------------------------------------------------
    push_cfg = config.get("push") or {}
    # Canonical key is `when`. Tolerate the legacy `on:` key, which YAML 1.1
    # (PyYAML) parses as the boolean True — so check both the string and True.
    push_on = push_cfg.get("when") or push_cfg.get("on") or push_cfg.get(True)
    if push_on in ("session_end", "every_n_minutes"):
        short = session_id[:8]
        msg = f"dev-diary: claude-code {short} on {branch} ({session_tag})"
        rel_yaml = str(yaml_path.relative_to(diary_root))
        rel_md = str(md_path.relative_to(diary_root))

        # Diary commits are auto-generated metadata. GPG signing adds no value
        # here and breaks inside the hook's non-interactive context (no pinentry
        # / GPG agent), so disable it unless the user opts back in.
        commit_cmd = ["git"]
        if not push_cfg.get("sign_commits", False):
            commit_cmd += ["-c", "commit.gpgsign=false"]
        commit_cmd += ["commit", "-m", msg, "--quiet"]

        def run(cmd):
            return subprocess.run(cmd, cwd=diary_root, capture_output=True, text=True)

        add_res = run(["git", "add", rel_yaml, rel_md])
        if add_res.returncode != 0:
            log_flush_error(diary_root, "git add", add_res)
        else:
            commit_res = run(commit_cmd)
            if commit_res.returncode != 0:
                log_flush_error(diary_root, "git commit", commit_res)
            elif push_on == "session_end":
                remote = push_cfg.get("remote", "origin")
                target_branch = push_cfg.get("branch", "main")
                push_res = run(["git", "push", remote, target_branch, "--quiet"])
                if push_res.returncode != 0:
                    log_flush_error(diary_root, "git push", push_res)

    # ---- cleanup ----------------------------------------------------------
    buffer_file.unlink(missing_ok=True)
    meta_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
