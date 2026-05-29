---
description: Query the dev-diary index — filter sessions by agent, issue, user, language, date
argument-hint: [--agent X] [--issue N] [--user EMAIL] [--language X] [--since DATE] [--until DATE]
---

Run a query against the user's local dev-diary index.

1. Check `~/.dev-diary/state.json` exists. If missing, tell the user to run `/dev-diary:enable` first.

2. Find the plugin CLI and execute with the arguments the user passed:
   ```bash
   CLI=$(ls ~/.claude/plugins/cache/dev-diary/dev-diary/*/cli/dev-diary.py | head -1)
   python "$CLI" query $ARGUMENTS
   ```

3. Show the output verbatim. If empty, suggest broadening the filters.

4. If `$ARGUMENTS` is empty, list available filters: `--agent`, `--issue`, `--user`, `--project`, `--language`, `--since`, `--until`, `-v`.
