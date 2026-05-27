---
description: Toggle whether git/gh commands are excluded from the diary
argument-hint: <true|false>
---

Toggle `capture.ignore_git_ops` in the user's diary config. When true (default),
git/gh commands (add, commit, push, `gh pr create`, etc.) are dropped from the
diary as process noise; prompts, file edits, and assistant messages still record.

1. Read `~/.dev-diary/state.json` to get `diary_root`. If missing, tell the user to run `/dev-diary:enable` first.

2. Parse `$ARGUMENTS`: accept `true`/`on`/`1` → true, `false`/`off`/`0` → false. If empty or unrecognized, report the current value of `capture.ignore_git_ops` in `<diary_root>/dev-diary.config.yaml` and the accepted values, then stop.

3. Edit `<diary_root>/dev-diary.config.yaml` and set `ignore_git_ops:` under `capture:` to the chosen boolean (it's `true`/`false`, unquoted). If the key doesn't exist yet, add it under the `capture:` block.

4. Confirm the new value to the user. No reload is needed — `flush.py` reads the config fresh on every session flush, so the change applies to the next captured turn.
