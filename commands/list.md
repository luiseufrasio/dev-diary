---
description: List session refs for a given date (default today) — one ref per line, ready for dev-diary:show
argument-hint: [YYYY-MM-DD]
---

List the refs of sessions recorded on a given date.

1. Read `~/.dev-diary/state.json` to get `diary_root`. If missing, tell the user to run `/dev-diary:enable` first.

2. Execute:
   ```
   python <diary_root>/cli/dev-diary.py list $ARGUMENTS
   ```

3. Show the output. Each line is a ref in the format `YYYY/MM/YYYY-MM-DD/session-NNN` that can be passed directly to `/dev-diary:show`. If no sessions are found, say so clearly.
