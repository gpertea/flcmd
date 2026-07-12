"""Main application: dual panes, function-key bar, action dispatch."""

import os
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


class App:
    def __init__(self, left_path: str | None = None, right_path: str | None = None):
        self.cfg = config.load()
        w = int(self.cfg.get("window", {}).get("w", 1000))
        h = int(self.cfg.get("window", {}).get("h", 640))
        self.keymap = Keymap(self.cfg.get("keys"))
        self._viewers: list = []

        from .ui.toolbar import LocationsToolbar, TOOLBAR_H
        self.win = fltk.Fl_Double_Window(w, h, "flcmd")
        self.menubar = fltk.Fl_Menu_Bar(0, 0, w, MENU_H)
        self.menubar.box(fltk.FL_THIN_UP_BOX)
        self._build_menu()
        self.show_toolbar = bool(self.cfg.get("toolbar", {}).get("show", True))
        tb_h = TOOLBAR_H if self.show_toolbar else 0
        self.toolbar = LocationsToolbar(
            0, MENU_H, w, TOOLBAR_H,
            lambda loc: self._go_location(self.active(), loc), self.win)
        if not self.show_toolbar:
            self.toolbar.hide()
        top = MENU_H + tb_h
        ph = h - top - FKEY_H
        self.tile = fltk.Fl_Tile(0, top, w, ph)
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

        bar = fltk.Fl_Group(0, h - FKEY_H, w, FKEY_H)
        bw = w // len(FKEYS)
        for i, (label, action) in enumerate(FKEYS):
            b = fltk.Fl_Button(i * bw, h - FKEY_H,
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
        mb.add("&Show/&Locations Toolbar", 0, cb, "toolbar.toggle",
               fltk.FL_MENU_DIVIDER)
        from .panes.thumbs import TILE_SIZES
        for ts in TILE_SIZES:
            mb.add(f"&Show/Thumbnail Si&ze/{ts} px", 0, cb, f"thumbs.size:{ts}")
        for z, lbl in (("fit", "&Fit"), ("fitw", "Fit &Width"),
                       ("100", "&100%")):
            mb.add(f"&Show/Preview &Zoom/{lbl}", 0, cb, f"preview.zoom:{z}")
        mb.add("C&onfiguration/&Options...", 0, cb, "cfg.options", inactive)
        mb.add("C&onfiguration/Change &Editor Command...", 0, cb, "cfg.editor")
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

    def _copy_move(self, pane, move: bool):
        names = self._sources(pane)
        if not names:
            return
        other = self.other(pane)
        verb = "Move" if move else "Copy"
        what = names[0] if len(names) == 1 else f"{len(names)} items"
        dst, follow = dialogs.ask_dest(verb, f"{verb} {what} to:", other.path,
                                       "Follow symlinks (copy link targets)")
        if not dst:
            return
        dst = paths.canon(dst)
        if not other.vfs.is_dir(dst):
            if not dialogs.confirm(verb, f"Create directory?\n{dst}",
                                   yes="Create"):
                return
            try:
                self._ensure_dir(other.vfs, dst)
            except OSError as e:
                pane.flash(f"mkdir: {e}")
                return
        items = [paths.join(pane.path, n) for n in names]
        ctl = ops.OpControl()
        ok = progress.run_operation(
            verb, f"{verb} {what} -> {dst}", ctl,
            lambda: ops.copy_op(pane.vfs, items, other.vfs, dst, ctl,
                                move=move, follow_symlinks=follow))
        pane.refresh()
        other.refresh()
        pane.flash("cancelled" if ctl.error == "cancelled"
                   else f"{verb.lower()}: done" if ok else "failed")

    def _act_file_copy(self, pane):
        self._copy_move(pane, move=False)

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
        size = pane.dir_sizes.get(e.name, st.size) if st.is_dir else st.size
        mtime = datetime.fromtimestamp(st.mtime).strftime("%Y-%m-%d %H:%M:%S")
        dialogs.ask_buttons(
            "Properties",
            f"{e.name}\ntype: {kind}\nsize: {size:,} bytes\n"
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
        if not e or e.is_dir:
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

    def _act_toolbar_toggle(self, pane):
        from .ui.toolbar import TOOLBAR_H
        self.show_toolbar = not self.show_toolbar
        config.update("toolbar", {"show": self.show_toolbar})
        top = MENU_H + (TOOLBAR_H if self.show_toolbar else 0)
        if self.show_toolbar:
            self.toolbar.show()
        else:
            self.toolbar.hide()
        self.tile.resize(0, top, self.win.w(), self.win.h() - top - FKEY_H)
        self.win.redraw()

    # -- bookmarks (folder shortcuts menu) + locations toolbar -----------------
    def _go_location(self, pane, location: str):
        """chdir the pane to a bookmarked location (local path or sftp URL)."""
        from .ssh import SSHSession
        from .vfs.sftp import SftpVFS
        if location.startswith("sftp://"):
            rest = location[len("sftp://"):]
            host, _, p = rest.partition("/")
            rpath = "/" + p
            # reuse an existing sftp session on this pane to the same host
            if (pane.vfs.scheme == "sftp"
                    and pane.vfs.session.label == host):
                pane.set_path(rpath)
                return
            try:
                sess = SSHSession(host)
            except Exception as e:
                pane.flash(f"connect {host}: {e}")
                return
            while pane.vfs.scheme == "sftp":
                pane.pop_vfs()
            pane.push_vfs(SftpVFS(sess), rpath if p else sess.home)
        else:
            while pane.vfs.scheme != "file":
                pane.pop_vfs()
            if pane.vfs.is_dir(location):
                pane.set_path(location)
            else:
                pane.flash(f"no such directory: {location}")

    def _act_bookmarks_menu(self, pane):
        """Folder-shortcuts popup (double-click on the panel header)."""
        from . import bookmarks
        from .ui import esc
        self.set_active_pane(pane)
        data = bookmarks.load()
        result: list = [None]

        def pick(wid, token):
            result[0] = token

        mb = fltk.Fl_Menu_Button(fltk.Fl.event_x_root(),
                                 fltk.Fl.event_y_root(), 0, 0)
        mb.type(fltk.Fl_Menu_Button.POPUP3)

        def add_nodes(nodes, prefix):
            for node in nodes:
                title = esc(node.get("title", "?")).replace("/", "\\/")
                if "items" in node:
                    add_nodes(node["items"], prefix + title + "/")
                else:
                    mb.add(prefix + title, 0, pick, "go:" + node.get("path", ""))

        add_nodes(data["bookmarks"], "")
        mb.add("+ Add current dir", 0, pick, "add", fltk.FL_MENU_DIVIDER)
        mb.add("* Configure...", 0, pick, "configure")
        mb.popup()
        token = result[0]
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
        from . import bookmarks
        pane.flash(f"bookmarks file: {bookmarks._store_path()}")

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
    fltk.Fl.scheme("gtk+")
    app = App(*(argv + [None, None])[:2])
    app.show()
    return fltk.Fl.run()
