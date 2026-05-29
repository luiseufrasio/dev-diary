---
description: Show a single diary entry by its hash (e.g. a743e5c5)
argument-hint: <hash>
---

Show the markdown content of a specific dev-diary session.

1. Check `~/.dev-diary/state.json` exists. If missing, tell the user to run `/dev-diary:enable` first.

2. Find the plugin CLI and execute:
   ```bash
   CLI=$(ls ~/.claude/plugins/cache/dev-diary/dev-diary/*/cli/dev-diary.py | head -1)
   python "$CLI" show $ARGUMENTS
   ```
   The CLI accepts either a bare hash (e.g. `a743e5c5`) or a full ref (`2026/05/29/a743e5c5`).

3. Render the markdown the CLI returns. If the ref isn't found, list the most recent sessions to help the user pick.
