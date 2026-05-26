---
description: Query the dev-diary index — filter sessions by agent, issue, user, language, date
argument-hint: [--agent X] [--issue N] [--user EMAIL] [--language X] [--since DATE] [--until DATE]
---

Run a query against the user's local dev-diary index.

1. Read `~/.dev-diary/state.json` to get `diary_root`. If missing, tell the user to run `/enable-dev-diary` first.

2. Execute the CLI with the arguments the user passed:
   ```
   python <diary_root>/cli/dev-diary.py query $ARGUMENTS
   ```

3. Show the output verbatim. If empty, suggest broadening the filters.

4. If `$ARGUMENTS` is empty, list available filters: `--agent`, `--issue`, `--user`, `--project`, `--language`, `--since`, `--until`, `-v`.
