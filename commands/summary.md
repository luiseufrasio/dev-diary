---
description: Visual HTML report for a period — category/language charts, sessions per day, projects, top files
argument-hint: [--week|--month]
---

Open a dev-diary summary report in the browser.

1. Check `~/.dev-diary/state.json` exists. If missing, tell the user to run `/dev-diary:enable` first.

2. Determine the period flag:
   - If the user passed `--month` or said "month" / "mês" / "30 days" → use `--month`
   - Otherwise → use `--week` (last 7 days, the default)

3. Execute:
   ```bash
   python ~/.claude/plugins/marketplaces/dev-diary/cli/dev-diary.py summary $ARGUMENTS
   ```

4. A browser window opens with the report. Tell the user what period is shown. If "no sessions" is printed, suggest running `dev-diary reindex` to rebuild the index, or note that there are no captured sessions in that window yet.
