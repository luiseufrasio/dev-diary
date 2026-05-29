---
description: Open a session as an interactive slide deck in the browser — one slide per turn, with actions, diffs, command output, and Claude's response
argument-hint: <hash>
---

Open a dev-diary session as a slide presentation in the browser.

1. Check `~/.dev-diary/state.json` exists. If missing, tell the user to run `/dev-diary:enable` first.

2. Execute:
   ```bash
   python ~/.claude/plugins/marketplaces/dev-diary/cli/dev-diary.py replay $ARGUMENTS
   ```
   The CLI accepts either a bare hash (e.g. `a743e5c5`) or a full ref (`2026/05/29/a743e5c5`).

3. A browser window opens with the slide deck. Tell the user they can navigate with ← → arrow keys or the Back/Next buttons. If the hash isn't found, suggest running `/dev-diary:list` to find available sessions.
