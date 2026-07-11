# flcmd

Multi-platform pyFLTK clone of the typical dual-pane file manager (like
Total Commander): TC keyboard shortcuts, built-in file viewer (also usable
standalone as `flcmd-view`), built-in SSH/SFTP, drag-and-drop to/from other
applications, and TC-compatible plugin support.

## Run

    uv sync
    uv run flcmd

## Develop / test

Headless unit tests:

    uv run pytest -m "not gui"

GUI tests (uses its own Xvfb display, never yours):

    xvfb-run -a uv run pytest

Linux needs FLTK 1.4 built from source for pyfltk (see docs/PLAN.md);
Windows/macOS get pyfltk wheels from PyPI.

Docs: `docs/ARCHITECTURE.md`, `docs/PLAN.md` (staged roadmap),
`docs/KEYBINDINGS.md`, `docs/PLUGINS.md`. Conventions: `CLAUDE.md`.
