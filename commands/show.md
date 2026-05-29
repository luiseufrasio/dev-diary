---
description: Show a single diary entry by its ref (e.g. 2026/05/2026-05-23/session-001)
argument-hint: <YYYY/MM/YYYY-MM-DD/session-NNN>
---

Show the markdown content of a specific dev-diary session.

1. Check `~/.dev-diary/state.json` exists. If missing, tell the user to run `/dev-diary:enable` first.

2. Find the plugin CLI and execute:
   ```bash
   CLI=$(ls ~/.claude/plugins/cache/dev-diary/dev-diary/*/cli/dev-diary.py | head -1)
   python "$CLI" show $ARGUMENTS
   ```

3. Render the markdown the CLI returns. If the ref isn't found, list the most recent sessions to help the user pick.
