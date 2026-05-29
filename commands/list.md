---
description: List session refs for a given date (default today) — one ref per line, ready for dev-diary:show
argument-hint: [YYYY-MM-DD]
---

List the refs of sessions recorded on a given date.

1. Check `~/.dev-diary/state.json` exists. If missing, tell the user to run `/dev-diary:enable` first.

2. Execute:
   ```bash
   python ~/.claude/plugins/marketplaces/dev-diary/cli/dev-diary.py list $ARGUMENTS
   ```

3. Show the output. Each entry shows `- {hash}  {time}` with the prompt indented below. If no sessions are found, say so clearly.
