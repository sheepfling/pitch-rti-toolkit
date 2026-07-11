"""Allow `python -m pitch` to run directly from the repository checkout."""

from __future__ import annotations

from pitch.cli import main


raise SystemExit(main())
