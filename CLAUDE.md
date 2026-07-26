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

## pyFLTK rules (hard-won -- full write-ups in docs/NOTES-pyfltk.md)
- **Parentless widgets must outlive every FLTK reference to them.** A
  widget not added to a group is owned by the Python proxy: when the last
  Python ref goes, the C++ object is freed while FLTK may still point at
  it, and the process dies later in an unrelated redraw. Add it to a
  group, or keep one long-lived instance and reuse it (popups go through
  `ui/menus.popup()`).
- **Windows: native calls that deliver or pump window messages go through
  `ctypes.PyDLL`, never `windll`** (which releases the GIL): DoDragDrop,
  SetWindowPos/SetWindowLongPtr/ShowWindow/SendMessage, TrackPopupMenu,
  MessageBox. pyfltk callbacks fired from those messages need the GIL.
- **Do not reach for Fl_Table for list/pane UIs** -- it fights custom
  scrollbars, column resizing and vertical-only scrolling; flcmd draws its
  own `FileList`.

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
- Linux setup: `scripts/setup.sh` (builds a minimal local FLTK 1.4 into
  ~/.local if missing, then runs `uv sync`); Windows/macOS: plain `uv sync`.
  `uv run flcmd` to launch. Full Linux install notes: docs/INSTALL-LINUX.md.
- On Linux pyfltk comes from a patched sdist vendored in `vendor/`
  ([tool.uv.sources] marker) -- upstream's no-GL build is broken; the patch
  lives in scripts/patches/. FLTK is built X11-only, no GL, bundled
  jpeg/png/zlib, static PIC libs.
- GUI tests use a separate display via Xvfb -- never the user's display:
  `xvfb-run -a uv run pytest` or the `xdisplay` fixture in tests/conftest.py
  (spawns its own Xvfb; tests skip if Xvfb is not installed). Headless logic
  tests run with plain `uv run pytest -m "not gui"`.

## Windows GUI testing: use the VirtualBox VM, never the host desktop
Synthetic mouse/keyboard input on the developer's desktop interferes with
their work. All interactive Windows testing runs in the VirtualBox VM
**Win10x64** (guest login: user `claude`, password `tester123`), driven
with VBoxManage from the host:
- Host OS determines the binary: Windows host ->
  `C:\Program Files\Virtualbox7\VBoxManage.exe`, invoked from
  **PowerShell** (MSYS2 bash mangles `/c`-style guest arguments into
  paths); Linux host -> `VBoxManage` on PATH.
- If the VM is not running: `VBoxManage startvm Win10x64 --type gui`,
  then poll `showvminfo` until the "VirtualBox System Service" facility
  is active (~40 s).
- Guest quoting through `guestcontrol run` is unreliable: for anything
  non-trivial write a `.ps1` locally, `guestcontrol copyto` it, then
  `run --exe powershell.exe -- powershell -NoProfile -ExecutionPolicy
  Bypass -File <script>`.
- **NEVER run `guestcontrol closesession --all` -- it aborts (crashes)
  the whole VM process** (reproduced twice on VBox 7.2.14). Sessions
  linger after each `run`; that is harmless. If they pile up or the VM
  gets weird, reboot it (`controlvm Win10x64 reboot`, or after an abort
  `startvm`). Stuck sessions come from killing VBoxManage mid-call --
  use generous timeouts instead.
- Deploy: `git archive --format=zip HEAD` -> copyto ->
  `Expand-Archive` -> `uv sync --python
  "C:\Program Files\Python312\python.exe"` (uv in guest:
  `C:\Users\claude\.local\bin\uv.exe`). The guest has python.org
  3.12.10 installed all-users; ALWAYS pass that `--python`: venvs from
  uv-managed CPython get a console-subsystem pythonw trampoline (ugly
  conhost window behind the GUI). Guest scratch dir: `C:\test\flcmd\`
  (app tree in `app\`, test area `playground\`). Single-file
  iteration: copyto straight into `app\src\flcmd\...` (editable
  install) and restart the app.
- Drive input with `VBoxManage controlvm Win10x64 keyboardputscancode`
  (press/release pairs, e.g. Enter `1c 9c`, F8 `42 c2`, Tab `0f 8f`,
  Down `e0 50 e0 d0`); verify visually with
  `controlvm Win10x64 screenshotpng <file>` and read the PNG.
- The VM has **Total Commander 10.52** at
  `C:\util\totalcmd\TOTALCMD64.EXE` -- launch and drive it there
  (keyboardputscancode + screenshots) to check reference behavior when
  implementing TC features.
