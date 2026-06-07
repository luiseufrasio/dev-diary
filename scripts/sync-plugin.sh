#!/usr/bin/env bash
# Sync repo files to the installed Claude Code plugin directory.
# Run automatically via .git/hooks/post-commit, or manually: bash scripts/sync-plugin.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_DIR="$HOME/.claude/plugins/marketplaces/dev-diary"
CACHE_BASE="$HOME/.claude/plugins/cache/dev-diary/dev-diary"

if [[ ! -d "$PLUGIN_DIR" ]]; then
  echo "sync-plugin: plugin dir not found at $PLUGIN_DIR — skipping"
  exit 0
fi

copy_file() {
  local src="$1" dst="$2"
  mkdir -p "$(dirname "$dst")"
  cp "$src" "$dst"
}

# --- cli ---
copy_file "$REPO_DIR/cli/dev-diary.py" "$PLUGIN_DIR/cli/dev-diary.py"

# --- hooks ---
for f in "$REPO_DIR/hooks/"*.py; do
  [[ -f "$f" ]] || continue
  copy_file "$f" "$PLUGIN_DIR/hooks/$(basename "$f")"
done

# --- commands (skills) ---
for f in "$REPO_DIR/commands/"*.md; do
  [[ -f "$f" ]] || continue
  copy_file "$f" "$PLUGIN_DIR/commands/$(basename "$f")"
  # also sync to every cache hash dir
  if [[ -d "$CACHE_BASE" ]]; then
    for hash_dir in "$CACHE_BASE"/*/; do
      [[ -d "$hash_dir/commands" ]] || continue
      copy_file "$f" "$hash_dir/commands/$(basename "$f")"
    done
  fi
done

echo "sync-plugin: synced to $PLUGIN_DIR"
