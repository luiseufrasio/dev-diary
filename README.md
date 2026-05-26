# dev-diary

A Claude Code plugin (and soon Cursor/Gemini/Codex adapters) that captures a persistent, queryable diary of what AI agents actually did in your repos.

Every Claude Code session becomes two files in **your diary repo**:

- **`session-NNN.md`** — human-readable step-by-step
- **`session-NNN.yaml`** — structured events (tool calls, files, timestamps, actor, language, issue ref) for querying

A local CLI builds a SQLite index from the YAML files so you can ask:

```bash
/dev-diary-query --agent claude-code --language python --since 2026-05-01
/dev-diary-query --issue 123
/dev-diary-query --user dev@example.com --project web-app
/dev-diary-show   2026/05/2026-05-23/session-001
```

## Two repos, one workflow

dev-diary deliberately splits into two pieces:

| Repo | What lives here | Where it goes |
|---|---|---|
| **dev-diary plugin** (this repo) | hooks, slash commands, schema, CLI, default config | installed via `/plugin install` — lives under `~/.claude/plugins/` |
| **your diary repo** (per dev, you create/fork) | `entries/`, your `dev-diary.config.yaml`, your commits | wherever you clone it — pushed to your GitHub |

A tiny `~/.dev-diary/state.json` (written by `/enable-dev-diary`) points the plugin at your diary repo.

## Install

```
/plugin marketplace add luiseufrasio/dev-diary
/plugin install dev-diary@dev-diary
/enable-dev-diary
```

`/enable-dev-diary` walks you through:
1. Where your diary repo lives (or fork this repo as your starting point)
2. Writing `~/.dev-diary/state.json`
3. Copying `config.example.yaml` → `<diary>/dev-diary.config.yaml` for you to tune redaction / push policy

The plugin's `hooks/hooks.json` wires `UserPromptSubmit` / `PostToolUse` / `Stop` automatically — no `~/.claude/settings.json` edits required.

## Plugin layout

```
.claude-plugin/
  marketplace.json         # marketplace catalog — makes the repo installable
  plugin.json              # plugin manifest (name, version, author)
commands/
  enable-dev-diary.md      # /enable-dev-diary  — setup
  dev-diary-query.md       # /dev-diary-query   — CLI wrapper
  dev-diary-show.md        # /dev-diary-show    — render one entry
hooks/
  hooks.json               # declares the three hooks
  post_tool.py             # UserPromptSubmit + PostToolUse — append to buffer
  flush.py                 # Stop — buffer → yaml+md → git commit
schema/
  entry.schema.yaml        # canonical schema for *.yaml entries
cli/
  dev-diary.py             # query CLI (indexes YAML into SQLite)
config.example.yaml        # template config — copied to user's diary on /enable-dev-diary
```

## Diary repo layout (after /enable-dev-diary)

```
<diary_root>/
  dev-diary.config.yaml    # your copy, edited for your redaction/push preferences
  entries/YYYY/MM/YYYY-MM-DD/
    session-NNN.md
    session-NNN.yaml
  .dev-diary-buffer/       # transient JSONL while a session is open (gitignored)
  .dev-diary/index.sqlite  # local CLI index (gitignored)
```

## How capture works

1. `UserPromptSubmit` → records your prompt as a `prompt` event.
2. `PostToolUse` → records each tool call (`Edit`/`Write` → `file_edit`, `Bash` → `command`, otherwise `tool_use`).
3. `Stop` → flush: redact, derive git context (user/repo/branch, issue ref from branch), detect languages, write `session-NNN.{yaml,md}`, commit, push.

Hooking per-event but committing per-session keeps GitHub noise low and avoids leaking partial state.

## Platform support

Cross-platform — hooks and CLI are pure Python.

- **Requirement:** Python 3.9+ in `PATH` as `python`, plus `pip install pyyaml`.
- On Linux distros where only `python3` is on `PATH`, install the `python-is-python3` package (Debian/Ubuntu) or alias `python` to `python3`. (If preferred, edit `hooks/hooks.json` to replace `python` with `python3` — the manifest is the only place it appears.)

## Status

Sketch / proposal. Claude Code is the first target (native plugin format). Cursor/Gemini/Codex adapters come next, writing into the same `entries/` schema so one CLI queries them all.
