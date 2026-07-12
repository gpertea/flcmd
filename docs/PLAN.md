# Staged plan

Each stage ends runnable and tested (xvfb GUI smoke tests + headless unit
tests). User review requested at milestones marked [REVIEW].

## Status (2026-07-12)
Stages 1-5b and 6.5 are DONE: dual-pane browsing, full file operations,
Lister-style viewer (text/hex/image, any file size), external F4 editor,
X11 drag and drop both ways, zip/tar browsing, built-in SSH/SFTP (tested
against a real host), image quick-view + thumbnails, folder shortcuts
menu + tree editor, locations toolbar. 108 tests green
(`xvfb-run -a uv run pytest`); ssh-marked tests need a reachable host.

### Next steps -- options (pick on resume)
1. Stage 6 plugins: Python plugin API mirroring TC semantics, then the
   ctypes TC C-ABI shim (WLX/WCX first). Largest work item.
2. Stage 7 power features: pane tabs (Ctrl+T/W/Tab), command line bar
   with history, Alt+F7 find files, Ctrl+B branch view, Alt+F1/F2 roots.
3. Archive write support: pack (Alt+F5) / unpack (Alt+F9), copy INTO
   zip archives.
4. Custom commands + MSYS2 integration (totalcmd-run-MSYS2-scripts.png
   reference is in the repo, still unaddressed).
5. Windows/macOS ports of the dnd drag-out shims (pywin32 OLE / pyobjc).
6. Smaller items: Ctrl+D hotlist keybinding, toolbar button reordering,
   Shift+F5 same-dir copy, background op queue, inotify watcher, EXIF
   rotation, remote/archive thumbnails + preview, options dialog.

## Stage 1 -- skeleton + browsing [DONE]
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
- Viewer image mode added later (stage 5b follow-up): image files open
  as pictures automatically (1/3/4 switch text/hex/image), zoom lock
  fit / fit-width / 100% ('z' cycles), persisted; WLX plugin viewing
  remains stage 6

## Stage 4 -- drag and drop [DONE EARLY, after stage 1]
- Drop IN per pane (FLTK FL_DND_* + text/uri-list paste) -> confirm + copy
- Drag OUT: dnd/x11.py XDND source via ctypes over FLTK's own X connection;
  verified end-to-end against a GTK drop target under Xvfb (xdotool-driven)
- Also landed early: menubar, mouse selection (click / Ctrl / Shift /
  dead-space clear), full-height pane background
- Still open: win32 (pywin32 OLE) and macOS (pyobjc) drag-out backends

## Stage 5 -- VFS: archives + built-in SSH [DONE]
- archive.py: zip/tar browsed as directories (read-only; Enter/Ctrl+PgDn
  opens, '..' pops out); copy-out via the ops engine; pack later
- ssh/: paramiko sessions, agent + pubkey auth, ssh_config aliases,
  custom config path in [ssh] config_file; sftp.py VFS with streaming
  prefetch; Ctrl+N connect (remembers last host), password fallback,
  Disconnect; F3 views remote/archived files via temp copy
- open: remote listdir runs on the UI thread (brief block), no pack/
  unpack into archives yet, no per-op concurrent sftp sessions

## Stage 5b -- image browser [DONE]
- panes/images.py: FLTK jpeg/png/gif/bmp decoders (fast C, no deps),
  Pillow fallback for webp (dev/optional); no Fl_Shared_Image (SWIG
  ownership conflicts -> double frees)
- Quick View panel (Ctrl+Q, TC-style): inactive pane previews the image
  under the other pane's cursor (80 ms debounce); zoom lock fit / fit
  width / 100% persisted in [preview], reapplied on pane/divider resize
- Thumbnail view per pane (Ctrl+Shift+F1 / Show menu): grid with
  filenames under tiles, configurable tile size (64-256 px, persisted in
  [thumbs]), incremental non-blocking decode, folder/placeholder tiles;
  cursor, selection, F5/F6/F8, drag-out all keep working
- open: preview/thumbs for non-local VFS, EXIF rotation, video thumbs

## Stage 6 -- plugins
- plugins/api.py: Python plugin API (viewer/packer/content/fs), discovery,
  enable/disable in settings
- tc_shim.py: ctypes host for TC C-ABI plugins -- WLX (viewer) and WCX
  (packer) first, WDX next, WFX later; backslash path shim; Windows-first,
  same C API for native .so on Linux  [REVIEW]

## Stage 6.5 -- shortcuts + UI polish [DONE]
- Panel headers: draggable-divider bevel continues into the directory
  label strip; active pane is app-owned (survives dialog focus-steal)
- Folder shortcuts menu (double-click panel header): multi-level, add
  current dir, works for sftp:// locations; JSON store in config dir
- Locations toolbar (Show menu, on by default): drop dirs to add
  buttons, left-click chdir active pane, right-click edit/delete
- Dialogs: auto-width labels (no truncation), '@' escaped everywhere
- Bookmark tree editor (Configure... / Configuration menu): add/edit/
  delete entries and submenus, move up/down, indent/outdent; edits on a
  working copy, saved only on OK
- Still open: toolbar button reordering

## Stage 7 -- power features + polish
- Tabs (Ctrl+T/W/Tab), command line bar with history, Alt+F7 search,
  Ctrl+B branch view, Alt+F1/F2 drive/root list
- Ctrl+D binding for the (already implemented) folder shortcuts menu
- Custom commands incl. MSYS2 bash script integration on Windows
- Options dialog, themes/fonts, PyInstaller packaging

## Known risks
- Drag-out on Wayland (XDND only works under XWayland); revisit.
- TC binary plugins assume Windows API beyond the plugin ABI (many WLX
  plugins create Win32 child windows) -- embedding needs a real HWND;
  on non-Windows only recompiled/native plugins can work.
- pyFLTK has no Linux wheels: Linux devs must build FLTK 1.4 (documented).
