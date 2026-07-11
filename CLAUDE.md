# flcmd

Cross-platform (Linux/Windows/macOS) dual-pane file manager in Python + pyFLTK,
emulating Total Commander functionality and keyboard shortcuts.

## Guiding principles
- Modular code: small, reusable components; each module usable standalone where
  it makes sense (e.g. the file viewer).
- Compact code, concise and sparse comments -- comment only non-trivial blocks.
- ASCII only in code, comments, and output.
- Prefer stdlib; add dependencies only when clearly justified.

## Hard conventions
- **Path separator is `/` everywhere, on all platforms, including Windows.**
  Never emit or store `\` paths. All internal/canonical paths use `/`.
  `flcmd.paths` is the ONLY place that converts to/from native form
  (`to_native()` / `from_canon()`), used at OS-API and TC-plugin boundaries
  (TC plugins get backslash paths via the shim) and for UNC/Samba paths.
- GUI code never blocks: file operations, SFTP, and archive work run in worker
  threads; UI updates go through `Fl.awake()` callbacks.
- Every keyboard action goes through `flcmd.keymap` (action table), never
  hardcoded key handling in widgets -- keybindings are user-remappable.

## Stack decisions (settled -- do not relitigate)
- GUI: pyFLTK 1.4 (FLTK 1.4 built from source on Linux; wheels on Win/mac).
- Drag-and-drop OUT to other apps: per-platform native shims in `flcmd.dnd`
  (X11/XDND via ctypes first; pywin32 OLE and pyobjc later). Drop IN uses
  FLTK's native DND events (`FL_DND_*` + `FL_PASTE` text/uri-list).
- SSH/SFTP: paramiko (pure Python), built-in (not a plugin). Pubkey auth and
  ssh_config aliases on all platforms; custom config/keys path in settings on
  Windows; MSYS2 integration (bash scripts as custom commands) when installed.
- Plugins: tiered TC compatibility -- Python plugin API mirroring TC semantics
  on all platforms; ctypes loader for real TC DLLs (WLX/WCX/WDX, later WFX) on
  Windows; same C API for natively compiled .so/.dylib on Linux/macOS.
- Python >= 3.11, uv-managed project (`uv sync`, `uv run`). PyInstaller later.
- Any native/C++ code on Windows is built with the MSYS2/MinGW toolchain
  (ucrt64) -- NO MSVC support or compatibility required. Native code must
  stay portable (Linux gcc/clang, macOS clang, Windows mingw-w64 ucrt).
- Prefer pure-Python shims (ctypes) over compiled patches when both work;
  compiled C++ is fine when genuinely needed (e.g. plugin window embedding).

## Layout
- `src/flcmd/` -- app package; `app.py` is the entry point.
  - `paths.py` canonical path handling; `vfs/` filesystem abstraction
    (local, sftp, archive); `panes/` file-list UI; `ops/` file operations;
    `viewer/` built-in viewer (also standalone: `flcmd-view` / `python -m
    flcmd.viewer`); `dnd/` drag-out shims; `plugins/` plugin host;
    `ssh/` session/config; `ui/` dialogs and theme; `keymap.py` shortcuts.
- `docs/` -- ARCHITECTURE.md, PLAN.md (staged roadmap), KEYBINDINGS.md,
  PLUGINS.md.
- `tests/` -- pytest; GUI tests need an X display.

## Build / run / test
- `uv sync` to set up; `uv run flcmd` to launch.
- GUI tests use a separate display via Xvfb -- never the user's display:
  `xvfb-run -a uv run pytest` or the `xdisplay` fixture in tests/conftest.py
  (spawns its own Xvfb). Headless logic tests run with plain `uv run pytest -m
  "not gui"`.
- FLTK 1.4.5 is installed to /usr/local (built from source); pyfltk builds
  against it via `fltk-config`.
