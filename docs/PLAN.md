# Staged plan

Each stage ends runnable and tested (xvfb GUI smoke tests + headless unit
tests). User review requested at milestones marked [REVIEW].

## Stage 1 -- skeleton + browsing (this stage)
- paths.py (canonical '/' paths, native conversion, tests)
- vfs base + local
- Main window: dual panes (Fl_Table file lists), path bar, active-pane
  tracking, Tab switching
- Navigation: Enter/Backspace, sorting (name/ext/size/date, Ctrl+F3..F6),
  selection (Ins, Space, +/- glob, Ctrl+A), quick search
- keymap with TC defaults; config load/save
- xvfb test fixture; smoke test: app opens, lists dir, navigates  [REVIEW]

## Stage 2 -- file operations [DONE]
- ops/fileops.py engine: F5 copy, F6 move (fast rename + copy/delete
  fallback), F7 mkdir (nested), F8/Del delete; worker thread + progress
  dialog with cancel; Overwrite/Overwrite All/Skip/Skip All conflicts;
  Retry/Skip/Skip All error prompts; drop-in copies use the same engine
- F2/Shift+F6 inline rename (in-place Fl_Input, Esc cancels); Alt+Enter
  properties; Ctrl+L occupied space; Space computes dir size
- Symlinks are copied as links by default; "Follow symlinks" checkbox in
  the copy/move dialog copies targets instead. Panes auto-refresh on
  external changes (1s dir-mtime poll; local VFS only -- misses in-place
  size changes of existing files, revisit with inotify later)
- Still open: same-dir Shift+F5 copy-as, background op queue

## Stage 3 -- viewer + editor [DONE]
- viewer/: TC Lister equivalent -- text mode (UTF-8 default, ASCII-only
  option), hex mode, line wrap, case-insensitive search with wraparound
  (F7/Ctrl+F, F3/Shift+F3), font + size configurable, multi-file n/p;
  standalone `flcmd-view FILE...`; options persisted immediately
- F4 external editor only (no internal editor): command configured on
  first use or via Configuration menu; Shift+F4 creates + edits
- config: flcmd.ini (configparser, wincmd.ini style) replaces TOML;
  typed load; [viewer]/[editor]/[window]/[left]/[right]/[keys] sections
- Files of ANY size open instantly: only a sliding window (window_mb,
  default 8 MB) is held; a file-wide scrollbar maps the whole file, the
  window follows scrolling (auto-slide near edges), Ctrl+Home/End jump to
  file start/end, and search streams over the file on disk in both
  directions with wraparound. Small files use the normal scrollbar only.
- Still open: image mode (with WLX plugins, stage 6)  [REVIEW]

## Stage 4 -- drag and drop [DONE EARLY, after stage 1]
- Drop IN per pane (FLTK FL_DND_* + text/uri-list paste) -> confirm + copy
- Drag OUT: dnd/x11.py XDND source via ctypes over FLTK's own X connection;
  verified end-to-end against a GTK drop target under Xvfb (xdotool-driven)
- Also landed early: menubar, mouse selection (click / Ctrl / Shift /
  dead-space clear), full-height pane background
- Still open: win32 (pywin32 OLE) and macOS (pyobjc) drag-out backends

## Stage 5 -- VFS: archives + built-in SSH
- archive.py: browse zip/tar as directories; pack/unpack via F5
- ssh/: paramiko sessions, agent + pubkey auth, ssh_config aliases,
  custom config path setting (Windows); sftp.py VFS; connect dialog
  (Ctrl+N / Net menu), reconnect, host key prompts  [REVIEW]

## Stage 6 -- plugins
- plugins/api.py: Python plugin API (viewer/packer/content/fs), discovery,
  enable/disable in settings
- tc_shim.py: ctypes host for TC C-ABI plugins -- WLX (viewer) and WCX
  (packer) first, WDX next, WFX later; backslash path shim; Windows-first,
  same C API for native .so on Linux  [REVIEW]

## Stage 7 -- power features + polish
- Tabs (Ctrl+T/W/Tab), command line bar with history, Alt+F7 search,
  Ctrl+B branch view, directory hotlist (Ctrl+D), Alt+F1/F2 drive/root list
- Custom commands incl. MSYS2 bash script integration on Windows
- Options dialog, themes/fonts, PyInstaller packaging

## Known risks
- Drag-out on Wayland (XDND only works under XWayland); revisit.
- TC binary plugins assume Windows API beyond the plugin ABI (many WLX
  plugins create Win32 child windows) -- embedding needs a real HWND;
  on non-Windows only recompiled/native plugins can work.
- pyFLTK has no Linux wheels: Linux devs must build FLTK 1.4 (documented).
