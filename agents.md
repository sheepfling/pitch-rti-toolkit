# Agent notes

- Use a platform-specific virtual environment directory.
- Do not share one `.venv` between WSL/Linux, Windows, and macOS.
- Recommended names are `.venv-wsl`, `.venv-win`, and `.venv-macos`.
- When editing or testing, assume each platform has its own isolated venv and
  package set.
- The project dev install target is `.[dev]`, which currently includes `pytest`.
- Port selection is route-scoped and deterministic; do not reintroduce shared
  localhost defaults such as a single `8989`/`8080` pair for every platform.
