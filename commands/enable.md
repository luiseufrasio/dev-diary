---
description: Set up dev-diary capture — point the plugin at the user's diary repo
---

The user wants to enable dev-diary capture. Walk them through setup:

1. **Check prerequisites.** Run `python --version` (3.9+) and `python -c "import yaml"`. If PyYAML is missing, run `pip install pyyaml` (or `pip install --user pyyaml` if the global install is locked).

2. **Ask where the diary repo lives.** Two paths:
   - They already cloned a fork of `dev-diary` somewhere → ask for the absolute path.
   - They don't have one yet → offer to `git clone https://github.com/<their-user>/dev-diary <path>` (after they fork via the GitHub UI).

3. **Write the state file.** Create `~/.dev-diary/state.json` with:
   ```json
   { "diary_root": "<absolute path to their diary repo>" }
   ```
   The hooks read this to know where to flush sessions.

4. **Verify the config exists.** If `<diary_root>/dev-diary.config.yaml` is missing, copy `${CLAUDE_PLUGIN_ROOT}/config.example.yaml` into place and open it for them to edit redaction patterns / push policy.

5. **Confirm hooks are active.** Tell the user that since the plugin is installed, the `UserPromptSubmit` / `PostToolUse` / `Stop` hooks are already wired — no `~/.claude/settings.json` edits needed. Next prompt in any session will start writing to their diary.

6. **Sanity check.** Suggest they send any small prompt to verify a `session-001.{yaml,md}` lands under `<diary_root>/entries/YYYY/MM/YYYY-MM-DD/`.
