#!/usr/bin/env python3
"""dev-diary — query CLI over local entries/*.yaml.

Builds a SQLite index on first run (or with `dev-diary reindex`) so queries are
fast and offline. Index lives at .dev-diary/index.sqlite — gitignored.

    dev-diary query --agent claude-code --language python --since 2026-05-01
    dev-diary query --issue 123
    dev-diary query --user dev@example.com --project web-app
    dev-diary show 2026/05/23/b1a01ad7
    dev-diary reindex
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import yaml  # PyYAML

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
  outcome     TEXT
);
CREATE TABLE IF NOT EXISTS session_languages (
  session_id TEXT, language TEXT,
  PRIMARY KEY (session_id, language)
);
CREATE TABLE IF NOT EXISTS session_files (
  session_id TEXT, file TEXT,
  PRIMARY KEY (session_id, file)
);
CREATE INDEX IF NOT EXISTS idx_started ON sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_agent   ON sessions(agent_name);
CREATE INDEX IF NOT EXISTS idx_issue   ON sessions(issue_ref);
CREATE INDEX IF NOT EXISTS idx_email   ON sessions(git_email);
"""


def reindex() -> int:
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    if INDEX.exists():
        INDEX.unlink()
    con = sqlite3.connect(INDEX)
    con.executescript(SCHEMA)

    count = 0
    for yml in ENTRIES.rglob("*.yaml"):
        data = yaml.safe_load(yml.read_text(encoding="utf-8"))
        con.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                (data.get("summary") or {}).get("prompt"),
                (data.get("summary") or {}).get("outcome"),
            ),
        )
        for lang in data.get("languages") or []:
            con.execute(
                "INSERT OR IGNORE INTO session_languages VALUES (?,?)",
                (data["session_id"], lang),
            )
        # files_changed lives in summary (new schema); fall back to files_touched (old)
        summary = data.get("summary") or {}
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


def show(args: argparse.Namespace) -> None:
    md = ENTRIES / f"{args.ref}.md"
    if not md.exists():
        print(f"not found: {md.relative_to(ROOT)}")
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
    q.add_argument("-v", "--verbose", action="store_true")
    q.set_defaults(func=query)

    s = sub.add_parser("show")
    s.add_argument("ref", help="e.g. 2026/05/23/b1a01ad7")
    s.set_defaults(func=show)

    sub.add_parser("reindex").set_defaults(func=lambda _a: reindex())

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
