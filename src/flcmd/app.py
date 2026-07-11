"""Main application: dual panes, function-key bar, action dispatch."""

import os
import sys

import fltk

from . import config, paths, viewer
from .keymap import Keymap
from .panes import FilePane
from .vfs import LocalVFS

FKEY_H = 26
FKEYS = [
    ("F3 View", "file.view"), ("F4 Edit", "file.edit"),
    ("F5 Copy", "file.copy"), ("F6 Move", "file.move"),
    ("F7 MkDir", "file.mkdir"), ("F8 Delete", "file.delete"),
    ("Alt+F4 Exit", "app.quit"),
]
NOT_YET = {
    "file.edit": "stage 3", "file.copy": "stage 2", "file.move": "stage 2",
    "file.mkdir": "stage 2", "file.delete": "stage 2",
}


class App:
    def __init__(self, left_path: str | None = None, right_path: str | None = None):
        self.cfg = config.load()
        w = int(self.cfg.get("window", {}).get("w", 1000))
        h = int(self.cfg.get("window", {}).get("h", 640))
        self.keymap = Keymap(self.cfg.get("keys"))
        self._viewers: list = []

        self.win = fltk.Fl_Double_Window(w, h, "flcmd")
        self.tile = fltk.Fl_Tile(0, 0, w, h - FKEY_H)
        vfs = LocalVFS()
        lp = self._start_path(vfs, left_path, "left")
        rp = self._start_path(vfs, right_path, "right")
        self.left = FilePane(0, 0, w // 2, h - FKEY_H, vfs, lp, self.dispatch, self.keymap)
        self.right = FilePane(w // 2, 0, w - w // 2, h - FKEY_H, vfs, rp, self.dispatch, self.keymap)
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

    def _start_path(self, vfs, override, side) -> str:
        p = override or self.cfg.get(side, {}).get("path")
        if p and vfs.is_dir(paths.canon(p)):
            return paths.canon(p)
        return paths.canon(os.path.expanduser("~"))

    # -- helpers -----------------------------------------------------------
    def active(self) -> FilePane:
        f = fltk.Fl.focus()
        return self.right if f is self.right.table else self.left

    def other(self, pane: FilePane) -> FilePane:
        return self.right if pane is self.left else self.left

    def _fkey_cb(self, wid, action):
        self.dispatch(action, self.active())

    def _win_cb(self, wid):
        # ignore Esc; close button / Alt+F4 quit
        if fltk.Fl.event() == fltk.FL_SHORTCUT and fltk.Fl.event_key() == fltk.FL_Escape:
            return
        self.quit()

    # -- actions -----------------------------------------------------------
    def dispatch(self, action: str, pane: FilePane) -> bool:
        m = getattr(self, "_act_" + action.replace(".", "_"), None)
        if m:
            m(pane)
            return True
        if action in NOT_YET:
            pane.flash(f"{action}: not implemented yet ({NOT_YET[action]})")
            return True
        return False

    def _act_pane_switch(self, pane):
        self.other(pane).table.take_focus()
        self.left.table.redraw()
        self.right.table.redraw()

    def _act_pane_swap(self, pane):
        lp, rp = self.left.path, self.right.path
        self.left.set_path(rp)
        self.right.set_path(lp)

    def _act_pane_refresh(self, pane):
        pane.refresh()

    def _act_nav_open(self, pane):
        e = pane.current()
        if not e:
            return
        if e.name == "..":
            self._act_nav_up(pane)
        elif e.is_dir:
            pane.set_path(paths.join(pane.path, e.name))
        else:
            pane.flash("run/open file: stage 2")

    def _act_nav_up(self, pane):
        if paths.is_root(pane.path):
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

    def _act_sel_toggle_space(self, pane):
        pane.toggle_select(advance=False)

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

    def _act_file_view(self, pane):
        e = pane.current()
        if not e or e.is_dir:
            return
        self._viewers = [v for v in self._viewers if v.visible()]
        self._viewers.append(viewer.view_file(paths.join(pane.path, e.name)))

    def _act_app_quit(self, pane):
        self.quit()

    # -- lifecycle -----------------------------------------------------------
    def show(self):
        self.win.show()
        self.left.table.take_focus()

    def quit(self):
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
