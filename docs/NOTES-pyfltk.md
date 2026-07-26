# pyFLTK gotchas (tech notes)

Hard-won findings; each one cost a debugging session. Relevant to ANY
pyFLTK app, not just flcmd.

1. [Widget lifetime](#1-widget-lifetime-parentless-widgets-die-with-their-python-ref)
2. [The GIL trap on Windows](#2-the-gil-trap-native-calls-that-deliver-messages)
3. [Fl_Table is not a file list](#3-fl_table-is-not-a-file-list)

---

# 1. Widget lifetime: parentless widgets die with their Python ref

**Symptom** (2026-07, folder-shortcuts menu): picking an item from a
popup menu killed the process an unpredictable moment later, with an
access violation inside a completely unrelated redraw.

**Cause.** A widget added to a group is owned by FLTK; a **parentless**
widget is owned by the Python proxy and its C++ object is freed as soon
as the last Python reference goes away. A menu built per call:

    mb = fltk.Fl_Menu_Button(x, y, 0, 0)   # no parent
    ...
    mb.popup()                             # returns -> mb is garbage

is freed while FLTK still holds pointers to it (picked item + its
callback data, `Fl::pushed()`, damage list). The crash lands wherever
that memory is next touched -- typically a later redraw, hence the
delay, which makes the real culprit invisible in the traceback.

**Rule.** Any widget created without a parent must outlive every FLTK
reference to it. Either add it to a group/window, or keep one
long-lived instance and reuse it. flcmd does the latter for popups:
`ui/menus.py` keeps a single `Fl_Menu_Button`, `clear()`s and
repositions it per popup. Same applies to menus built in a callback,
temporary dialogs held in locals, and image/box objects passed to
widgets that keep a raw pointer.

---

# 2. The GIL trap: native calls that deliver messages

From implementing file drag-out on Windows (`flcmd/dnd/win32.py`,
2026-07). Relevant to any pyFLTK app calling a blocking native Windows
API via ctypes -- not just drag and drop.

## The crash

Starting an OLE drag (`DoDragDrop` / `SHDoDragDrop` called via
`ctypes.windll`) from inside a widget's `handle()` crashed the process
within ~1 s: `access violation reading 0x10`, faulting module
**python312.dll** (found via a vectored exception handler; Python
faulthandler alone only shows the Python frame around the ctypes call).

Red herrings we chased first: our hand-rolled ctypes IDataObject
vtables (rewriting them to use only shell-provided COM objects changed
nothing), FLTK's drop target on our own window (revoking it changed
nothing), app timers, multi-monitor.

## Root cause

- `ctypes.windll` / `CDLL` **releases the GIL** around every foreign
  call, including a blocking `SHDoDragDrop`.
- `SHDoDragDrop` runs a **modal message loop on the calling thread**.
  That loop dispatches queued window messages (paint, timers, DND
  enter/over on our own windows) to FLTK's WndProc.
- FLTK then invokes Python-side overrides (`handle()`, `draw()`,
  timeout callbacks) through pyfltk's SWIG wrappers, which **assume the
  GIL is held** -- true under `Fl.run()` / `Fl.wait()`, false inside a
  ctypes call. Python C-API without the GIL -> access violation inside
  python3xx.dll.

A console process without FLTK windows never crashed (nothing calls
back into Python from the modal loop) -- that contrast was the key
diagnostic step.

## The fix (one line)

Call the blocking API through **`ctypes.PyDLL`**, which keeps the GIL:

    _shell32_gil = ctypes.PyDLL("shell32")
    _shell32_gil.SHDoDragDrop.restype = ctypes.c_long
    ...
    hr = _shell32_gil.SHDoDragDrop(None, pdo, None, effects, byref(eff))

Every FLTK/Python callback dispatched from inside the drag loop now
runs with the GIL held, exactly as under `Fl.run()`. Trade-off: other
Python threads are paused for the (short, user-interactive) drag.

## General rule for pyFLTK apps on Windows

Any native call that can **re-enter the Windows message loop** on the
GUI thread must go through `PyDLL`, not `windll`, if FLTK windows
exist: `DoDragDrop`/`SHDoDragDrop`, `TrackPopupMenu`, `MessageBox`,
common dialogs, anything COM that pumps messages -- and also calls that
deliver messages **synchronously** to the target WndProc rather than
pumping a loop: `SetWindowPos` (WM_NCCALCSIZE et al., confirmed crash
with SWP_FRAMECHANGED), `SetWindowLongPtr` (WM_STYLECHANGED),
`ShowWindow`, `SendMessage` of any kind aimed at an FLTK window. Fast,
non-message-delivering calls are fine via `windll`.

Is this pyFLTK-specific? The GIL aspect, yes: C++ FLTK apps have no
GIL, and bindings whose callbacks do `PyGILState_Ensure` themselves
(e.g. comtypes-implemented COM servers, ctypes callback functions)
are also safe. It will bite any Python GUI binding whose event
dispatch assumes the GIL, whenever a ctypes-released-GIL call pumps
messages.

## Why not Fl::dnd() for files, and the rest of the recipe

- FLTK's own drag-out (`Fl::dnd()`) on Windows serves **CF_UNICODETEXT
  only** (fl_dnd_win32.cxx, FLDataObject::GetData) -- Explorer ignores
  text drags, so files need a CF_HDROP data object.
- Cleanest source setup, no COM interfaces implemented in Python:
  `SHParseDisplayName` (path -> PIDL) ->
  `SHCreateShellItemArrayFromIDLists` ->
  `BindToHandler(BHID_DataObject)` (= Explorer's own data object:
  CF_HDROP + shell formats + drag visuals) ->
  `SHDoDragDrop(NULL, pdo, NULL, effects, &eff)` (NULL drop source:
  the shell provides one). Note: `SHCreateDataObject` alone is NOT
  enough -- it does not serve CF_HDROP.
- Drop-IN needs no OLE work: FLTK's built-in drop target delivers
  files as an FL_PASTE with newline-separated **native** paths (drive
  letters, backslashes) -- parse accordingly. But never open a dialog
  inside the FL_PASTE handler: it runs synchronously inside the
  *source* application's modal drag loop (defer with
  `Fl.add_timeout(0.0, ...)`), and FLTK does not update Fl modifiers
  during OLE drags (query `GetKeyState` for Shift=move semantics).

---

# 3. Fl_Table is not a file list

flcmd's file panes started on `Fl_Table_Row` and fought it for weeks
(2026-07) before switching to a custom-drawn `FileList` (an `Fl_Box`,
~300 lines, in `panes/panel.py`). What Fl_Table does that a TC-style
pane must not:

- It **owns its scrollbars** and re-shows/re-places them on every
  internal recalc. Hiding or repositioning them per draw is a race you
  lose (they spring back over the header); unparenting them leaves
  stale pixels because its damage tracking still assumes they exist.
- No way to have vertical-only scrolling: the h-scrollbar reappears
  whenever columns overflow, and it de-syncs header hot zones from the
  drawn dividers.
- Its own `col_resize` machinery keeps grabbing borders (including the
  last column's right edge) whatever you layer on top.
- It reserves phantom strips (a stray grey row at the pane bottom).

If every cell is custom-drawn anyway -- which is the case for any
TC-like pane (icons, per-type colors, ellipsis, sort arrows) -- Fl_Table
contributes only scroll arithmetic that is a dozen lines to write, so
prefer a plain widget: only visible rows are painted, and behavior is
exactly what you draw. No C++ needed.
