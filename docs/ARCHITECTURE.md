# Architecture

## Overview
flcmd is a dual-pane file manager. The GUI (pyFLTK) is a thin layer over
toolkit-independent core modules; everything below `panes/` and `ui/` is
plain Python and testable headless.

```
src/flcmd/
  app.py        entry point: main window, menu, pane layout, command line bar
  config.py     settings (TOML in platform config dir), persisted state
  keymap.py     action table: key -> action name -> handler; user-remappable
  paths.py      canonical '/'-separated paths on ALL platforms; sole
                converter to/from native form (Windows drives, UNC)
  vfs/          filesystem abstraction -- all panes talk to a VFS, never
                to os.* directly
    base.py     VFS interface: listdir, stat, open, mkdir, remove, rename,
                copyfile hooks; DirEntry dataclass
    local.py    local filesystem
    sftp.py     paramiko-backed remote FS (built-in SSH)
    archive.py  zip/tar browsing (later: WCX packer plugins)
  panes/        file-list UI (Fl_Table-based), path bar, tabs, quick search
  ops/          copy/move/delete/mkdir engines with progress + conflict
                resolution, running in worker threads (queue + Fl.awake)
  viewer/       built-in file viewer (text/hex/image, encodings, wrap);
                standalone via `flcmd-view` / `python -m flcmd.viewer`;
                hosts WLX viewer plugins
  dnd/          drag OUT to other apps: x11.py (XDND, ctypes), win32.py
                (shell OLE drag; see docs/NOTES-pyfltk-win32-dnd.md)
                (OLE, pywin32), macos.py (pyobjc). Drop IN handled by FLTK
                events in panes.
  plugins/      plugin host
    api.py      Python plugin API mirroring TC semantics (WLX/WCX/WDX/WFX)
    tc_shim.py  ctypes loader for TC C-ABI plugins; converts canonical '/'
                paths to backslash form at this boundary only
  ssh/          paramiko session management, agent/pubkey auth, ssh_config
                alias parsing (custom config path on Windows), MSYS2 helpers
  ui/           dialogs (copy/move/delete/overwrite, connect, options), theme
tests/          pytest; gui-marked tests run under Xvfb (own display)
```

## Key rules
- Panes render `DirEntry` lists from a VFS; switching a pane to SFTP or an
  archive is just swapping its VFS instance. Cross-VFS copy streams through
  file objects.
- UI thread never blocks; long work posts progress via `Fl.awake(cb)`.
- All keyboard input flows through `keymap.py` (TC-compatible defaults, see
  docs/KEYBINDINGS.md).
- Canonical paths use `/` everywhere; `paths.to_native()` only at OS/plugin
  boundaries (see CLAUDE.md).

## Threading model
One UI thread (FLTK event loop). `ops.queue` owns a worker pool for file
operations; each operation reports (done_bytes, total, current_file) and
supports cancel. paramiko sessions live on their own threads; VFS calls from
ops workers are synchronous within the worker.
