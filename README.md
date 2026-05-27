# dev-diary

A Claude Code plugin (and soon Cursor/Gemini/Codex adapters) that captures a persistent, queryable diary of what AI agents actually did in your repos.

Every Claude Code session becomes two files in **your diary repo**:

- **`session-NNN.md`** — human-readable step-by-step
- **`session-NNN.yaml`** — structured events (tool calls, files, timestamps, actor, language, issue ref) for querying

A local CLI builds a SQLite index from the YAML files so you can ask:

```bash
/dev-diary:query --agent claude-code --language python --since 2026-05-01
/dev-diary:query --issue 123
/dev-diary:query --user dev@example.com --project web-app
/dev-diary:show   2026/05/23/b1a01ad7
```

## Two repos, one workflow

dev-diary deliberately splits into two pieces:

| Repo | What lives here | Where it goes |
|---|---|---|
| **dev-diary plugin** (this repo) | hooks, slash commands, schema, CLI, default config | installed via `/plugin install` — lives under `~/.claude/plugins/` |
| **your diary repo** (per dev, you create/fork) | `entries/`, your `dev-diary.config.yaml`, your commits | wherever you clone it — pushed to your GitHub |

A tiny `~/.dev-diary/state.json` (written by `/dev-diary:enable`) points the plugin at your diary repo.

## Install

```
/plugin marketplace add luiseufrasio/dev-diary
/plugin install dev-diary@dev-diary
/dev-diary:enable
```

> **`/dev-diary:enable` is required before anything is captured.**
> The hooks are wired as soon as the plugin loads, but they silently no-op until
> you run enable. The enable command writes `~/.dev-diary/state.json` — the
> single file that tells the hooks which diary repo to write to. Without it,
> events are recorded and immediately discarded at session end.

`/dev-diary:enable` walks you through:
1. The URL of your (private) diary repo, and cloning it / wiring `origin` on a local working copy so sessions auto-push
2. Running `hooks/setup.py --diary-root <path>` which writes `~/.dev-diary/state.json` and copies `config.example.yaml` → `<diary>/dev-diary.config.yaml` in one step
3. Opening `dev-diary.config.yaml` so you can tune redaction patterns and the push policy before your first session
4. Seeding the first `git push` so the Stop hook's silent push works later

The plugin's `hooks/hooks.json` wires `UserPromptSubmit` / `PostToolUse` / `Stop` automatically — no `~/.claude/settings.json` edits required.

## Plugin layout

```
.claude-plugin/
  marketplace.json         # marketplace catalog — makes the repo installable
  plugin.json              # plugin manifest (name, version, author)
commands/
  enable.md                # /dev-diary:enable      — setup
  query.md                 # /dev-diary:query       — CLI wrapper
  show.md                  # /dev-diary:show        — render one entry
  ignore-git.md            # /dev-diary:ignore-git  — toggle git/gh capture
hooks/
  hooks.json               # declares the three hooks
  post_tool.py             # UserPromptSubmit + PostToolUse — append to buffer
  flush.py                 # Stop — buffer → yaml+md → git commit
  setup.py                 # /dev-diary:enable — write state.json + seed config
schema/
  entry.schema.yaml        # canonical schema for *.yaml entries
cli/
  dev-diary.py             # query CLI (indexes YAML into SQLite)
config.example.yaml        # template config — copied to user's diary on /dev-diary:enable
```

## Diary repo layout (after /dev-diary:enable)

```
<diary_root>/
  dev-diary.config.yaml    # your copy, edited for your redaction/push preferences
  entries/YYYY/MM/DD/
    <session_id[:8]>.md    # e.g. b1a01ad7.md
    <session_id[:8]>.yaml  # full session_id in the file header
  .dev-diary-buffer/       # transient JSONL while a session is open (gitignored)
  .dev-diary/index.sqlite  # local CLI index (gitignored)
```

## How capture works

1. `UserPromptSubmit` → records your prompt as a `prompt` event.
2. `PostToolUse` → records each tool call (`Edit`/`Write` → `file_edit`, `Bash` → `command`, otherwise `tool_use`).
3. `Stop` → flush: redact, derive git context from the **session's** repo (user/repo/branch, issue ref), pull the assistant's replies for the turn from the transcript as `message` events, detect languages, write `session-NNN.{yaml,md}`, commit, push.

Hooking per-event but committing per-session keeps GitHub noise low and avoids leaking partial state. Version-control plumbing the agent runs (`git`/`gh` commands) is dropped from the diary by default — it's process noise, not implementation; toggle with `/dev-diary:ignore-git` or `capture.ignore_git_ops`.

## Platform support

Cross-platform — hooks and CLI are pure Python.

- **Requirement:** Python 3.9+ in `PATH` as `python`, plus `pip install pyyaml`.
- On Linux distros where only `python3` is on `PATH`, install the `python-is-python3` package (Debian/Ubuntu) or alias `python` to `python3`. (If preferred, edit `hooks/hooks.json` to replace `python` with `python3` — the manifest is the only place it appears.)

## Status

Sketch / proposal. Claude Code is the first target (native plugin format). Cursor/Gemini/Codex adapters come next, writing into the same `entries/` schema so one CLI queries them all.
