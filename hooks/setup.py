#!/usr/bin/env python3
"""One-time setup for /dev-diary:enable.

Writes ~/.dev-diary/state.json and copies config.example.yaml into the diary
repo if it doesn't exist yet. Called by the enable skill so these mechanical
steps don't require Claude to resolve the plugin cache path manually.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize dev-diary state and config.")
    parser.add_argument("--diary-root", required=True, help="Absolute path to the local diary repo")
    args = parser.parse_args()

    diary_root = Path(args.diary_root).resolve()
    if not diary_root.exists():
        print(f"error: diary-root does not exist: {diary_root}", file=sys.stderr)
        sys.exit(1)

    # Write ~/.dev-diary/state.json
    state_dir = Path.home() / ".dev-diary"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "state.json"
    state_file.write_text(
        json.dumps({"diary_root": str(diary_root).replace("\\", "/")}) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {state_file}")

    # Copy config.example.yaml → <diary_root>/dev-diary.config.yaml if missing
    config_dst = diary_root / "dev-diary.config.yaml"
    if config_dst.exists():
        print(f"config already exists at {config_dst} — skipping")
    else:
        config_src = Path(__file__).parent.parent / "config.example.yaml"
        shutil.copy(config_src, config_dst)
        print(f"created {config_dst}")
        print("  → review push.when and redaction rules before your first session")


if __name__ == "__main__":
    main()
