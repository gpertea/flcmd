"""File pane: path header + file table + selection footer.
All keys resolve through the app keymap via the dispatch callable."""

import time
from datetime import datetime
from fnmatch import fnmatch

import fltk

from .. import paths
from ..vfs import DirEntry, VFS

_T = fltk.Fl_Table

HDR_H = 22
FOOT_H = 20
ROW_H = 18
COL_EXT, COL_SIZE, COL_DATE = 44, 84, 104

_UP = DirEntry(name="..", is_dir=True)


def fmt_size(e: DirEntry) -> str:
    if e.name == "..":
        return "<UP>"
    if e.is_dir:
        return "<DIR>"
    return f"{e.size:,}"


def fmt_date(e: DirEntry) -> str:
    if not e.mtime:
        return ""
    return datetime.fromtimestamp(e.mtime).strftime("%Y-%m-%d %H:%M")


class FileTable(fltk.Fl_Table_Row):
    def __init__(self, x, y, w, h, pane):
        super().__init__(x, y, w, h)
        self.pane = pane
        self.type(fltk.Fl_Table_Row.SELECT_NONE)
        self.cols(4)
        self.col_header(1)
        self.col_resize(1)
        self.row_header(0)
        self.row_height_all(ROW_H)
        self.callback(self._on_click)
        self.end()

    def inner_w(self) -> int:
        sb = self.scrollbar_size() or fltk.Fl.scrollbar_size()
        return self.w() - sb - 4

    def vis_rows(self) -> int:
        return max(1, (self.h() - HDR_H - 4) // ROW_H)

    def _autosize_cols(self):
        name_w = max(80, self.inner_w() - COL_EXT - COL_SIZE - COL_DATE)
        for i, cw in enumerate((name_w, COL_EXT, COL_SIZE, COL_DATE)):
            self.col_width(i, cw)

    def resize(self, x, y, w, h):
        super().resize(x, y, w, h)
        self._autosize_cols()

    def _on_click(self, wid):
        if self.callback_context() != _T.CONTEXT_CELL:
            return
        self.take_focus()
        row = self.callback_row()
        if 0 <= row < len(self.pane.view):
            self.pane.set_cursor(row)
            if fltk.Fl.event_clicks():
                self.pane.dispatch("nav.open", self.pane)

    def handle(self, event):
        if event in (fltk.FL_FOCUS, fltk.FL_UNFOCUS):
            self.redraw()
            return 1
        if event == fltk.FL_KEYDOWN:
            if self.pane.on_key():
                return 1
            return super().handle(event)
        return super().handle(event)

    def draw_cell(self, ctx, r=0, c=0, x=0, y=0, w=0, h=0):
        if ctx == _T.CONTEXT_STARTPAGE:
            fltk.fl_font(fltk.FL_HELVETICA, 12)
            return
        if ctx == _T.CONTEXT_COL_HEADER:
            fltk.fl_push_clip(x, y, w, h)
            fltk.fl_draw_box(fltk.FL_THIN_UP_BOX, x, y, w, h, fltk.FL_BACKGROUND_COLOR)
            fltk.fl_color(fltk.FL_BLACK)
            fltk.fl_draw(("Name", "Ext", "Size", "Date")[c], x + 4, y, w - 8, h,
                         fltk.FL_ALIGN_LEFT)
            fltk.fl_pop_clip()
            return
        if ctx != _T.CONTEXT_CELL or r >= len(self.pane.view):
            return
        e = self.pane.view[r]
        cursor = r == self.pane.cursor
        focused = fltk.Fl.focus() == self
        selected = e.name in self.pane.selected
        bg = fltk.FL_WHITE
        if cursor:
            bg = fltk.fl_rgb_color(49, 106, 197) if focused else fltk.fl_rgb_color(200, 208, 220)
        fltk.fl_push_clip(x, y, w, h)
        fltk.fl_color(bg)
        fltk.fl_rectf(x, y, w, h)
        if selected:
            fg = fltk.fl_rgb_color(255, 80, 80) if (cursor and focused) else fltk.FL_RED
        else:
            fg = fltk.FL_WHITE if (cursor and focused) else fltk.FL_BLACK
        fltk.fl_color(fg)
        if c == 0:
            nm = e.name if e.is_dir else paths.splitext(e.name)[0]
            if e.is_dir and e.name != "..":
                nm = "[" + nm + "]"
            fltk.fl_draw(nm, x + 4, y, w - 8, h, fltk.FL_ALIGN_LEFT)
        elif c == 1:
            fltk.fl_draw(e.ext, x + 2, y, w - 4, h, fltk.FL_ALIGN_LEFT)
        elif c == 2:
            fltk.fl_draw(fmt_size(e), x + 2, y, w - 6, h, fltk.FL_ALIGN_RIGHT)
        else:
            fltk.fl_draw(fmt_date(e), x + 2, y, w - 4, h, fltk.FL_ALIGN_LEFT)
        fltk.fl_pop_clip()


class FilePane(fltk.Fl_Group):
    """One pane. `dispatch(action, pane)` is provided by the app."""

    def __init__(self, x, y, w, h, vfs: VFS, path: str, dispatch, keymap):
        super().__init__(x, y, w, h)
        self.vfs = vfs
        self.path = paths.canon(path)
        self.dispatch = dispatch
        self.keymap = keymap
        self.entries: list[DirEntry] = []   # real entries, sorted
        self.view: list[DirEntry] = []      # what the table shows (.. + entries)
        self.cursor = 0
        self.selected: set[str] = set()
        self.sort_key = "name"
        self.sort_rev = False
        self._search = ""
        self._search_t = 0.0
        self.header = fltk.Fl_Box(x, y, w, HDR_H)
        self.header.box(fltk.FL_FLAT_BOX)
        self.header.align(fltk.FL_ALIGN_INSIDE | fltk.FL_ALIGN_LEFT | fltk.FL_ALIGN_CLIP)
        self.header.labelfont(fltk.FL_HELVETICA_BOLD)
        self.header.labelsize(12)
        self.table = FileTable(x, y + HDR_H, w, h - HDR_H - FOOT_H, self)
        self.footer = fltk.Fl_Box(x, y + h - FOOT_H, w, FOOT_H)
        self.footer.box(fltk.FL_THIN_DOWN_BOX)
        self.footer.align(fltk.FL_ALIGN_INSIDE | fltk.FL_ALIGN_LEFT | fltk.FL_ALIGN_CLIP)
        self.footer.labelsize(11)
        self.resizable(self.table)
        self.end()
        self.refresh()

    # -- listing ----------------------------------------------------------
    def refresh(self, keep_cursor_name: str | None = None):
        try:
            entries = self.vfs.listdir(self.path)
        except OSError as e:
            self.flash(f"error: {e}")
            return
        self.entries = entries
        self._sort()
        names = {e.name for e in self.view}
        self.selected &= names
        want = keep_cursor_name or (self.view[self.cursor].name if self.cursor < len(self.view) else None)
        self.cursor = 0
        if want:
            for i, e in enumerate(self.view):
                if e.name == want:
                    self.cursor = i
                    break
        self._sync()

    def set_path(self, path: str, cursor_name: str | None = None):
        self.path = paths.canon(path)
        self.selected.clear()
        self.cursor = 0
        self.refresh(keep_cursor_name=cursor_name)

    def _sort(self):
        keyf = {
            "name": lambda e: e.name.lower(),
            "ext": lambda e: (e.ext.lower(), e.name.lower()),
            "size": lambda e: e.size,
            "date": lambda e: e.mtime,
        }[self.sort_key]
        dirs = sorted((e for e in self.entries if e.is_dir),
                      key=lambda e: e.name.lower())
        files = sorted((e for e in self.entries if not e.is_dir),
                       key=keyf, reverse=self.sort_rev)
        self.view = ([] if paths.is_root(self.path) else [_UP]) + dirs + files

    def sort(self, key: str):
        if self.sort_key == key:
            self.sort_rev = not self.sort_rev
        else:
            self.sort_key, self.sort_rev = key, False
        cur = self.view[self.cursor].name if self.view else None
        self._sort()
        self.refresh(keep_cursor_name=cur)

    def _sync(self):
        self.table.rows(len(self.view))
        self.table._autosize_cols()
        self.header.copy_label(" " + self.vfs.display(self.path))
        self._update_footer()
        self.table.redraw()

    # -- cursor / selection ------------------------------------------------
    def current(self) -> DirEntry | None:
        return self.view[self.cursor] if 0 <= self.cursor < len(self.view) else None

    def set_cursor(self, i: int):
        self.cursor = max(0, min(i, len(self.view) - 1))
        r1 = self.table.top_row()
        vis = self.table.vis_rows()
        if self.cursor < r1:
            self.table.top_row(self.cursor)
        elif self.cursor >= r1 + vis:
            self.table.top_row(self.cursor - vis + 1)
        self.table.redraw()

    def move_cursor(self, delta=None, absolute=None):
        vis = self.table.vis_rows()
        if absolute == "home":
            self.set_cursor(0)
        elif absolute == "end":
            self.set_cursor(len(self.view) - 1)
        elif delta == "pgup":
            self.set_cursor(self.cursor - vis)
        elif delta == "pgdn":
            self.set_cursor(self.cursor + vis)
        else:
            self.set_cursor(self.cursor + delta)

    def toggle_select(self, advance=False):
        e = self.current()
        if e and e.name != "..":
            self.selected.symmetric_difference_update({e.name})
        if advance:
            self.move_cursor(delta=1)
        self._update_footer()
        self.table.redraw()

    def select_all(self, on=True):
        self.selected = {e.name for e in self.view if e.name != ".."} if on else set()
        self._update_footer()
        self.table.redraw()

    def select_glob(self, pattern: str, add=True):
        hits = {e.name for e in self.view
                if not e.is_dir and fnmatch(e.name.lower(), pattern.lower())}
        self.selected = (self.selected | hits) if add else (self.selected - hits)
        self._update_footer()
        self.table.redraw()

    def invert_selection(self):
        files = {e.name for e in self.view if not e.is_dir}
        self.selected = files - self.selected
        self._update_footer()
        self.table.redraw()

    # -- keyboard ------------------------------------------------------------
    _NAV = {
        fltk.FL_Up: {"delta": -1}, fltk.FL_Down: {"delta": 1},
        fltk.FL_Home: {"absolute": "home"}, fltk.FL_End: {"absolute": "end"},
        fltk.FL_Page_Up: {"delta": "pgup"}, fltk.FL_Page_Down: {"delta": "pgdn"},
    }

    def on_key(self) -> bool:
        key = fltk.Fl.event_key()
        state = fltk.Fl.event_state()
        mods = state & (fltk.FL_CTRL | fltk.FL_ALT | fltk.FL_META)
        action = self.keymap.action_for_event()
        if action:
            return bool(self.dispatch(action, self))
        if not mods and key in self._NAV:
            self.move_cursor(**self._NAV[key])
            return True
        txt = fltk.Fl.event_text()
        if not mods and txt and txt.isprintable() and txt != " ":
            self._quick_search(txt)
            return True
        if key == fltk.FL_Escape and self._search:
            self._search = ""
            self._update_footer()
            return True
        return False

    def _quick_search(self, txt: str):
        now = time.monotonic()
        if now - self._search_t > 1.0:
            self._search = ""
        self._search_t = now
        self._search += txt.lower()
        order = list(range(self.cursor, len(self.view))) + list(range(self.cursor))
        for i in order:
            if self.view[i].name.lower().startswith(self._search):
                self.set_cursor(i)
                break
        self._update_footer()

    # -- footer ---------------------------------------------------------------
    def _update_footer(self):
        if self._search:
            self.footer.copy_label(f" search: {self._search}")
            return
        files = [e for e in self.view if not e.is_dir]
        sel = [e for e in files if e.name in self.selected]
        seldirs = sum(1 for e in self.view if e.is_dir and e.name in self.selected)
        total, ssel = sum(e.size for e in files), sum(e.size for e in sel)
        ndirs = sum(1 for e in self.view if e.is_dir and e.name != "..")
        self.footer.copy_label(
            f" {ssel:,} / {total:,} bytes in {len(sel)+seldirs} / "
            f"{len(files)+ndirs} selected")

    def flash(self, msg: str):
        self.footer.copy_label(" " + msg)
        self.footer.redraw()
