"""Main application: dual panes, function-key bar, action dispatch."""

import os
import re
import stat as st_mod
import sys
from datetime import datetime

import fltk

from . import config, ops, paths, viewer
from .keymap import Keymap
from .panes import FilePane
from .ui import dialogs, progress
from .vfs import LocalVFS

MENU_H = 25
FKEY_H = 26
FKEYS = [
    ("F3 View", "file.view"), ("F4 Edit", "file.edit"),
    ("F5 Copy", "file.copy"), ("F6 Move", "file.move"),
    ("F7 MkDir", "file.mkdir"), ("F8 Delete", "file.delete"),
    ("Alt+F4 Exit", "app.quit"),
]
NOT_YET: dict[str, str] = {}


class PaneTile(fltk.Fl_Group):
    """Two-pane splitter with a comfortable divider grab zone and a
    TC-style proportional split on resize (plain Fl_Group: Fl_Tile's
    hair-line hot area and edge-absorbing resize both get replaced)."""

    GRAB = 4  # px each side of the divider
    MIN_PANE = 120

    def __init__(self, *args):
        super().__init__(*args)
        self._div_drag = False
        self._we_cursor = False

    def _div_x(self) -> int:
        c = self.child(0)
        return c.x() + c.w()

    def _near(self) -> bool:
        return (self.children() >= 2
                and abs(fltk.Fl.event_x() - self._div_x()) <= self.GRAB)

    def _split(self, divx: int):
        divx = min(max(divx, self.x() + self.MIN_PANE),
                   self.x() + self.w() - self.MIN_PANE)
        y, h, rx = self.y(), self.h(), self.x() + self.w()
        self.child(0).resize(self.x(), y, divx - self.x(), h)
        self.child(1).resize(divx, y, rx - divx, h)
        self.init_sizes()
        self.redraw()

    def resize(self, x, y, w, h):
        # keep the split ratio (TC-like), not Fl_Tile's edge-absorbing
        ratio = (self._div_x() - self.x()) / self.w() \
            if self.children() >= 2 and self.w() > 0 else 0.5
        fltk.Fl_Widget.resize(self, x, y, w, h)
        if self.children() >= 2:
            self._split(x + round(w * ratio))

    def handle(self, event):
        if event in (fltk.FL_MOVE, fltk.FL_ENTER):
            near = self._near()
            if near:  # every move: the window handler resets the cursor
                self.window().cursor(fltk.FL_CURSOR_WE)
                self._we_cursor = True
                return 1
            if self._we_cursor:
                self._we_cursor = False
                self.window().cursor(fltk.FL_CURSOR_DEFAULT)
        elif (event == fltk.FL_PUSH
              and fltk.Fl.event_button() == fltk.FL_LEFT_MOUSE
              and self._near()):
            self._div_drag = True
            return 1
        elif event == fltk.FL_DRAG and self._div_drag:
            self._split(fltk.Fl.event_x())
            return 1
        elif event == fltk.FL_RELEASE and self._div_drag:
            self._div_drag = False
            return 1
        return super().handle(event)


class App:
    def __init__(self, left_path: str | None = None, right_path: str | None = None):
        self.cfg = config.load()
        w = int(self.cfg.get("window", {}).get("w", 1000))
        h = int(self.cfg.get("window", {}).get("h", 640))
        self.keymap = Keymap(self.cfg.get("keys"))
        self._viewers: list = []

        from .ui.cmdline import CMD_H, CmdLine
        from .ui.titlebar import TITLEBAR_H, BorderlessWindow, TitleBar
        from .ui.toolbar import LocationsToolbar, TOOLBAR_H
        self.custom_title = bool(
            self.cfg.get("ui", {}).get("custom_titlebar",
                                       sys.platform == "win32"))
        if self.custom_title:
            self.win = BorderlessWindow(w, h, "flcmd")
            self.titlebar = TitleBar(0, 0, w, TITLEBAR_H, self.win)
        else:
            self.win = fltk.Fl_Double_Window(w, h, "flcmd")
            self.titlebar = None
        self._top0 = TITLEBAR_H if self.custom_title else 0
        self.menubar = fltk.Fl_Menu_Bar(0, self._top0, w, MENU_H)
        self.menubar.box(fltk.FL_THIN_UP_BOX)
        self._build_menu()
        self.show_toolbar = bool(self.cfg.get("toolbar", {}).get("show", True))
        tb_h = TOOLBAR_H if self.show_toolbar else 0
        self.toolbar = LocationsToolbar(
            0, self._top0 + MENU_H, w, TOOLBAR_H,
            lambda loc: self._go_location(self.active(), loc), self.win,
            nav_cb=lambda d: self.dispatch("nav.back" if d < 0 else "nav.fwd",
                                           self.active()))
        if not self.show_toolbar:
            self.toolbar.hide()
        self.show_cmdline = bool(self.cfg.get("cmdline", {}).get("show", True))
        cmd_h = CMD_H if self.show_cmdline else 0
        top = self._top0 + MENU_H + tb_h
        ph = h - top - FKEY_H - cmd_h
        self.tile = PaneTile(0, top, w, ph)
        vfs = LocalVFS()
        lp = self._start_path(vfs, left_path, "left")
        rp = self._start_path(vfs, right_path, "right")
        self.left = FilePane(0, top, w // 2, ph, vfs, lp, self.dispatch, self.keymap)
        self.right = FilePane(w // 2, top, w - w // 2, ph, vfs, rp, self.dispatch, self.keymap)
        self.tile.end()
        for side in ("left", "right"):
            p = getattr(self, side)
            p.sort_key = self.cfg.get(side, {}).get("sort", "name")
            p.sort_rev = bool(self.cfg.get(side, {}).get("rev", False))
            p.refresh()

        self.cmdline = CmdLine(0, h - FKEY_H - CMD_H, w, CMD_H,
                               self._run_command, self._focus_active_pane)
        if not self.show_cmdline:
            self.cmdline.hide()

        from .ui.buttons import HoverButton
        bar = fltk.Fl_Group(0, h - FKEY_H, w, FKEY_H)
        bw = w // len(FKEYS)
        for i, (label, action) in enumerate(FKEYS):
            b = HoverButton(i * bw, h - FKEY_H,
                            bw if i < len(FKEYS) - 1 else w - bw * i, FKEY_H, label)
            b.box(fltk.FL_THIN_UP_BOX)
            b.labelsize(11)
            b.clear_visible_focus()
            b.callback(self._fkey_cb, action)
        bar.end()
        self.win.end()
        self.win.resizable(self.tile)
        self.win.callback(self._win_cb)
        self.win.size_range(400, 300)
        self._watching = True
        fltk.Fl.add_timeout(1.0, self._watch_tick)
        self.left.on_cursor = self.right.on_cursor = self._cursor_moved
        self.left.on_path = self.right.on_path = self._path_changed
        self._active = self.left
        self.set_active_pane(self.left)

    def _build_menu(self):
        mb, cb = self.menubar, self._menu_cb
        inactive = fltk.FL_MENU_INACTIVE
        mb.add("&Files/&Edit\tF4", 0, cb, "file.edit")
        mb.add("&Files/Create + Edit &File\tShift+F4", 0, cb, "file.edit_new")
        mb.add("&Files/Re&name\tF2", 0, cb, "file.rename")
        mb.add("&Files/&Properties\tAlt+Enter", 0, cb, "file.props")
        mb.add("&Files/Calculate &Occupied Space\tCtrl+L", 0, cb,
               "pane.dirsize")
        mb.add("&Files/&Bookmark Current Dir...", 0, cb, "bookmarks.add",
               fltk.FL_MENU_DIVIDER)
        mb.add("&Files/&Quit\tAlt+F4", 0, cb, "app.quit")
        mb.add("&Mark/Select &All\tCtrl+A", 0, cb, "sel.all")
        mb.add("&Mark/&Unselect All\tCtrl+Shift+A", 0, cb, "sel.none")
        mb.add("&Mark/&Invert Selection\tNum *", 0, cb, "sel.invert",
               fltk.FL_MENU_DIVIDER)
        mb.add("&Mark/Select &Group...\tNum +", 0, cb, "sel.glob_add")
        mb.add("&Mark/Unselect Grou&p...\tNum -", 0, cb, "sel.glob_sub")
        mb.add("&Commands/&Search Files...\tAlt+F7", 0, cb, "cmd.search", inactive)
        mb.add("&Commands/Open &Terminal", 0, cb, "cmd.terminal", inactive)
        mb.add("&Net/&SSH\\/SFTP Connect...\tCtrl+N", 0, cb, "net.connect")
        mb.add("&Net/&Disconnect", 0, cb, "net.disconnect")
        mb.add("&Show/Sort by &Name\tCtrl+F3", 0, cb, "sort.name")
        mb.add("&Show/Sort by &Extension\tCtrl+F4", 0, cb, "sort.ext")
        mb.add("&Show/Sort by &Date\tCtrl+F5", 0, cb, "sort.date")
        mb.add("&Show/Sort by &Size\tCtrl+F6", 0, cb, "sort.size",
               fltk.FL_MENU_DIVIDER)
        mb.add("&Show/&Refresh\tCtrl+R", 0, cb, "pane.refresh")
        mb.add("&Show/S&wap Panes\tCtrl+U", 0, cb, "pane.swap",
               fltk.FL_MENU_DIVIDER)
        mb.add("&Show/&List View", 0, cb, "pane.list")
        mb.add("&Show/&Thumbnail View\tCtrl+Shift+F1", 0, cb, "pane.thumbs")
        mb.add("&Show/&Quick View Panel\tCtrl+Q", 0, cb, "pane.quickview")
        mb.add("&Show/&Locations Toolbar", 0, cb, "toolbar.toggle")
        mb.add("&Show/Navigation &Buttons", 0, cb, "toolbar.nav_toggle")
        mb.add("&Show/&Command Line", 0, cb, "cmdline.toggle",
               fltk.FL_MENU_DIVIDER)
        from .panes.thumbs import TILE_SIZES
        for ts in TILE_SIZES:
            mb.add(f"&Show/Thumbnail Si&ze/{ts} px", 0, cb, f"thumbs.size:{ts}")
        for z, lbl in (("fit", "&Fit"), ("fitw", "Fit &Width"),
                       ("100", "&100%")):
            mb.add(f"&Show/Preview &Zoom/{lbl}", 0, cb, f"preview.zoom:{z}")
        mb.add("C&onfiguration/&Options...", 0, cb, "cfg.options", inactive)
        mb.add("C&onfiguration/Change &Editor Command...", 0, cb, "cfg.editor")
        mb.add("C&onfiguration/&Folder Shortcuts...", 0, cb,
               "bookmarks.configure")
        mb.add("&Help/&About flcmd", 0, cb, "help.about")

    def _menu_cb(self, wid, action):
        if action == "help.about":
            fltk.fl_message("flcmd 0.1\nDual-pane file manager (pyFLTK)\n"
                            "Total Commander style keybindings")
            return
        self.dispatch(action, self.active())

    def _start_path(self, vfs, override, side) -> str:
        p = override or self.cfg.get(side, {}).get("path")
        if p and vfs.is_dir(paths.canon(p)):
            return paths.canon(p)
        return paths.canon(os.path.expanduser("~"))

    # -- helpers -----------------------------------------------------------
    def active(self) -> FilePane:
        return self._active

    def set_active_pane(self, pane: FilePane):
        if pane.mode == "preview":
            return  # quick-view panel never becomes active
        if self._active is not pane:
            self._active = pane
        pane.set_active(True)
        self.other(pane).set_active(False)
        self.cmdline.set_prompt(pane.vfs.display(pane.path))

    def _path_changed(self, pane):
        if pane is self._active:
            self.cmdline.set_prompt(pane.vfs.display(pane.path))

    def _focus_active_pane(self):
        self.active().active_view().take_focus()

    def other(self, pane: FilePane) -> FilePane:
        return self.right if pane is self.left else self.left

    def _fkey_cb(self, wid, action):
        self.dispatch(action, self.active())

    def _watch_tick(self, data=None):
        if not self._watching:
            return
        self.left.maybe_refresh()
        self.right.maybe_refresh()
        fltk.Fl.repeat_timeout(1.0, self._watch_tick)

    def _win_cb(self, wid):
        # ignore Esc; close button / Alt+F4 quit
        if fltk.Fl.event() == fltk.FL_SHORTCUT and fltk.Fl.event_key() == fltk.FL_Escape:
            return
        self.quit()

    # -- actions -----------------------------------------------------------
    def dispatch(self, action: str, pane: FilePane) -> bool:
        if action.startswith("thumbs.size:"):
            ts = int(action.split(":")[1])
            config.update("thumbs", {"size": ts})
            for p in (self.left, self.right):
                if p.thumbs:
                    p.thumbs.set_tile(ts)
            return True
        if action.startswith("preview.zoom:"):
            z = action.split(":")[1]
            config.update("preview", {"zoom": z})
            for p in (self.left, self.right):
                if p.preview:
                    p.preview.set_zoom(z)
            return True
        if action.startswith("bookmark.go:"):
            self._go_location(pane, action[len("bookmark.go:"):])
            return True
        m = getattr(self, "_act_" + action.replace(".", "_"), None)
        if m:
            m(pane)
            return True
        if action in NOT_YET:
            pane.flash(f"{action}: not implemented yet ({NOT_YET[action]})")
            return True
        return False

    def _act_pane_switch(self, pane):
        other = self.other(pane)
        if other.mode == "preview":
            return  # quick-view panel is not focusable (TC behavior)
        other.active_view().take_focus()
        self.left.redraw_view()
        self.right.redraw_view()

    def _act_pane_swap(self, pane):
        lp, rp = self.left.path, self.right.path
        self.left.set_path(rp)
        self.right.set_path(lp)

    def _act_pane_refresh(self, pane):
        pane.refresh()

    def _act_nav_open(self, pane):
        from .vfs.archive import is_archive
        e = pane.current()
        if not e:
            return
        if e.name == "..":
            self._act_nav_up(pane)
        elif e.is_dir:
            pane.set_path(paths.join(pane.path, e.name))
        elif is_archive(e.name):
            pane.enter_archive(e.name)
        else:
            pane.flash("no association configured (use F3/F4)")

    def _act_nav_open_archive(self, pane):
        e = pane.current()
        if e and not e.is_dir:
            pane.enter_archive(e.name)

    def _act_nav_up(self, pane):
        if paths.is_root(pane.path):
            pane.pop_vfs()  # leave archive/remote back to where it lives
            return
        child = paths.basename(pane.path)
        pane.set_path(paths.parent(pane.path), cursor_name=child)

    def _open_other(self, pane):
        e = pane.current()
        tgt = self.other(pane)
        if e and e.is_dir and e.name != "..":
            tgt.set_path(paths.join(pane.path, e.name))
        else:
            tgt.set_path(pane.path)

    _act_nav_cursor_to_left = _open_other
    _act_nav_cursor_to_right = _open_other

    def _act_sel_toggle(self, pane):
        pane.toggle_select(advance=True)

    def _act_sel_all(self, pane):
        pane.select_all(True)

    def _act_sel_none(self, pane):
        pane.select_all(False)

    def _act_sel_glob_add(self, pane):
        pat = fltk.fl_input("Select files:", "*")
        if pat:
            pane.select_glob(pat, add=True)

    def _act_sel_glob_sub(self, pane):
        pat = fltk.fl_input("Unselect files:", "*")
        if pat:
            pane.select_glob(pat, add=False)

    def _act_sel_invert(self, pane):
        pane.invert_selection()

    def _act_sort_name(self, pane): pane.sort("name")
    def _act_sort_ext(self, pane): pane.sort("ext")
    def _act_sort_size(self, pane): pane.sort("size")
    def _act_sort_date(self, pane): pane.sort("date")

    # -- file operations (stage 2) -------------------------------------------
    def _sources(self, pane) -> list[str]:
        """Selected names in view order, else the cursor item."""
        names = [e.name for e in pane.view if e.name in pane.selected]
        if not names:
            e = pane.current()
            if not e or e.name == "..":
                return []
            names = [e.name]
        return names

    @staticmethod
    def _ensure_dir(vfs, d: str) -> None:
        if vfs.is_dir(d):
            return
        parent = paths.parent(d)
        if parent != d:
            App._ensure_dir(vfs, parent)
        vfs.mkdir(d)

    def _copy_move(self, pane, move: bool, same_dir: bool = False):
        names = self._sources(pane)
        if not names:
            return
        other = self.other(pane)
        verb = "Move" if move else "Copy"
        what = f'"{names[0]}"' if len(names) == 1 else f"{len(names)} items"
        # TC-style prefill: destination dir + source name (or *.*);
        # bare name for the same-folder copy (Shift+F5)
        tail = names[0] if len(names) == 1 else "*.*"
        prefill = tail if same_dir else paths.join(other.path, tail)
        dst, follow = dialogs.ask_dest(verb, f"{verb} {what} to:", prefill,
                                       "Follow symlinks (copy link targets)")
        if not dst or not dst.strip():
            return
        dst = dst.strip().replace("\\", "/")
        # a relative destination resolves against the SOURCE pane
        if dst.startswith("/") or re.match(r"^[A-Za-z]:", dst):
            dvfs, dst = other.vfs, paths.canon(dst)
        else:
            dvfs, dst = pane.vfs, paths.join(pane.path, dst)
        rename = None
        base = paths.basename(dst)
        if base in ("*.*", "*"):
            dst = paths.parent(dst)
        elif len(names) == 1 and not dvfs.is_dir(dst):
            rename = base            # copy/move under a new name (TC)
            dst = paths.parent(dst)
        if not dvfs.is_dir(dst):
            if not dialogs.confirm(verb, f"Create directory?\n{dst}",
                                   yes="Create"):
                return
            try:
                self._ensure_dir(dvfs, dst)
            except OSError as e:
                pane.flash(f"mkdir: {e}")
                return
        items = [paths.join(pane.path, n) for n in names]
        ctl = ops.OpControl()
        ok = progress.run_operation(
            verb, f"{verb} {what} -> {dst}", ctl,
            lambda: ops.copy_op(pane.vfs, items, dvfs, dst, ctl,
                                move=move, follow_symlinks=follow,
                                rename=rename))
        pane.refresh()
        other.refresh()
        pane.flash("cancelled" if ctl.error == "cancelled"
                   else f"{verb.lower()}: done" if ok else "failed")

    def _act_file_copy(self, pane):
        self._copy_move(pane, move=False)

    def _act_file_copy_same(self, pane):
        self._copy_move(pane, move=False, same_dir=True)

    def _act_file_move(self, pane):
        self._copy_move(pane, move=True)

    def _act_file_mkdir(self, pane):
        name = dialogs.ask_text("New directory", "Create directory:")
        if not name:
            return
        try:
            self._ensure_dir(pane.vfs, paths.join(pane.path, name))
        except OSError as e:
            pane.flash(f"mkdir: {e}")
            return
        pane.refresh(keep_cursor_name=name.strip("/").split("/")[0])
        self.other(pane).refresh()

    def _act_file_delete(self, pane):
        names = self._sources(pane)
        if not names:
            return
        shown = "\n".join(names[:8]) + ("\n..." if len(names) > 8 else "")
        if not dialogs.confirm("Delete",
                               f"Delete {len(names)} item(s)?\n{shown}",
                               yes="Delete"):
            return
        items = [paths.join(pane.path, n) for n in names]
        ctl = ops.OpControl()
        progress.run_operation("Delete", f"Delete {len(names)} item(s)", ctl,
                               lambda: ops.delete_op(pane.vfs, items, ctl))
        pane.refresh()
        other = self.other(pane)
        if other.path == pane.path:
            other.refresh()

    def _act_file_rename(self, pane):
        pane.start_rename()

    def _act_file_props(self, pane):
        e = pane.current()
        if not e or e.name == "..":
            return
        try:
            st = pane.vfs.stat(paths.join(pane.path, e.name))
        except OSError as ex:
            pane.flash(str(ex))
            return
        kind = "link" if st.is_link else "directory" if st.is_dir else "file"
        target = ""
        if st.is_link:
            try:
                target = f"\ntarget: {pane.vfs.readlink(paths.join(pane.path, e.name))}"
            except OSError:
                pass
        size = pane.dir_sizes.get(e.name, st.size) if st.is_dir else st.size
        mtime = datetime.fromtimestamp(st.mtime).strftime("%Y-%m-%d %H:%M:%S")
        dialogs.ask_buttons(
            "Properties",
            f"{e.name}\ntype: {kind}{target}\nsize: {size:,} bytes\n"
            f"modified: {mtime}\nmode: {st_mod.filemode(st.mode)}",
            ["OK"])

    def _act_pane_dirsize(self, pane):
        names = self._sources(pane)
        if not names:
            return
        total = pane.calc_sizes(names)
        dialogs.ask_buttons(
            "Occupied space",
            f"{total:,} bytes in {len(names)} item(s)", ["OK"])

    def _act_sel_toggle_space(self, pane):
        pane.toggle_select(advance=False, du=True)

    def _materialize(self, pane, name: str) -> str | None:
        """Local path for a pane entry; non-local VFS entries are pulled to
        a temp file (viewer/preview need a real file)."""
        p = paths.join(pane.path, name)
        if pane.vfs.scheme == "file":
            return p
        import tempfile
        try:
            with pane.vfs.open(p) as src:
                fd, tmp = tempfile.mkstemp(suffix="_" + name)
                with os.fdopen(fd, "wb") as dst:
                    while chunk := src.read(1 << 20):
                        dst.write(chunk)
            return paths.canon(tmp)
        except OSError as e:
            pane.flash(f"read: {e}")
            return None

    def _act_file_view(self, pane):
        e = pane.current()
        if not e:
            return
        if e.is_link:
            p = paths.join(pane.path, e.name)
            try:
                tgt = pane.vfs.readlink(p)
            except OSError as ex:
                pane.flash(f"readlink: {ex}")
                return
            if e.is_dir:  # dir symlink: F3 reports the target
                pane.flash(f"{e.name} -> {tgt}")
                return
            try:
                pane.vfs.stat_follow(p)
            except OSError:  # dangling link: nothing to view
                pane.flash(f"broken link: {e.name} -> {tgt}")
                return
            # file symlink: fall through and view the target's content
        if e.is_dir:
            return
        p = self._materialize(pane, e.name)
        if not p:
            return
        self._viewers = [v for v in self._viewers if v.visible()]
        self._viewers.append(viewer.view_file(p))

    def _act_file_edit(self, pane):
        e = pane.current()
        if not e or e.is_dir:
            return
        if pane.vfs.scheme != "file":
            pane.flash("edit: local files only")
            return
        if viewer.edit_file(self.cfg, paths.join(pane.path, e.name),
                            pane.flash):
            pane.flash(f"editing {e.name}")

    def _act_file_edit_new(self, pane):
        name = dialogs.ask_text("New file", "Create and edit file:")
        if not name:
            return
        p = paths.join(pane.path, name)
        if not pane.vfs.exists(p):
            try:
                with pane.vfs.open(p, "wb"):
                    pass
            except OSError as ex:
                pane.flash(f"create: {ex}")
                return
            pane.refresh(keep_cursor_name=name)
        viewer.edit_file(self.cfg, p, pane.flash)

    def _act_pane_activate(self, pane):
        self.set_active_pane(pane)

    def _act_bookmarks_add(self, pane):
        self._bookmark_add_current(pane)

    def _relayout(self):
        from .ui.cmdline import CMD_H
        from .ui.toolbar import TOOLBAR_H
        w, h = self.win.w(), self.win.h()
        top = self._top0 + MENU_H + (TOOLBAR_H if self.show_toolbar else 0)
        cmd_h = CMD_H if self.show_cmdline else 0
        self.toolbar.show() if self.show_toolbar else self.toolbar.hide()
        self.cmdline.show() if self.show_cmdline else self.cmdline.hide()
        self.tile.resize(0, top, w, h - top - FKEY_H - cmd_h)
        self.cmdline.resize(0, h - FKEY_H - cmd_h, w, CMD_H)
        self.win.redraw()

    def _act_toolbar_toggle(self, pane):
        self.show_toolbar = not self.show_toolbar
        self.cfg.setdefault("toolbar", {})["show"] = self.show_toolbar
        config.update("toolbar", {"show": self.show_toolbar})
        self._relayout()

    def _act_toolbar_nav_toggle(self, pane):
        show = not bool(config.load().get("toolbar", {}).get("nav", True))
        self.cfg.setdefault("toolbar", {})["nav"] = show
        config.update("toolbar", {"nav": show})
        self.toolbar.rebuild()

    def _act_cmdline_toggle(self, pane):
        self.show_cmdline = not self.show_cmdline
        self.cfg.setdefault("cmdline", {})["show"] = self.show_cmdline
        config.update("cmdline", {"show": self.show_cmdline})
        self._relayout()

    # -- command line ----------------------------------------------------------
    def _run_command(self, text: str):
        pane = self.active()
        if text == "cd" or text.startswith("cd "):
            self._cmd_cd(pane, text[2:].strip())
            return
        import subprocess
        cwd = paths.to_native(pane.path) if pane.vfs.scheme == "file" \
            else os.path.expanduser("~")
        try:
            subprocess.Popen(text, shell=True, cwd=cwd,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError as e:
            pane.flash(f"exec: {e}")
            return
        pane.flash(f"started: {text}")

    def _cmd_cd(self, pane, arg: str):
        import posixpath
        if not arg:
            tgt = paths.canon(os.path.expanduser("~")) \
                if pane.vfs.scheme == "file" else "/"
        else:
            if pane.vfs.scheme == "file":
                arg = os.path.expandvars(os.path.expanduser(arg))
            arg = paths.canon(arg)
            absolute = arg.startswith("/") or paths.is_root(arg) \
                or (len(arg) > 1 and arg[1] == ":")
            tgt = arg if absolute else paths.join(pane.path, arg)
            tgt = paths.canon(posixpath.normpath(tgt))  # resolve . and ..
        if pane.vfs.is_dir(tgt):
            pane.set_path(tgt)
        else:
            pane.flash(f"cd: no such directory: {tgt}")

    # -- bookmarks (folder shortcuts menu) + locations toolbar -----------------
    def _go_location(self, pane, location: str, record: bool = True):
        """chdir the pane to a bookmarked location (local path or sftp URL).
        History is recorded once up front; internal steps never record."""
        from .ssh import SSHSession
        from .vfs.sftp import SftpVFS
        if record:
            pane.record_hist()
        if location.startswith("sftp://"):
            rest = location[len("sftp://"):]
            host, _, p = rest.partition("/")
            rpath = "/" + p
            # reuse an existing sftp session on this pane to the same host
            if (pane.vfs.scheme == "sftp"
                    and pane.vfs.session.label == host):
                pane.set_path(rpath, record=False)
                return
            try:
                sess = SSHSession(host)
            except Exception as e:
                pane.flash(f"connect {host}: {e}")
                return
            while pane.vfs.scheme == "sftp":
                pane.pop_vfs(record=False)
            pane.push_vfs(SftpVFS(sess), rpath if p else sess.home,
                          record=False)
        else:
            while pane.vfs.scheme != "file":
                pane.pop_vfs(record=False)
            if pane.vfs.is_dir(location):
                pane.set_path(location, record=False)
            else:
                pane.flash(f"no such directory: {location}")

    def _act_nav_back(self, pane):
        if not pane.hist_back:
            pane.flash("history: nothing to go back to")
            return
        cur = pane.location()
        loc = pane.hist_back.pop()
        if cur:
            pane.hist_fwd.append(cur)
        self._go_location(pane, loc, record=False)

    def _act_nav_fwd(self, pane):
        if not pane.hist_fwd:
            pane.flash("history: nothing to go forward to")
            return
        cur = pane.location()
        loc = pane.hist_fwd.pop()
        if cur:
            pane.hist_back.append(cur)
        self._go_location(pane, loc, record=False)

    def _act_bookmarks_menu(self, pane):
        """Folder-shortcuts popup (double-click on the panel header)."""
        from . import bookmarks
        from .ui import esc, menus
        self.set_active_pane(pane)
        data = bookmarks.load()

        def build(mb, pick):
            def add_nodes(nodes, prefix):
                for node in nodes:
                    title = esc(node.get("title", "?")).replace("/", "\\/")
                    if "items" in node:
                        add_nodes(node["items"], prefix + title + "/")
                    else:
                        mb.add(prefix + title, 0, pick,
                               "go:" + node.get("path", ""))

            add_nodes(data["bookmarks"], "")
            mb.add("+ Add current dir", 0, pick, "add", fltk.FL_MENU_DIVIDER)
            mb.add("* Configure...", 0, pick, "configure")

        token = menus.popup(build)
        if token == "add":
            self._bookmark_add_current(pane)
        elif token == "configure":
            self._bookmark_configure(pane)
        elif isinstance(token, str) and token.startswith("go:"):
            self._go_location(pane, token[3:])

    def _bookmark_add_current(self, pane):
        from . import bookmarks
        loc = bookmarks.make_location(pane.vfs, pane.path)
        title = dialogs.ask_text("Add bookmark", "Menu title:",
                                 bookmarks.short_title(loc))
        if not title:
            return
        data = bookmarks.load()
        bookmarks.add_bookmark(data, title, loc)
        bookmarks.save(data)
        pane.flash(f"bookmarked: {title}")

    def _bookmark_configure(self, pane):
        from .ui.bmedit import edit_bookmarks
        if edit_bookmarks():
            pane.flash("bookmarks saved")

    def _act_bookmarks_configure(self, pane):
        self._bookmark_configure(pane)

    # -- view modes (thumbnails / quick view) ----------------------------------
    def _act_pane_list(self, pane):
        pane.set_mode("list")

    def _act_pane_thumbs(self, pane):
        pane.set_mode("thumbs" if pane.mode != "thumbs" else "list")

    def _act_pane_quickview(self, pane):
        other = self.other(pane)
        if other.mode == "preview":
            other.set_mode(getattr(other, "_premode", "list"))
        else:
            other._premode = other.mode
            other.set_mode("preview")
            self._update_preview(pane)

    def _cursor_moved(self, pane):
        if self.other(pane).mode == "preview" and pane.mode != "preview":
            self._pv_src = pane
            fltk.Fl.remove_timeout(self._pv_tick)
            fltk.Fl.add_timeout(0.08, self._pv_tick)  # debounce fast cursoring

    def _pv_tick(self, data=None):
        src = getattr(self, "_pv_src", None)
        if src:
            self._update_preview(src)

    def _update_preview(self, src):
        other = self.other(src)
        if other.mode != "preview" or not other.preview:
            return
        e = src.current()
        if not e or e.name == "..":
            other.preview.show_file(None, e)
            return
        if src.vfs.scheme == "file":
            other.preview.show_file(paths.join(src.path, e.name), e)
        else:
            other.preview.show_file(None, e)

    def _act_net_connect(self, pane):
        import paramiko
        from .ssh import SSHSession
        from .vfs.sftp import SftpVFS
        last = self.cfg.get("ssh", {}).get("last_host", "")
        target = dialogs.ask_text("SSH/SFTP Connect",
                                  "Host (ssh alias or [user@]host[:port]):",
                                  last)
        if not target:
            return
        password = None
        for _ in range(3):  # pubkey/agent first, then password retries
            try:
                self.win.cursor(fltk.FL_CURSOR_WAIT)
                fltk.Fl.check()
                sess = SSHSession(target, password=password)
                break
            except paramiko.AuthenticationException:
                password = dialogs.ask_text("Authentication",
                                            f"Password for {target}:",
                                            secret=True)
                if not password:
                    return
            except Exception as e:
                pane.flash(f"connect: {e}")
                return
            finally:
                self.win.cursor(fltk.FL_CURSOR_DEFAULT)
        else:
            pane.flash("connect: authentication failed")
            return
        self.cfg.setdefault("ssh", {})["last_host"] = target
        config.update("ssh", {"last_host": target})
        pane.push_vfs(SftpVFS(sess), sess.home)

    def _act_net_disconnect(self, pane):
        while pane.vfs.scheme == "sftp":
            if not pane.pop_vfs():
                break

    def _act_cfg_editor(self, pane):
        cur = self.cfg.get("editor", {}).get("command", "")
        cmd = dialogs.ask_text("Configure editor",
                               "Editor command (e.g. 'gedit' or 'code -w'):",
                               cur)
        if cmd is not None:
            self.cfg.setdefault("editor", {})["command"] = cmd
            config.update("editor", {"command": cmd})

    def _act_app_quit(self, pane):
        self.quit()

    # -- lifecycle -----------------------------------------------------------
    def show(self):
        self.win.show()
        self.left.table.take_focus()

    def quit(self):
        self._watching = False
        self.cfg["window"] = {"w": self.win.w(), "h": self.win.h()}
        for side in ("left", "right"):
            p = getattr(self, side)
            self.cfg[side] = {"path": p.path, "sort": p.sort_key, "rev": p.sort_rev}
        try:
            config.save(self.cfg)
        except OSError:
            pass
        while fltk.Fl.first_window():
            fltk.Fl.first_window().hide()


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    from .ui import theme
    theme.apply_scheme()
    app = App(*(argv + [None, None])[:2])
    app.show()
    return fltk.Fl.run()
