# dev-diary — from zero to first captured session

End-to-end walkthrough: publish the plugin, create your diary repo, install in Claude Code, capture and query. Commands assume PowerShell on Windows; substitute `~/.claude` etc. on macOS/Linux.

> **Two repos, on purpose.** The **plugin repo** holds code (hooks, commands, CLI). The **diary repo** holds your data (`entries/`, config). They are linked by `~/.dev-diary/state.json`.

---

## 0. Prerequisites

```powershell
python --version          # 3.9+ required, must be on PATH as `python`
pip install pyyaml        # only external dep used by flush.py and the CLI
git --version
gh --version              # optional — makes GitHub repo creation one-liners
claude --version          # Claude Code
```

If only `python3` is on PATH (common on Debian/Ubuntu), either install `python-is-python3` or edit `hooks/hooks.json` in your plugin clone and replace `python` with `python3`.

---

## 1. Publish the plugin repo

You already have the source at `C:\Users\49770413\dev\dev-diary`. Push it to GitHub.

```powershell
cd C:\Users\49770413\dev\dev-diary
git init -b main
git add .
git commit -m "Initial dev-diary plugin"

# With gh CLI:
gh repo create dev-diary --public --source=. --push

# Or manually:
#   1. Create empty repo at github.com/<you>/dev-diary
#   2. git remote add origin https://github.com/<you>/dev-diary.git
#   3. git push -u origin main
```

---

## 2. Create your diary repo

Separate, **private** repo where your captured sessions land.

```powershell
cd C:\Users\49770413\dev
mkdir my-dev-diary
cd my-dev-diary
git init -b main

# Bring the default config (you'll edit this to tune redaction/push policy)
Copy-Item ..\dev-diary\config.example.yaml .\dev-diary.config.yaml

# Bring the CLI so /dev-diary:query and /dev-diary:show work
mkdir cli
Copy-Item ..\dev-diary\cli\dev-diary.py .\cli\

# Bring the .gitignore so the buffer + sqlite index stay local
Copy-Item ..\dev-diary\.gitignore .

git add .
git commit -m "Initialize diary"

gh repo create my-dev-diary --private --source=. --push
```

---

## 3. Install the plugin in Claude Code

The repo is its own marketplace (`.claude-plugin/marketplace.json`). Install in two steps — add the marketplace, then install the plugin from it:

```
/plugin marketplace add luiseufrasio/dev-diary
/plugin install dev-diary@dev-diary
```

`dev-diary@dev-diary` reads as `<plugin-name>@<marketplace-name>` — both happen to be `dev-diary` here.

**Local testing** (e.g. before pushing changes): point the marketplace at your local clone instead of GitHub. The local path must contain `.claude-plugin/marketplace.json`:

```
/plugin marketplace add C:\Users\49770413\dev\dev-diary
/plugin install dev-diary@dev-diary
```

Verify any time with `/plugin` (no args) for the interactive menu, or non-interactively:

```powershell
claude plugin validate .            # from the plugin/marketplace repo
claude plugin marketplace list
```

---

## 4. Enable capture for your diary

```
/dev-diary:enable
```

Answer the prompts; it writes:

```powershell
cat $HOME\.dev-diary\state.json
# { "diary_root": "C:\\Users\\49770413\\dev\\my-dev-diary" }
```

Until that file exists, the hooks exit silently — installed-but-not-enabled plugin is harmless.

---

## 5. Test capture

Open a fresh Claude Code session **in any project** (doesn't have to be the diary repo) and send a small prompt that triggers a tool call, e.g.:

> "List the files in the current directory."

Let Claude finish and exit the session (Ctrl+C / type `/exit`). The `Stop` hook fires the flush.

Verify the artifacts:

```powershell
# Buffer should be gone (flushed + cleaned):
ls C:\Users\49770413\dev\my-dev-diary\.dev-diary-buffer\ 2>$null

# Today's session pair should exist:
$today = Get-Date -Format 'yyyy-MM-dd'
$y = Get-Date -Format 'yyyy'; $m = Get-Date -Format 'MM'
ls "C:\Users\49770413\dev\my-dev-diary\entries\$y\$m\$today\"

# A commit should have landed in the diary repo:
cd C:\Users\49770413\dev\my-dev-diary
git log --oneline -1
# expect something like:  dev-diary: claude-code abc12345 on main (session-001)
```

Open `session-001.md` — you should see the prompt as a quote block and a numbered step-by-step of every tool call. Open `session-001.yaml` — same data, structured.

---

## 6. Query

From Claude Code:

```
/dev-diary:query
/dev-diary:query --since 2026-05-01 --language python
/dev-diary:show  2026/05/2026-05-23/session-001
```

From a terminal:

```powershell
$diary = "C:\Users\49770413\dev\my-dev-diary"
python $diary\cli\dev-diary.py reindex
python $diary\cli\dev-diary.py query --agent claude-code
python $diary\cli\dev-diary.py query --issue 123 -v
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| No yaml/md after a session ends | `cat ~\.dev-diary\state.json` exists and `diary_root` points somewhere real. |
| `ModuleNotFoundError: yaml` | `pip install pyyaml` (or `pip install --user pyyaml`). |
| Hook seems to never fire | Run `/plugin` and confirm `dev-diary` is listed and active. Check `~/.claude/plugins/dev-diary/hooks/hooks.json` exists. |
| `python: command not found` (Linux) | Edit `hooks/hooks.json` → replace `python` with `python3`, then reinstall the plugin. |
| Commit lands but `git push` fails | Check `~/.dev-diary/state.json` repo has a working `origin` and your git credentials are configured (`gh auth login` if using gh). Or set `push.when: every_n_minutes` in `dev-diary.config.yaml` to commit without pushing. |
| `session-001` keeps getting written (not 002, 003...) | The flush picks the next number by scanning today's folder — confirm previous sessions are committed and not deleted. |

### Manual flush dry-run

To exercise `flush.py` outside Claude Code (handy when debugging):

```powershell
# Drop a fake buffer:
$sid = "test-session"
$buf = "C:\Users\49770413\dev\my-dev-diary\.dev-diary-buffer"
mkdir $buf -Force | Out-Null
'{"timestamp":"2026-05-23T10:00:00-03:00","type":"prompt","actor":"human","summary":"test prompt"}' |
  Set-Content "$buf\$sid.jsonl"

# Invoke flush with a synthetic Stop payload:
"{`"session_id`":`"$sid`"}" | python $HOME\.claude\plugins\dev-diary\hooks\flush.py
```

A `session-NNN.{yaml,md}` should appear under today's `entries/` folder.
