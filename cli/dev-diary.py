#!/usr/bin/env python3
"""dev-diary — query CLI over local entries/*.yaml.

Builds a SQLite index on first run (or with `dev-diary reindex`) so queries are
fast and offline. Index lives at .dev-diary/index.sqlite — gitignored.

    dev-diary query --agent claude-code --language python --since 2026-05-01
    dev-diary query --issue 123
    dev-diary query --user dev@example.com --project web-app
    dev-diary list                    # today's sessions
    dev-diary list 2026-05-23         # sessions on a specific date
    dev-diary show 2026/05/2026-05-23/session-001
    dev-diary replay a743e5c5         # open session as slides in browser
    dev-diary reindex
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sqlite3
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import yaml  # PyYAML

# diary_root: state.json wins (separate diary repo); fall back to plugin repo layout
_state_file = Path.home() / ".dev-diary" / "state.json"
if _state_file.exists():
    ROOT = Path(json.loads(_state_file.read_text(encoding="utf-8"))["diary_root"])
else:
    ROOT = Path(__file__).resolve().parent.parent

ENTRIES = ROOT / "entries"
INDEX = ROOT / ".dev-diary" / "index.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  session_id  TEXT PRIMARY KEY,
  path        TEXT NOT NULL,
  agent_name  TEXT,
  agent_model TEXT,
  git_email   TEXT,
  git_name    TEXT,
  repo        TEXT,
  branch      TEXT,
  issue_ref   TEXT,
  started_at  TEXT,
  ended_at    TEXT,
  prompt      TEXT,
  outcome     TEXT,
  category    TEXT
);
CREATE TABLE IF NOT EXISTS session_languages (
  session_id TEXT, language TEXT,
  PRIMARY KEY (session_id, language)
);
CREATE TABLE IF NOT EXISTS session_files (
  session_id TEXT, file TEXT,
  PRIMARY KEY (session_id, file)
);
CREATE INDEX IF NOT EXISTS idx_started  ON sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_agent    ON sessions(agent_name);
CREATE INDEX IF NOT EXISTS idx_issue    ON sessions(issue_ref);
CREATE INDEX IF NOT EXISTS idx_email    ON sessions(git_email);
CREATE INDEX IF NOT EXISTS idx_category ON sessions(category);
"""

_CATEGORY_RULES: list[tuple[str, tuple, tuple]] = [
    ("test",
     ("test_", "_test.", ".spec.", ".test.", "/tests/", "/test/"),
     ("test", "spec", "tdd", "coverage", "unittest", "pytest", "jest", "assert")),
    ("fix",
     (),
     ("fix", "bug", "erro", "error", "crash", "except", "corrig", "falha",
      "broken", "failing", "resolve", "conserta")),
    ("docs",
     (".md", ".rst", "readme", "changelog", "/docs/", "/doc/"),
     ("doc", "readme", "comment", "document", "explain", "changelog",
      "comentar", "documentar")),
    ("refactor",
     (),
     ("refactor", "refatorar", "clean", "simplif", "extract", "rename", "reorgan",
      "restructure", "rewrite", "limpar", "reorganizar", "reestruturar", "otimiz")),
    ("feature",
     (),
     ("add ", "implement", "create", "new feature", "build",
      "adicionar", "implementar", "criar", "feature")),
    ("chore",
     (),
     ("upgrade", "bump", "setup", "install", "migrat",
      "atualizar", "configurar", "update dep")),
]


def classify_session(prompts_text: str, files: list) -> str:
    text = prompts_text.lower()
    file_str = " ".join(f.lower() for f in files)
    for category, file_pats, kws in _CATEGORY_RULES:
        if any(p in file_str for p in file_pats) or any(kw in text for kw in kws):
            return category
    return "unknown"


def reindex() -> int:
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    if INDEX.exists():
        INDEX.unlink()
    con = sqlite3.connect(INDEX)
    con.executescript(SCHEMA)

    count = 0
    for yml in ENTRIES.rglob("*.yaml"):
        data = yaml.safe_load(yml.read_text(encoding="utf-8"))
        summary = data.get("summary") or {}
        category = summary.get("category")
        if not category:
            turns = data.get("turns") or []
            all_prompts = " ".join((t.get("prompt") or "") for t in turns)
            files = summary.get("files_changed") or summary.get("files_touched") or []
            category = classify_session(all_prompts, files)

        con.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data["session_id"],
                str(yml.relative_to(ROOT)),
                data.get("agent", {}).get("name"),
                data.get("agent", {}).get("model"),
                data.get("user", {}).get("git_email"),
                data.get("user", {}).get("git_name"),
                data.get("project", {}).get("repo"),
                data.get("project", {}).get("branch"),
                (data.get("issue") or {}).get("ref"),
                data.get("started_at"),
                data.get("ended_at"),
                next((t.get("prompt") for t in (data.get("turns") or []) if t.get("prompt")), None)
                or summary.get("prompt"),
                summary.get("outcome"),
                category,
            ),
        )
        for lang in data.get("languages") or []:
            con.execute(
                "INSERT OR IGNORE INTO session_languages VALUES (?,?)",
                (data["session_id"], lang),
            )
        # files_changed lives in summary (new schema); fall back to files_touched (old)
        for f in summary.get("files_changed") or summary.get("files_touched") or []:
            con.execute(
                "INSERT OR IGNORE INTO session_files VALUES (?,?)",
                (data["session_id"], f),
            )
        count += 1

    con.commit()
    con.close()
    print(f"indexed {count} session(s) -> {INDEX.relative_to(ROOT)}")
    return count


def query(args: argparse.Namespace) -> None:
    if not INDEX.exists():
        reindex()
    con = sqlite3.connect(INDEX)
    con.row_factory = sqlite3.Row

    where, params = [], []
    if args.agent:    where.append("agent_name = ?");                 params.append(args.agent)
    if args.issue:    where.append("issue_ref LIKE ?");               params.append(f"%{args.issue}%")
    if args.user:     where.append("git_email = ?");                  params.append(args.user)
    if args.project:  where.append("repo LIKE ?");                    params.append(f"%{args.project}%")
    if args.since:    where.append("started_at >= ?");                params.append(args.since)
    if args.until:    where.append("started_at <= ?");                params.append(args.until)
    if args.language:
        where.append("session_id IN (SELECT session_id FROM session_languages WHERE language = ?)")
        params.append(args.language)
    if args.file:
        where.append("session_id IN (SELECT session_id FROM session_files WHERE file LIKE ?)")
        params.append(f"%{args.file}%")
    if args.category:
        where.append("category = ?")
        params.append(args.category)

    sql = "SELECT * FROM sessions"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY started_at DESC"

    rows = con.execute(sql, params).fetchall()
    if not rows:
        print("(no sessions match)")
        return
    for r in rows:
        print(f"{r['started_at']}  {r['agent_name']:<12}  {r['git_email']:<35}  "
              f"{(r['issue_ref'] or '-'):<8}  {r['path']}")
        if args.verbose and r["prompt"]:
            print(f"    > {r['prompt']}")


def list_sessions(args: argparse.Namespace) -> None:
    if not INDEX.exists():
        reindex()
    con = sqlite3.connect(INDEX)
    con.row_factory = sqlite3.Row

    date = args.date or datetime.date.today().isoformat()
    try:
        d = datetime.date.fromisoformat(date)
    except ValueError:
        print(f"error: invalid date '{date}', expected YYYY-MM-DD")
        return

    # Filter by path date (directory structure), not started_at, to avoid
    # timezone skew between when a session starts and when flush writes the file.
    path_prefix = f"entries/{d.year}/{d.month:02d}/{d.day:02d}/"
    rows = con.execute(
        "SELECT path, started_at, prompt FROM sessions"
        " WHERE REPLACE(path, '\\', '/') LIKE ? ORDER BY started_at",
        (path_prefix + "%",),
    ).fetchall()

    if not rows:
        print(f"(no sessions on {date})")
        return

    for r in rows:
        hash_ = r["path"].replace("\\", "/").split("/")[-1].removesuffix(".yaml")
        time_ = (r["started_at"] or "")[:16]
        print(f"- {hash_}  {time_}")
        if r["prompt"]:
            prompt = r["prompt"]
            if len(prompt) > 80:
                prompt = prompt[:77] + "..."
            print(f"    {prompt}")


def _parse_turn_responses(md_text: str) -> dict:
    """Extract Claude's blockquote responses per turn-id from the markdown."""
    out: dict[str, str] = {}
    cur_id: str | None = None
    buf: list[str] = []
    for line in md_text.splitlines():
        m = re.match(r"^## (turn-\d+)", line)
        if m:
            if cur_id is not None:
                out[cur_id] = "\n".join(buf).strip()
            cur_id = m.group(1)
            buf = []
        elif cur_id is not None:
            if line.startswith("> "):
                buf.append(line[2:])
            elif line == ">":
                buf.append("")
    if cur_id is not None:
        out[cur_id] = "\n".join(buf).strip()
    return out


def _action_html(action: dict) -> str:
    import html as _h
    atype = action.get("type", "")
    tool  = action.get("tool", "")
    icons = {"Read": "📄", "Edit": "✏️", "Write": "📝", "Grep": "🔍",
             "Glob": "🗂️", "WebFetch": "🌐", "Agent": "🤖",
             "Bash": "💻", "command": "💻"}
    icon = icons.get(tool) or icons.get(atype, "⚙️")
    css  = {"Read":"read","Edit":"edit","Write":"write","Grep":"grep",
            "command":"bash","Bash":"bash"}.get(tool or atype, "other")

    h = f'<div class="action action-{css}">'
    h += f'<span class="aicon">{icon}</span>'
    if tool:
        h += f'<span class="atool">{_h.escape(tool)}</span>'

    if atype == "file_edit":
        fname = Path(action.get("file", "")).name
        fpath = _h.escape(action.get("file", ""))
        h += f'<span class="afile" title="{fpath}">{_h.escape(fname)}</span>'
        diff = action.get("diff", "")
        if diff:
            h += (f'<details class="diff-wrap">'
                  f'<summary>diff</summary>'
                  f'<pre><code class="language-diff">{_h.escape(diff)}</code></pre>'
                  f'</details>')

    elif atype == "command":
        cmd = action.get("cmd", "")
        out = action.get("output", "")
        if cmd:
            h += f'<pre class="cmd-block"><code class="language-bash">{_h.escape(cmd)}</code></pre>'
        if out:
            preview = out.strip()[:600] + ("…" if len(out.strip()) > 600 else "")
            h += (f'<details class="out-wrap">'
                  f'<summary>output</summary>'
                  f'<pre class="out-block">{_h.escape(preview)}</pre>'
                  f'</details>')

    else:
        summary = action.get("summary", "")
        if summary:
            h += f'<span class="asum">{_h.escape(summary)}</span>'

    h += '</div>'
    return h


def _response_subtitle(response: str) -> str:
    """One-line headline for the slide: first heading, else first non-empty line."""
    if not response:
        return ""
    for line in response.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^#{1,4}\s+(.+?)\s*#*\s*$", line)
        if m:
            return m.group(1).strip()
        # Strip inline emphasis/code so the headline reads clean
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        return (text[:140].rstrip() + "…") if len(text) > 140 else text
    return ""


def _build_replay_html(data: dict, turns: list, responses: dict) -> str:
    import html as _h

    sid      = (data.get("session_id") or "")[:8]
    model    = (data.get("agent") or {}).get("model", "")
    repo_url = (data.get("project") or {}).get("repo", "")
    branch   = (data.get("project") or {}).get("branch", "")
    repo     = repo_url.split("/")[-1] if repo_url else ""
    started  = str(data.get("started_at") or "")[:16].replace("T", " ")
    ended    = str(data.get("ended_at") or "")[:16].replace("T", " ")
    files    = (data.get("summary") or {}).get("files_changed") or []

    def slide(body: str, idx: int) -> str:
        cls = "slide active" if idx == 0 else "slide"
        return f'<div class="{cls}" id="s{idx}">{body}</div>'

    slides: list[str] = []

    # ── Slide 0: overview ──────────────────────────────────────────────────
    fl = "".join(
        f'<li><code>{_h.escape(Path(f).name)}</code>'
        f'<span class="fpath">{_h.escape(f)}</span></li>'
        for f in files
    )
    ov  = f'<div class="badge">Overview</div>'
    ov += f'<h1>Session <code>{_h.escape(sid)}</code></h1>'
    ov += '<div class="meta">'
    for label, val in [("model", model), ("repo", repo), ("branch", branch),
                        ("started", started), ("ended", ended),
                        ("turns", str(len(turns)))]:
        ov += (f'<div class="mc"><span class="ml">{label}</span>'
               f'<span class="mv">{_h.escape(val)}</span></div>')
    ov += '</div>'
    if fl:
        ov += f'<h3 class="sec-title">Files changed</h3><ul class="flist">{fl}</ul>'
    slides.append(slide(ov, 0))

    # ── One slide per turn ─────────────────────────────────────────────────
    # Index 0 has no response (overview slide); turn responses sit at i=1..N.
    response_texts: list[str] = [""]

    for i, turn in enumerate(turns, 1):
        tid      = turn.get("id", f"turn-{i}")
        prompt   = turn.get("prompt", "")
        actions  = turn.get("actions") or []
        response = responses.get(tid, "")
        subtitle = _response_subtitle(response)
        response_texts.append(response)

        body  = f'<div class="badge">Turn {i} / {len(turns)}</div>'
        if subtitle:
            body += f'<h2 class="tldr">{_h.escape(subtitle)}</h2>'

        if response:
            # marked.js renders this client-side from RESPONSES[{i}]
            body += (f'<section class="resp-sec">'
                     f'<h3 class="sec-title">What was done</h3>'
                     f'<div class="resp" id="resp-{i}"></div>'
                     f'</section>')

        body += '<section class="ctx-sec">'
        body += (f'<h3 class="sec-title">Prompt</h3>'
                 f'<div class="prompt">'
                 f'<span class="picon">💬</span>'
                 f'<span class="ptxt">{_h.escape(prompt)}</span>'
                 f'</div>')
        if actions:
            act_html = "\n".join(_action_html(a) for a in actions)
            body += f'<h3 class="sec-title act-title">Actions</h3>{act_html}'
        body += '</section>'

        slides.append(slide(body, i))

    total = len(slides)
    slides_html = "\n".join(slides)
    # Replace `</` so an embedded `</script>` can't close the host <script> tag.
    responses_json = json.dumps(response_texts).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>replay · {_h.escape(sid)}</title>
<link rel="stylesheet"
  href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked@12.0.0/marked.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:#0d1117;color:#e6edf3;height:100vh;display:flex;flex-direction:column}}
a{{color:#58a6ff}}
code{{font-family:'Cascadia Code','Consolas','Fira Code',monospace}}

/* ── layout ── */
.deck{{flex:1;overflow-y:auto;padding:2rem 2.5rem;max-width:860px;
  margin:0 auto;width:100%}}
.slide{{display:none;animation:fadein .2s ease}}
.slide.active{{display:block}}
@keyframes fadein{{from{{opacity:0;transform:translateY(6px)}}to{{opacity:1;transform:none}}}}

/* ── badge ── */
.badge{{display:inline-block;background:#238636;color:#fff;padding:.2rem .7rem;
  border-radius:12px;font-size:.72rem;font-weight:700;letter-spacing:.06em;
  text-transform:uppercase;margin-bottom:1.4rem}}

/* ── overview ── */
h1{{font-size:1.9rem;color:#79c0ff;margin-bottom:1.4rem;font-weight:600}}
h1 code{{font-size:1.7rem;color:#79c0ff}}
.meta{{display:grid;grid-template-columns:repeat(3,1fr);gap:.75rem;margin-bottom:1.8rem}}
.mc{{background:#161b22;border:1px solid #30363d;border-radius:8px;
  padding:.65rem 1rem}}
.ml{{display:block;font-size:.7rem;color:#8b949e;text-transform:uppercase;
  letter-spacing:.05em;margin-bottom:.2rem}}
.mv{{color:#e6edf3;font-weight:500;font-size:.9rem;word-break:break-all}}
.flist{{list-style:none;padding:0}}
.flist li{{display:flex;gap:.6rem;align-items:baseline;
  padding:.35rem 0;border-bottom:1px solid #21262d;font-size:.85rem}}
.flist code{{color:#ffa657}}
.fpath{{color:#8b949e;font-size:.75rem}}

/* ── turn slide ── */
.tldr{{font-size:1.55rem;color:#79c0ff;font-weight:600;line-height:1.35;
  margin-bottom:1.4rem}}
.prompt{{display:flex;gap:.9rem;align-items:flex-start;
  background:#161b22;border-left:4px solid #388bfd;
  border-radius:0 8px 8px 0;padding:1.1rem 1.3rem;margin-bottom:1rem}}
.picon{{font-size:1.2rem;flex-shrink:0;margin-top:.1rem}}
.ptxt{{font-size:1.05rem;line-height:1.6;color:#e6edf3}}
.sec-title{{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;
  color:#8b949e;margin-bottom:.6rem;padding-bottom:.4rem;
  border-bottom:1px solid #21262d}}
.act-title{{margin-top:1.2rem}}
section{{margin-bottom:1.4rem}}
.ctx-sec{{margin-top:1.8rem;padding-top:1.4rem;border-top:1px dashed #30363d}}
.ctx-sec .prompt{{background:#0d1117;border-left:3px solid #388bfd;
  padding:.7rem 1rem;margin-bottom:0}}
.ctx-sec .ptxt{{font-size:.92rem;color:#c9d1d9}}

/* ── actions ── */
.action{{display:flex;flex-wrap:wrap;align-items:flex-start;gap:.4rem;
  background:#161b22;border:1px solid #30363d;border-radius:6px;
  padding:.55rem .7rem;margin-bottom:.4rem}}
.aicon{{font-size:.95rem;flex-shrink:0}}
.atool{{font-size:.75rem;font-weight:700;padding:.1rem .4rem;
  border-radius:4px;background:#21262d;color:#79c0ff;flex-shrink:0}}
.action-edit .atool{{color:#ffa657;background:#1f1b14}}
.action-bash .atool{{color:#3fb950;background:#122117}}
.action-grep .atool{{color:#d2a8ff;background:#1e1630}}
.afile{{font-size:.8rem;color:#8b949e;font-family:monospace}}
.asum{{font-size:.82rem;color:#8b949e;flex:1}}

/* ── command blocks ── */
.cmd-block{{width:100%;margin-top:.4rem;border-radius:6px;font-size:.82rem;overflow-x:auto}}
.cmd-block code{{padding:.65rem 1rem!important}}
.out-wrap,.diff-wrap{{width:100%;margin-top:.35rem;font-size:.8rem}}
.out-wrap summary,.diff-wrap summary{{color:#8b949e;cursor:pointer;
  padding:.2rem .4rem;border-radius:4px;user-select:none}}
.out-wrap summary:hover,.diff-wrap summary:hover{{color:#c9d1d9}}
.out-block{{background:#0d1117;border:1px solid #30363d;border-radius:6px;
  padding:.65rem 1rem;font-family:monospace;font-size:.78rem;
  white-space:pre-wrap;word-break:break-all;color:#8b949e;margin-top:.3rem;
  max-height:280px;overflow-y:auto}}
.diff-wrap pre{{margin-top:.3rem;border-radius:6px;font-size:.78rem;max-height:300px;overflow-y:auto}}

/* ── response ── */
.resp-sec .sec-title{{color:#3fb950}}
.resp{{color:#c9d1d9;line-height:1.7;font-size:.93rem}}
.resp > :first-child{{margin-top:0}}
.resp > :last-child{{margin-bottom:0}}
.resp p{{margin:0 0 .7rem}}
.resp strong{{color:#e6edf3}}
.resp em{{color:#e6edf3}}
.resp h1,.resp h2{{font-size:1.1rem;color:#e6edf3;margin:1.3rem 0 .55rem;
  font-weight:600;padding-bottom:.3rem;border-bottom:1px solid #21262d}}
.resp h3,.resp h4{{font-size:.95rem;color:#e6edf3;margin:1.1rem 0 .45rem;font-weight:600}}
.resp ul,.resp ol{{margin:.3rem 0 .8rem 1.5rem;padding:0}}
.resp li{{margin-bottom:.25rem}}
.resp li > p{{margin:0}}
.resp blockquote{{border-left:3px solid #30363d;padding:.15rem .9rem;
  color:#8b949e;margin:.7rem 0}}
.resp blockquote p{{margin:.3rem 0}}
.resp code{{background:#21262d;padding:.1rem .35rem;border-radius:4px;
  font-size:.85em;color:#ffa657}}
.resp pre{{background:#0d1117;border:1px solid #30363d;border-radius:6px;
  margin:.7rem 0;padding:0;overflow-x:auto}}
.resp pre code{{background:transparent;padding:.7rem 1rem;display:block;
  font-size:.82rem;color:#e6edf3}}
.resp table{{border-collapse:collapse;margin:.7rem 0;font-size:.86rem;
  display:block;overflow-x:auto}}
.resp th,.resp td{{border:1px solid #30363d;padding:.4rem .7rem;text-align:left}}
.resp th{{background:#161b22;font-weight:600;color:#e6edf3}}
.resp hr{{border:0;border-top:1px solid #30363d;margin:1.2rem 0}}
.resp a{{text-decoration:underline}}

/* ── nav bar ── */
.nav{{display:flex;align-items:center;justify-content:space-between;
  padding:.85rem 2.5rem;background:#161b22;border-top:1px solid #30363d;
  max-width:860px;margin:0 auto;width:100%}}
button{{background:#21262d;color:#e6edf3;border:1px solid #30363d;
  padding:.4rem 1.1rem;border-radius:6px;cursor:pointer;font-size:.88rem;
  transition:background .12s}}
button:hover:not(:disabled){{background:#30363d}}
button:disabled{{opacity:.35;cursor:not-allowed}}
#ctr{{color:#8b949e;font-size:.85rem;font-variant-numeric:tabular-nums}}
</style>
</head>
<body>
<div class="deck">
{slides_html}
</div>
<div class="nav">
  <button id="bk" onclick="go(-1)" disabled>← Back</button>
  <span id="ctr">1 / {total}</span>
  <button id="nx" onclick="go(1)">Next →</button>
</div>
<script>
const RESPONSES={responses_json};
marked.setOptions({{gfm:true,breaks:false}});
RESPONSES.forEach((md,i)=>{{
  const el=document.getElementById('resp-'+i);
  if(el&&md)el.innerHTML=marked.parse(md);
}});
let c=0;
const S=document.querySelectorAll('.slide'),T={total};
function go(d){{
  S[c].classList.remove('active');
  c=Math.max(0,Math.min(T-1,c+d));
  S[c].classList.add('active');
  document.getElementById('ctr').textContent=(c+1)+' / '+T;
  document.getElementById('bk').disabled=c===0;
  document.getElementById('nx').disabled=c===T-1;
  document.querySelectorAll('pre code').forEach(el=>{{
    if(!el.dataset.highlighted)hljs.highlightElement(el);
  }});
}}
document.addEventListener('keydown',e=>{{
  if(e.key==='ArrowRight'||e.key==='ArrowDown')go(1);
  if(e.key==='ArrowLeft'||e.key==='ArrowUp')go(-1);
}});
document.querySelectorAll('pre code').forEach(el=>hljs.highlightElement(el));
</script>
</body>
</html>"""


def replay(args: argparse.Namespace) -> None:
    import tempfile
    import webbrowser

    ref = args.ref
    if "/" in ref or "\\" in ref:
        yaml_path = ENTRIES / f"{ref}.yaml"
        md_path   = ENTRIES / f"{ref}.md"
    else:
        matches = list(ENTRIES.rglob(f"{ref}.yaml"))
        if not matches:
            print(f"not found: {ref}")
            return
        yaml_path = matches[0]
        md_path   = yaml_path.with_suffix(".md")

    data      = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    md_text   = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    turns     = data.get("turns") or []
    responses = _parse_turn_responses(md_text)

    html = _build_replay_html(data, turns, responses)
    tmp  = Path(tempfile.mktemp(suffix=".html"))
    tmp.write_text(html, encoding="utf-8")
    webbrowser.open(tmp.as_uri())
    print(f"replay: {len(turns)} turn(s) → {tmp.name}")


def show(args: argparse.Namespace) -> None:
    ref = args.ref
    if "/" in ref or "\\" in ref:
        md = ENTRIES / f"{ref}.md"
    else:
        matches = list(ENTRIES.rglob(f"{ref}.md"))
        if not matches:
            print(f"not found: {ref}")
            return
        md = matches[0]
    if not md.exists():
        print(f"not found: {ref}")
        return
    print(md.read_text(encoding="utf-8"))


def main() -> None:
    p = argparse.ArgumentParser(prog="dev-diary")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("query")
    q.add_argument("--agent")
    q.add_argument("--issue")
    q.add_argument("--user")
    q.add_argument("--project")
    q.add_argument("--language")
    q.add_argument("--file", help="filter by file path substring")
    q.add_argument("--since")
    q.add_argument("--until")
    q.add_argument("--category", help="filter by category (fix, feature, docs, test, refactor, chore, unknown)")
    q.add_argument("-v", "--verbose", action="store_true")
    q.set_defaults(func=query)

    ls = sub.add_parser("list")
    ls.add_argument("date", nargs="?", help="YYYY-MM-DD (default: today)")
    ls.set_defaults(func=list_sessions)

    s = sub.add_parser("show")
    s.add_argument("ref", help="e.g. 2026/05/23/b1a01ad7")
    s.set_defaults(func=show)

    rp = sub.add_parser("replay", help="open session as slides in browser")
    rp.add_argument("ref", help="session hash or full ref")
    rp.set_defaults(func=replay)

    sub.add_parser("reindex").set_defaults(func=lambda _a: reindex())

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
