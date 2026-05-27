---
description: Set up dev-diary capture — point the plugin at the user's diary repo
---

The user wants to enable dev-diary capture. Walk them through setup. This is a
first-time setup, so the goal is a working diary repo with a remote so sessions
auto-commit AND auto-push.

1. **Check prerequisites.** Run `python --version` (3.9+) and `python -c "import yaml"`. If PyYAML is missing, run `pip install pyyaml` (or `pip install --user pyyaml` if the global install is locked).

2. **Ask for the private diary repo URL.** The diary should live in the user's own (ideally private) git repo so sessions push there. Ask for the remote URL, e.g. `https://github.com/<user>/my-dev-diary.git`. If they haven't created it yet, tell them to create an empty private repo on their git host first (no README/license/gitignore, to avoid push conflicts), then come back with the URL.

3. **Ask where the local working copy should live** (a local path, e.g. `C:/Users/<user>/dev/my-dev-diary`), then set it up so `origin` points at the URL from step 2:
   - **Path doesn't exist** → `git clone <url> <path>`. Cloning sets `origin` automatically. (Works for an empty remote too.)
   - **Path exists, no `origin`** → `cd <path>` and `git remote add origin <url>`.
   - **Path exists with a different `origin`** → confirm with the user before changing it (`git remote set-url origin <url>`).
   Verify with `git -C <path> remote -v` that `origin` matches the URL.

4. **Run the setup script** to write `~/.dev-diary/state.json` and seed the config in one step. Find setup.py by globbing the plugin cache, then call it:
   ```bash
   SETUP=$(ls ~/.claude/plugins/cache/dev-diary/dev-diary/*/hooks/setup.py | head -1)
   python "$SETUP" --diary-root "<diary_root>"
   ```
   The script writes `~/.dev-diary/state.json` (the bridge between plugin and diary repo) and copies `config.example.yaml` → `<diary_root>/dev-diary.config.yaml` if the config doesn't exist yet. If you want to review the push/redaction defaults before the first session, open `<diary_root>/dev-diary.config.yaml` now. Note: `push.when: session_end` (the default) requires `origin` to be set and reachable — that's why step 3 matters.

5. **Seed the first push** (so credentials are confirmed and the branch tracks the remote): from `<diary_root>`, `git add -A && git commit -m "Initialize diary"` (if anything is uncommitted) then `git push -u origin main`. If push prompts for auth, that's the credential helper kicking in — let it complete once here so the silent push in the Stop hook works later.

6. **Confirm hooks are active.** Since the plugin is installed, the `UserPromptSubmit` / `PostToolUse` / `Stop` hooks are already wired — no `~/.claude/settings.json` edits needed. Confirm the last `/reload-plugins` showed them loaded (non-zero hooks, no load error).

7. **Sanity check.** Suggest they send any small prompt that triggers a tool call, then end the session, and verify a `session-001.{yaml,md}` lands under `<diary_root>/entries/YYYY/MM/YYYY-MM-DD/` and gets committed + pushed.
