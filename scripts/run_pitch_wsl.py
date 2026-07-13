#!/usr/bin/env python3
"""Launch Pitch inside WSL with explicit route environment and source path."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: run_pitch_wsl.py <env-json> <args-json>", file=sys.stderr)
        return 2

    env = json.loads(sys.argv[1])
    args = json.loads(sys.argv[2])
    if not isinstance(env, dict) or not isinstance(args, list):
        print("Invalid launcher payload.", file=sys.stderr)
        return 2

    os.environ.update({str(key): str(value) for key, value in env.items()})

    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))

    from pitch.cli import main as pitch_main

    return int(pitch_main([str(arg) for arg in args]))


if __name__ == "__main__":
    raise SystemExit(main())
