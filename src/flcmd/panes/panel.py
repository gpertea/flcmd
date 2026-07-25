"""File pane: path header + file table + selection footer.
All keys resolve through the app keymap via the dispatch callable."""

import sys
import time
from datetime import datetime
from fnmatch import fnmatch
from stat import filemode

import fltk

from .. import dnd, paths
from ..ui import esc, theme
from ..vfs import DirEntry, LocalVFS, VFS

_T = fltk.Fl_Table

HDR_H = 22
FOOT_H = 20
ROW_H = 18
PAD = 2  # sunken frame inset of the file list
COL_EXT, COL_SIZE, COL_DATE = 44, 84, 104
COL_ATTR = 46 if sys.platform == "win32" else 78  # "rahs" vs "rwxr-xr-x"
COLS = ("name", "ext", "size", "date", "attr")
COL_TITLES = ("Name", "Ext", "Size", "Date", "Attr")

_UP = DirEntry(name="..", is_dir=True)


def _shift_down() -> bool:
    """Shift state at drop time. FLTK's win32 drop target does not update
    Fl modifiers during OLE drags, so ask the OS directly there."""
    if sys.platform == "win32":
        import ctypes
        return bool(ctypes.windll.user32.GetKeyState(0x10) & 0x8000)
    return bool(fltk.Fl.event_state() & fltk.FL_SHIFT)


# -- input handling shared by the list table and the thumbnail grid ---------
def table_click(tbl):
    ctx = tbl.callback_context()
    ev = fltk.Fl.event()
    if fltk.Fl.event_button() != fltk.FL_LEFT_MOUSE:
        return
    if ctx == _T.CONTEXT_CELL:
        idx = tbl.cell_index(tbl.callback_row(), tbl.callback_col())
        if not (0 <= idx < len(tbl.pane.view)):
            return
        if ev == fltk.FL_PUSH:
            tbl._cell_pushed = True
            tbl.take_focus()
            tbl.pane.on_mouse_push(idx)
            if fltk.Fl.event_clicks():
                tbl.pane.dispatch("nav.open", tbl.pane)
    elif ctx == _T.CONTEXT_TABLE and ev == fltk.FL_PUSH:
        # dead-space click: just focus the pane (TC keeps selection)
        tbl.take_focus()


def table_handle(tbl, event, sup) -> int:
    if event == fltk.FL_FOCUS:
        tbl.pane.dispatch("pane.activate", tbl.pane)
        return 1
    if event == fltk.FL_UNFOCUS:
        return 1  # active state is app-owned; don't dim on dialog focus-steal
    if event == fltk.FL_PUSH and fltk.Fl.event_button() == fltk.FL_LEFT_MOUSE:
        tbl._push_xy = (fltk.Fl.event_x(), fltk.Fl.event_y())
        tbl._dragging = False
        tbl._cell_pushed = False
        hit = getattr(tbl, "header_hit", None)  # thumbs grid has no header
        tbl._hdr_push = hit(fltk.Fl.event_x(), fltk.Fl.event_y()) if hit else None
        if tbl._hdr_push and tbl._hdr_push[1] is not None:
            # our own column-border drag (wider grab zone than Fl_Table's):
            # TC semantics -- resize the column LEFT of the border, columns
            # to the right keep their widths and shift
            b = tbl._hdr_push[1]
            tbl._col_drag = (b, fltk.Fl.event_x(), tbl.col_width(b))
            return 1
        return sup(event)
    if event == fltk.FL_DRAG and getattr(tbl, "_col_drag", None):
        b, sx, sw = tbl._col_drag
        new = max(20, sw + fltk.Fl.event_x() - sx)  # overflow crops, TC-like
        tbl.col_width(b, new)
        if b > 0:  # Name refills on relayout; the rest are user-set
            tbl._user_w[b] = new
        tbl.redraw()
        return 1
    if event == fltk.FL_DRAG:
        # header pushes (sort click or column-border resize) belong to
        # Fl_Table; only a drag that started on a cell is a file drag-out
        if getattr(tbl, "_hdr_push", None) or not tbl._cell_pushed:
            return sup(event)
        if tbl._push_xy and not tbl._dragging:
            dx = abs(fltk.Fl.event_x() - tbl._push_xy[0])
            dy = abs(fltk.Fl.event_y() - tbl._push_xy[1])
            if dx + dy > 6:
                tbl._dragging = True
                tbl._push_xy = None
                tbl.pane.start_drag()
                fltk.Fl.pushed(None)
                tbl._dragging = False
        return 1
    if event == fltk.FL_RELEASE:
        tbl._col_drag = None
        hp, tbl._hdr_push = getattr(tbl, "_hdr_push", None), None
        if hp and tbl._push_xy:
            col, border = hp
            dx = abs(fltk.Fl.event_x() - tbl._push_xy[0])
            dy = abs(fltk.Fl.event_y() - tbl._push_xy[1])
            if border is None and dx + dy < 5:
                tbl.pane.sort(COLS[col])
        tbl._push_xy = None
        return sup(event) or 1
    if event == fltk.FL_MOVE:
        hit = getattr(tbl, "header_hit", None)
        hp = hit(fltk.Fl.event_x(), fltk.Fl.event_y()) if hit else None
        if hp is not None and hp[1] is not None:
            # every move: the window-level handler resets the cursor
            tbl.window().cursor(fltk.FL_CURSOR_WE)
            tbl._we_cursor = True
            return 1  # keep Fl_Table's own (narrower) cursor logic out
        if getattr(tbl, "_we_cursor", False):
            tbl._we_cursor = False
            tbl.window().cursor(fltk.FL_CURSOR_DEFAULT)
        return sup(event)
    if event == fltk.FL_MOUSEWHEEL:
        r = sup(event)
        tbl.pane.sync_scrollbar()
        return r
    if event in (fltk.FL_DND_ENTER, fltk.FL_DND_DRAG, fltk.FL_DND_RELEASE):
        return 1
    if event == fltk.FL_PASTE:
        tbl.pane.on_drop(fltk.Fl.event_text())
        return 1
    if event == fltk.FL_KEYDOWN:
        if tbl.pane.on_key():
            return 1
        return sup(event)
    return sup(event)


def fit_name(nm: str, avail: float) -> str:
    """TC-style truncation for a too-narrow Name column: end with '..',
    and keep the closing bracket of '[dirname]' entries."""
    if fltk.fl_width(nm) <= avail:
        return nm
    bracket = nm.startswith("[") and nm.endswith("]")
    body, tail = (nm[:-1], "..]") if bracket else (nm, "..")
    lo, hi = 0, len(body)
    while lo < hi:  # longest prefix that fits together with the tail
        mid = (lo + hi + 1) // 2
        if fltk.fl_width(body[:mid] + tail) <= avail:
            lo = mid
        else:
            hi = mid - 1
    return body[:lo] + tail


def fmt_date(e: DirEntry) -> str:
    if not e.mtime:
        return ""
    return datetime.fromtimestamp(e.mtime).strftime("%Y-%m-%d %H:%M")


def fmt_attr(e: DirEntry) -> str:
    if e.attr:
        return e.attr           # win32 "rahs" flags from the VFS
    if e.mode:
        return filemode(e.mode)[1:]  # POSIX rwx string
    return ""


class FileList(fltk.Fl_Box):
    """Custom-drawn file list: column header band + rows, vertical-only
    scrolling (the pane owns the scrollbar). Replaces Fl_Table, whose
    scrollbar and damage machinery fought every TC behavior needed here
    (kept the old FileTable's public surface: rows/top_row/vis_rows/
    col_width/header_hit/ensure_visible/nav_key/cell_index)."""

    def __init__(self, x, y, w, h, pane):
        super().__init__(x, y, w, h)
        self.pane = pane
        self.box(fltk.FL_NO_BOX)  # everything is drawn here
        self.set_visible_focus()  # keyboard focus, no ring drawn
        self._rows = 0
        self._top = 0
        self._user_w: dict[int, int] = {}  # user-resized column widths
        self._widths = [80, COL_EXT, COL_SIZE, COL_DATE, COL_ATTR]
        self._push_xy = None
        self._dragging = False
        self._cell_pushed = False
        self._hdr_push = None
        self._col_drag = None
        self._we_cursor = False

    # -- geometry ----------------------------------------------------------
    def rows(self, n=None):
        if n is None:
            return self._rows
        self._rows = n
        self._top = min(self._top, max(0, n - self.vis_rows()))
        self._autosize_cols()

    def top_row(self, n=None):
        if n is None:
            return self._top
        self._top = max(0, min(n, max(0, self._rows - self.vis_rows())))
        self.redraw()

    def vis_rows(self) -> int:
        return max(1, (self.h() - HDR_H - 2 * PAD) // ROW_H)

    def inner_w(self) -> int:
        need = self._rows > self.vis_rows()
        return self.w() - 2 * PAD - (fltk.Fl.scrollbar_size() if need else 0)

    def col_width(self, c, w=None):
        if w is None:
            return self._widths[c]
        self._widths[c] = max(20, w)
        self.redraw()

    def _autosize_cols(self):
        """Name fills whatever the fixed columns leave over."""
        fixed = [self._user_w.get(c, d) for c, d in
                 ((1, COL_EXT), (2, COL_SIZE), (3, COL_DATE), (4, COL_ATTR))]
        self._widths = [max(80, self.inner_w() - sum(fixed))] + fixed
        self.redraw()

    def resize(self, x, y, w, h):
        super().resize(x, y, w, h)
        self._autosize_cols()

    def cell_index(self, r: int, c: int = 0) -> int:
        return r

    def row_at(self, ey: int) -> int:
        top_y = self.y() + PAD + HDR_H
        if ey < top_y:
            return -1
        r = self._top + (ey - top_y) // ROW_H
        return r if r < self._rows else -1

    def header_hit(self, ex, ey):
        """(col, border) when (ex, ey) is in the column header band;
        border is the column a resize drag would change (None when not
        within the 5px grab zone; the last column has no right border)."""
        if not (self.y() + PAD <= ey <= self.y() + PAD + HDR_H):
            return None
        x0 = self.x() + PAD
        for c in range(5):
            wc = self._widths[c]
            if ex < x0 + wc:
                if c > 0 and ex - x0 <= 5:
                    return (c, c - 1)
                if (x0 + wc) - ex <= 5 and c < 4:
                    return (c, c)
                return (c, None)
            x0 += wc
        return None

    def nav_key(self, key: int) -> bool:
        m = self._NAV.get(key)
        if m is None:
            return False
        self.pane.move_cursor(**m)
        return True

    _NAV = {
        fltk.FL_Up: {"delta": -1}, fltk.FL_Down: {"delta": 1},
        fltk.FL_Home: {"absolute": "home"}, fltk.FL_End: {"absolute": "end"},
        fltk.FL_Page_Up: {"delta": "pgup"}, fltk.FL_Page_Down: {"delta": "pgdn"},
    }

    def ensure_visible(self, idx: int):
        vis = self.vis_rows()
        if idx < self._top:
            self.top_row(idx)
        elif idx >= self._top + vis:
            self.top_row(idx - vis + 1)
        self.pane.sync_scrollbar()

    # -- drawing -----------------------------------------------------------
    def draw(self):
        x, y, w, h = self.x(), self.y(), self.w(), self.h()
        fltk.fl_push_clip(x, y, w, h)
        fltk.fl_color(theme.ROW_BG)
        fltk.fl_rectf(x + 1, y + 1, w - 2, h - 2)
        fltk.fl_font(fltk.FL_HELVETICA, 12)
        self._draw_header()
        cy, bottom = y + PAD + HDR_H, y + h - PAD
        r = self._top
        while cy < bottom:
            if r < min(self._rows, len(self.pane.view)):
                self._draw_row(r, cy)
                cy += ROW_H
                r += 1
            else:
                break
        fltk.fl_draw_box(fltk.FL_THIN_DOWN_FRAME, x, y, w, h,
                         fltk.FL_BACKGROUND_COLOR)
        fltk.fl_pop_clip()

    def _draw_header(self):
        x0, y0 = self.x() + PAD, self.y() + PAD
        bw = self.w() - 2 * PAD
        fltk.fl_color(theme.HEADER_BG)
        fltk.fl_rectf(x0, y0, bw, HDR_H)
        cx = x0
        for c in range(5):
            wc = self._widths[c]
            fltk.fl_push_clip(cx, y0, min(wc, x0 + bw - cx), HDR_H)
            fltk.fl_color(theme.HEADER_EDGE)
            fltk.fl_line(cx + wc - 1, y0 + 2, cx + wc - 1, y0 + HDR_H - 3)
            fltk.fl_color(theme.TEXT)
            fltk.fl_draw(COL_TITLES[c], cx + 4, y0, wc - 8, HDR_H,
                         fltk.FL_ALIGN_LEFT)
            if self.pane.sort_key == COLS[c]:
                ax, ay = cx + wc - 14, y0 + (HDR_H - 5) // 2
                fltk.fl_color(fltk.FL_DARK2)
                if self.pane.sort_rev:   # descending: down arrow
                    fltk.fl_polygon(ax, ay, ax + 9, ay, ax + 4, ay + 5)
                else:                    # ascending: up arrow
                    fltk.fl_polygon(ax, ay + 5, ax + 9, ay + 5, ax + 4, ay)
            fltk.fl_pop_clip()
            cx += wc
            if cx >= x0 + bw:
                break
        fltk.fl_color(theme.HEADER_EDGE)
        fltk.fl_line(x0, y0 + HDR_H - 1, x0 + bw - 1, y0 + HDR_H - 1)

    def _draw_row(self, r, ry):
        e = self.pane.view[r]
        cursor = r == self.pane.cursor
        focused = self.pane.is_active
        x0 = self.x() + PAD
        iw = self.w() - 2 * PAD
        if cursor and focused:
            fltk.fl_color(theme.CURSOR_BG)
        else:
            fltk.fl_color(theme.ROW_BG if r % 2 == 0 else theme.ROW_BG_ALT)
        fltk.fl_rectf(x0, ry, iw, ROW_H)
        if cursor and not focused:  # inactive pane: outline instead of fill
            fltk.fl_color(theme.CURSOR_EDGE)
            fltk.fl_line(x0, ry, x0 + iw - 1, ry)
            fltk.fl_line(x0, ry + ROW_H - 1, x0 + iw - 1, ry + ROW_H - 1)
        # text is never inverted: black, or red when explicitly selected
        color = theme.SEL_TEXT if e.name in self.pane.selected else theme.TEXT
        cx = x0
        for c in range(5):
            wc = self._widths[c]
            fltk.fl_push_clip(cx, ry, min(wc, x0 + iw - cx), ROW_H)
            fltk.fl_color(color)
            if c == 0:
                from .icons import ICON_W, entry_icon
                entry_icon(e).draw(cx + 2, ry + (ROW_H - ICON_W) // 2)
                nm = e.name if e.is_dir else paths.splitext(e.name)[0]
                if e.is_dir and e.name != "..":
                    nm = "[" + nm + "]"
                nm = fit_name(nm, wc - ICON_W - 10)
                fltk.fl_draw(nm, cx + ICON_W + 6, ry, wc - ICON_W - 10, ROW_H,
                             fltk.FL_ALIGN_LEFT, None, 0)
            elif c == 1:
                fltk.fl_draw(e.ext, cx + 2, ry, wc - 4, ROW_H,
                             fltk.FL_ALIGN_LEFT, None, 0)
            elif c == 2:
                fltk.fl_draw(self.pane.size_text(e), cx + 2, ry, wc - 6,
                             ROW_H, fltk.FL_ALIGN_RIGHT)
            elif c == 3:
                fltk.fl_draw(fmt_date(e), cx + 2, ry, wc - 4, ROW_H,
                             fltk.FL_ALIGN_LEFT)
            else:
                fltk.fl_draw(fmt_attr(e), cx + 2, ry, wc - 4, ROW_H,
                             fltk.FL_ALIGN_LEFT)
            fltk.fl_pop_clip()
            cx += wc
            if cx >= x0 + iw:
                break

    # -- events ------------------------------------------------------------
    def handle(self, event):
        pane = self.pane
        if event == fltk.FL_FOCUS:
            pane.dispatch("pane.activate", pane)
            return 1
        if event == fltk.FL_UNFOCUS:
            return 1  # active state is app-owned; don't dim on focus-steal
        if event in (fltk.FL_ENTER, fltk.FL_LEAVE):
            return 1
        if event == fltk.FL_MOVE:
            hp = self.header_hit(fltk.Fl.event_x(), fltk.Fl.event_y())
            if hp is not None and hp[1] is not None:
                # every move: the window-level handler resets the cursor
                self.window().cursor(fltk.FL_CURSOR_WE)
                self._we_cursor = True
            elif self._we_cursor:
                self._we_cursor = False
                self.window().cursor(fltk.FL_CURSOR_DEFAULT)
            return 1
        if (event == fltk.FL_PUSH
                and fltk.Fl.event_button() == fltk.FL_LEFT_MOUSE):
            self._push_xy = (fltk.Fl.event_x(), fltk.Fl.event_y())
            self._dragging = False
            self._cell_pushed = False
            self._hdr_push = self.header_hit(*self._push_xy)
            if self._hdr_push:
                if self._hdr_push[1] is not None:  # border: start a resize
                    b = self._hdr_push[1]
                    self._col_drag = (b, fltk.Fl.event_x(), self._widths[b])
                return 1
            self.take_focus()
            idx = self.row_at(fltk.Fl.event_y())
            if idx >= 0:
                self._cell_pushed = True
                pane.on_mouse_push(idx)
                if fltk.Fl.event_clicks():
                    pane.dispatch("nav.open", pane)
            return 1
        if event == fltk.FL_DRAG:
            if self._col_drag:
                # TC semantics: resize the column left of the border; the
                # columns to the right keep their widths and shift
                b, sx, sw = self._col_drag
                self.col_width(b, max(20, sw + fltk.Fl.event_x() - sx))
                if b > 0:
                    self._user_w[b] = self._widths[b]
                return 1
            if self._cell_pushed and self._push_xy and not self._dragging:
                dx = abs(fltk.Fl.event_x() - self._push_xy[0])
                dy = abs(fltk.Fl.event_y() - self._push_xy[1])
                if dx + dy > 6:
                    self._dragging = True
                    self._push_xy = None
                    pane.start_drag()
                    fltk.Fl.pushed(None)
                    self._dragging = False
            return 1
        if event == fltk.FL_RELEASE:
            if self._col_drag:
                b = self._col_drag[0]
                self._col_drag = None
                if b == 0:  # a Name drag shifts the difference into Ext
                    rest = sum(self._user_w.get(c, d) for c, d in
                               ((2, COL_SIZE), (3, COL_DATE), (4, COL_ATTR)))
                    self._user_w[1] = max(
                        20, self.inner_w() - self._widths[0] - rest)
                # re-fill Name so the last column hugs the right edge
                self._autosize_cols()
            hp, self._hdr_push = self._hdr_push, None
            if hp and self._push_xy:
                col, border = hp
                dx = abs(fltk.Fl.event_x() - self._push_xy[0])
                dy = abs(fltk.Fl.event_y() - self._push_xy[1])
                if border is None and dx + dy < 5:
                    pane.sort(COLS[col])
            self._push_xy = None
            return 1
        if event == fltk.FL_MOUSEWHEEL:
            self.top_row(self._top + 3 * fltk.Fl.event_dy())
            pane.sync_scrollbar()
            return 1
        if event in (fltk.FL_DND_ENTER, fltk.FL_DND_DRAG, fltk.FL_DND_RELEASE):
            return 1
        if event == fltk.FL_PASTE:
            pane.on_drop(fltk.Fl.event_text())
            return 1
        if event == fltk.FL_KEYDOWN:
            if pane.on_key():
                return 1
        return super().handle(event)


class PaneHeader(fltk.Fl_Box):
    """Directory label at the top of a pane. Draws a raised divider bevel on
    its right edge (visually continuing the tile divider), shows the active
    pane in a darker steel-blue, is a drag source for the current dir, and
    opens the folder-shortcuts (bookmarks) menu on double-click."""

    def __init__(self, x, y, w, h, pane):
        super().__init__(x, y, w, h)
        self.pane = pane
        self.box(fltk.FL_FLAT_BOX)
        self.color(theme.PATH_IDLE)
        self.labelfont(fltk.FL_HELVETICA)
        self.labelsize(12)
        self._push_xy = None
        self._dragging = False

    def draw(self):
        c = theme.PATH_ACTIVE if self.pane.is_active else theme.PATH_IDLE
        fltk.fl_color(c)
        fltk.fl_rectf(self.x(), self.y(), self.w(), self.h())
        # directory text (drawn without symbol parsing)
        fltk.fl_color(theme.TEXT)
        fltk.fl_font(fltk.FL_HELVETICA, 12)
        fltk.fl_push_clip(self.x(), self.y(), self.w() - 4, self.h())
        fltk.fl_draw(self.label() or "", self.x() + 4, self.y(),
                     self.w() - 8, self.h(), fltk.FL_ALIGN_LEFT, None, 0)
        fltk.fl_pop_clip()
        # raised divider bevel on the right edge (continues the tile divider)
        rx = self.x() + self.w() - 1
        fltk.fl_color(fltk.FL_DARK3)
        fltk.fl_line(rx, self.y(), rx, self.y() + self.h() - 1)
        fltk.fl_color(fltk.FL_LIGHT3)
        fltk.fl_line(rx - 1, self.y(), rx - 1, self.y() + self.h() - 1)

    def handle(self, event):
        if event == fltk.FL_PUSH and fltk.Fl.event_button() == fltk.FL_LEFT_MOUSE:
            self.pane.dispatch("pane.activate", self.pane)
            if fltk.Fl.event_clicks():  # double-click -> bookmarks menu
                self.pane.dispatch("bookmarks.menu", self.pane)
                return 1
            self._push_xy = (fltk.Fl.event_x(), fltk.Fl.event_y())
            self._dragging = False
            return 1
        if event == fltk.FL_DRAG and self._push_xy and not self._dragging:
            if (abs(fltk.Fl.event_x() - self._push_xy[0])
                    + abs(fltk.Fl.event_y() - self._push_xy[1])) > 6:
                self._dragging = True
                self._push_xy = None
                self.pane.start_header_drag()
            return 1
        if event == fltk.FL_RELEASE:
            self._push_xy = None
            return 1
        return super().handle(event)


class _RenameInput(fltk.Fl_Input):
    def __init__(self, x, y, w, h, pane, old: str):
        super().__init__(x, y, w, h)
        self.pane, self.old = pane, old
        self.textsize(12)
        self.value(old)
        self.when(fltk.FL_WHEN_ENTER_KEY)
        self.callback(lambda wid: pane.end_rename(self.value()))

    def handle(self, event):
        if event == fltk.FL_KEYDOWN and fltk.Fl.event_key() == fltk.FL_Escape:
            self.pane.end_rename(None)
            return 1
        if event == fltk.FL_UNFOCUS:
            r = super().handle(event)
            self.pane.end_rename(None)
            return r
        return super().handle(event)


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
        self.dir_sizes: dict[str, int] = {}  # computed via Space / Ctrl+L
        self._rename: _RenameInput | None = None
        self._mtime = 0.0  # dir mtime at last listing (external-change poll)
        self.vfs_stack: list[tuple] = []  # (vfs, path, cursor) below this one
        self.mode = "list"                # list | thumbs | preview
        self.thumbs = None                # ThumbView, created on demand
        self.preview = None               # PreviewView, created on demand
        self.on_cursor = None             # app hook: cursor moved
        self.on_path = None               # app hook: path/listing changed
        self.hist_back: list[str] = []    # location history (bookmark form)
        self.hist_fwd: list[str] = []
        self.sort_key = "name"
        self.sort_rev = False
        self._search = ""
        self._search_t = 0.0
        self.is_active = False
        self.header = PaneHeader(x, y, w, HDR_H, self)
        self.table = FileList(x, y + HDR_H, w, h - HDR_H - FOOT_H, self)
        # pane-owned vertical scrollbar, TC-style: right edge, starting
        # below the column header band (Fl_Table's own bars stay hidden)
        self.vbar = fltk.Fl_Scrollbar(x + w - 12, y + HDR_H, 12, 10)
        self.vbar.linesize(1)
        self.vbar.when(fltk.FL_WHEN_CHANGED)
        self.vbar.callback(self._vbar_cb)
        self.vbar.hide()
        self.footer = fltk.Fl_Box(x, y + h - FOOT_H, w, FOOT_H)
        self.footer.box(fltk.FL_FLAT_BOX)
        self.footer.color(theme.FOOTER_BG)
        self.footer.align(fltk.FL_ALIGN_INSIDE | fltk.FL_ALIGN_LEFT | fltk.FL_ALIGN_CLIP)
        self.footer.labelsize(11)
        self.resizable(self.table)
        self.end()
        self.refresh()

    # -- scrollbar ---------------------------------------------------------
    def _vbar_cb(self, wid):
        self.table.top_row(int(wid.value()))
        self.table.redraw()

    def sync_scrollbar(self):
        # overlays the strip Fl_Table reserves; below the header band
        sb = fltk.Fl.scrollbar_size()
        rows, vis = len(self.view), self.table.vis_rows()
        need = self.mode == "list" and rows > vis
        if need:
            self.vbar.resize(self.x() + self.w() - sb,
                             self.y() + 2 * HDR_H + 2, sb,
                             self.h() - 2 * HDR_H - FOOT_H - 2)
            self.vbar.value(self.table.top_row(), vis, 0, rows)
            self.vbar.show()
        else:
            self.vbar.hide()

    def resize(self, x, y, w, h):
        super().resize(x, y, w, h)
        self.sync_scrollbar()

    # -- listing ----------------------------------------------------------
    def refresh(self, keep_cursor_name: str | None = None):
        try:
            entries = self.vfs.listdir(self.path)
            self._mtime = self.vfs.stat(self.path).mtime
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

    def maybe_refresh(self):
        """Auto-refresh when the directory changed externally (mtime poll).
        Local panes only; skipped while an inline rename is open."""
        if self._rename or self.vfs.scheme != "file":
            return
        try:
            mt = self.vfs.stat(self.path).mtime
        except OSError:
            return
        if mt != self._mtime:
            self.refresh()

    def location(self) -> str | None:
        """Current spot in portable bookmark form (None inside archives)."""
        from .. import bookmarks
        if self.vfs.scheme not in ("file", "sftp"):
            return None
        return bookmarks.make_location(self.vfs, self.path)

    def record_hist(self):
        loc = self.location()
        if loc and (not self.hist_back or self.hist_back[-1] != loc):
            self.hist_back.append(loc)
            del self.hist_back[:-50]
        self.hist_fwd.clear()

    def set_path(self, path: str, cursor_name: str | None = None,
                 record: bool = True):
        if record:
            self.record_hist()
        self.path = paths.canon(path)
        self.selected.clear()
        self.dir_sizes.clear()
        self.cursor = 0
        self.refresh(keep_cursor_name=cursor_name)
        # new directory: scroll back to the top, then keep cursor in view
        self.table.top_row(0)
        if self.thumbs:
            self.thumbs.top_row(0)
        self.active_view().ensure_visible(self.cursor)
        self.redraw_view()

    def _sort(self):
        keyf = {
            "name": lambda e: e.name.lower(),
            "ext": lambda e: (e.ext.lower(), e.name.lower()),
            "size": lambda e: e.size,
            "date": lambda e: e.mtime,
            "attr": lambda e: (fmt_attr(e), e.name.lower()),
        }[self.sort_key]
        # dirs follow name/date ordering (TC-style); ext/size keep them by name
        if self.sort_key in ("name", "date"):
            dirs = sorted((e for e in self.entries if e.is_dir),
                          key=keyf, reverse=self.sort_rev)
        else:
            dirs = sorted((e for e in self.entries if e.is_dir),
                          key=lambda e: e.name.lower())
        files = sorted((e for e in self.entries if not e.is_dir),
                       key=keyf, reverse=self.sort_rev)
        top = paths.is_root(self.path) and not self.vfs_stack
        self.view = ([] if top else [_UP]) + dirs + files

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
        self.sync_scrollbar()
        if self.thumbs:
            self.thumbs.relayout()
        self.header.copy_label(" " + esc(self.vfs.display(self.path)))
        self._update_footer()
        self.table.redraw()
        if self.on_path:
            self.on_path(self)

    # -- cursor / selection ------------------------------------------------
    def current(self) -> DirEntry | None:
        return self.view[self.cursor] if 0 <= self.cursor < len(self.view) else None

    def active_view(self):
        return self.thumbs if (self.mode == "thumbs" and self.thumbs) else self.table

    def redraw_view(self):
        self.table.redraw()
        if self.thumbs and self.thumbs.visible():
            self.thumbs.redraw()

    def set_mode(self, mode: str):
        if mode == self.mode:
            return
        if self._rename:
            self.end_rename(None)
        t = self.table
        if mode == "thumbs" and self.thumbs is None:
            from .thumbs import ThumbView
            self.thumbs = ThumbView(t.x(), t.y(), t.w(), t.h(), self)
            self.add(self.thumbs)
        if mode == "preview" and self.preview is None:
            from .preview import PreviewView
            self.preview = PreviewView(t.x(), t.y(), t.w(), t.h(), self)
            self.add(self.preview)
        self.mode = mode
        for wdg, on in ((self.table, mode == "list"),
                        (self.thumbs, mode == "thumbs"),
                        (self.preview, mode == "preview")):
            if wdg:
                wdg.show() if on else wdg.hide()
        if mode == "thumbs":
            self.thumbs.resize(t.x(), t.y(), t.w(), t.h())
            self.thumbs.relayout()
            self.thumbs.take_focus()
        elif mode == "list":
            self.table.take_focus()
        if mode != "preview":
            self._sync()
        self.redraw()

    def set_cursor(self, i: int):
        self.cursor = max(0, min(i, len(self.view) - 1))
        v = self.active_view()
        v.ensure_visible(self.cursor)
        v.redraw()
        if self.on_cursor:
            self.on_cursor(self)

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

    def toggle_select(self, advance=False, du=False):
        e = self.current()
        if e and e.name != "..":
            if du and e.is_dir and e.name not in self.dir_sizes:
                self.dir_sizes[e.name] = self._du(paths.join(self.path, e.name))
            self.selected.symmetric_difference_update({e.name})
        if advance:
            self.move_cursor(delta=1)
        self._update_footer()
        self.redraw_view()

    def select_all(self, on=True):
        self.selected = {e.name for e in self.view if e.name != ".."} if on else set()
        self._update_footer()
        self.redraw_view()

    def select_glob(self, pattern: str, add=True):
        hits = {e.name for e in self.view
                if not e.is_dir and fnmatch(e.name.lower(), pattern.lower())}
        self.selected = (self.selected | hits) if add else (self.selected - hits)
        self._update_footer()
        self.redraw_view()

    def invert_selection(self):
        files = {e.name for e in self.view if not e.is_dir}
        self.selected = files - self.selected
        self._update_footer()
        self.redraw_view()

    # -- mouse selection (TC semantics) --------------------------------------
    # Plain click only moves the cursor: the item under the cursor is the
    # implicit selection, never shown in red. Explicit (red) selection is
    # built with Ins, Ctrl+click (toggle, cursor follows) or Shift+click
    # (adds the cursor..clicked range).
    def on_mouse_push(self, row: int):
        e = self.view[row]
        state = fltk.Fl.event_state()
        if state & fltk.FL_SHIFT:
            a, b = sorted((self.cursor, row))
            self.selected |= {en.name for en in self.view[a:b + 1]
                              if en.name != ".."}
        elif state & fltk.FL_CTRL:
            if e.name != "..":
                self.selected ^= {e.name}
        self.set_cursor(row)
        self._update_footer()
        self.redraw_view()

    # -- nested VFS (archives, later sftp-in-archive etc.) --------------------
    def push_vfs(self, new_vfs: VFS, start_path: str, record: bool = True):
        if record:
            self.record_hist()
        e = self.current()
        self.vfs_stack.append((self.vfs, self.path, e.name if e else None))
        self.vfs = new_vfs
        self.set_path(start_path, record=False)

    def pop_vfs(self, record: bool = True) -> bool:
        if not self.vfs_stack:
            return False
        if record:
            self.record_hist()
        close = getattr(self.vfs, "close", None)
        old_vfs, old_path, cursor = self.vfs_stack.pop()
        self.vfs = old_vfs
        self.set_path(old_path, cursor_name=cursor, record=False)
        if close:
            try:
                close()
            except OSError:
                pass
        return True

    def enter_archive(self, name: str) -> bool:
        from ..vfs.archive import ArchiveVFS
        if self.vfs.scheme != "file":
            self.flash("archives: local files only (for now)")
            return False
        try:
            avfs = ArchiveVFS(paths.join(self.path, name))
        except Exception as e:  # zipfile/tarfile raise various types
            self.flash(f"archive: {e}")
            return False
        self.push_vfs(avfs, "/")
        return True

    # -- inline rename (F2 / Shift+F6) ----------------------------------------
    def start_rename(self):
        e = self.current()
        if not e or e.name == ".." or self._rename:
            return
        self.set_cursor(self.cursor)  # ensure the row is scrolled into view
        t = self.table
        y = t.y() + PAD + HDR_H + (self.cursor - t.top_row()) * ROW_H
        inp = _RenameInput(t.x() + 2, y, t.col_width(0) + t.col_width(1),
                           ROW_H + 4, self, e.name)
        self.add(inp)
        self._rename = inp
        inp.show()
        inp.take_focus()
        self.redraw()

    def end_rename(self, newname: str | None):
        inp, self._rename = self._rename, None
        if not inp:
            return
        old = inp.old
        self.remove(inp)
        fltk.Fl.delete_widget(inp)
        self.table.take_focus()
        if newname and newname != old:
            try:
                self.vfs.rename(paths.join(self.path, old),
                                paths.join(self.path, newname))
            except OSError as ex:
                self.flash(f"rename: {ex}")
                self.refresh()
                return
            if old in self.selected:
                self.selected.discard(old)
                self.selected.add(newname)
            self.refresh(keep_cursor_name=newname)
        self.redraw()

    # -- drag and drop -------------------------------------------------------
    def start_drag(self):
        if not isinstance(self.vfs, LocalVFS):
            self.flash("drag-out: local files only (for now)")
            return
        e = self.current()
        if self.selected and (not e or e.name in self.selected):
            names = [en.name for en in self.view if en.name in self.selected]
        elif e and e.name != "..":
            names = [e.name]
        else:
            return
        files = [paths.join(self.path, n) for n in names]
        try:
            own = []
            w = fltk.Fl.first_window()
            while w:
                own.append(fltk.fl_xid(w))
                w = fltk.Fl.next_window(w)
            dnd.start_file_drag(self.window(), files, own)
        except (NotImplementedError, RuntimeError) as ex:
            self.flash(f"drag-out: {ex}")
        # the nested drag loop consumed X events; repaint everything
        w = fltk.Fl.first_window()
        while w:
            w.redraw()
            w = fltk.Fl.next_window(w)

    def on_drop(self, text: str):
        files = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("file://"):
                files.append(paths.from_uri(line))
            elif (line.startswith("/") or line.startswith("\\\\") or
                  (len(line) > 2 and line[1] == ":" and line[2] in "/\\")):
                files.append(paths.canon(line))  # POSIX, UNC or drive path
        files = [f for f in files if f and paths.parent(f) != self.path]
        if not files:
            return
        move = _shift_down()  # sample NOW: Shift+drop means move
        # Defer past the source's modal DoDragDrop loop: on Windows the
        # drop is delivered synchronously inside it, and a dialog here
        # would hang the source app until dismissed.
        fltk.Fl.add_timeout(0.0,
                            lambda data=None: self._drop_copy(files, move))

    def _drop_copy(self, files, move=False):
        from .. import ops
        from ..ui import dialogs, progress
        if not isinstance(self.vfs, LocalVFS):
            self.flash("drop: only local targets for now")
            return
        verb = "Move" if move else "Copy"
        if not dialogs.confirm(verb, f"{verb} {len(files)} item(s) to\n"
                               f"{self.path} ?", yes=verb):
            return
        ctl = ops.OpControl()
        progress.run_operation(
            verb, f"{verb} {len(files)} item(s) -> {self.path}", ctl,
            lambda: ops.copy_op(self.vfs, files, self.vfs, self.path, ctl,
                                move=move))
        self.refresh()

    # -- keyboard ------------------------------------------------------------
    def on_key(self) -> bool:
        key = fltk.Fl.event_key()
        state = fltk.Fl.event_state()
        mods = state & (fltk.FL_CTRL | fltk.FL_ALT | fltk.FL_META)
        action = self.keymap.action_for_event()
        if action:
            return bool(self.dispatch(action, self))
        if not mods and self.active_view().nav_key(key):
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

    # -- sizes / footer -------------------------------------------------------
    def entry_bytes(self, e: DirEntry) -> int:
        return self.dir_sizes.get(e.name, 0) if e.is_dir else e.size

    def size_text(self, e: DirEntry) -> str:
        if e.name == "..":
            return "<UP>"
        if e.is_dir:
            n = self.dir_sizes.get(e.name)
            return "<DIR>" if n is None else f"{n:,}"
        return f"{e.size:,}"

    def _du(self, p: str) -> int:
        total = 0
        stack = [p]
        while stack:
            d = stack.pop()
            try:
                entries = self.vfs.listdir(d)
            except OSError:
                continue
            for e in entries:
                if e.is_dir and not e.is_link:
                    stack.append(paths.join(d, e.name))
                else:
                    total += e.size
        return total

    def calc_sizes(self, names: list[str]) -> int:
        """Compute (and remember) sizes for the given entries; returns total."""
        total = 0
        for e in self.view:
            if e.name not in names or e.name == "..":
                continue
            if e.is_dir:
                if e.name not in self.dir_sizes:
                    self.dir_sizes[e.name] = self._du(paths.join(self.path, e.name))
                total += self.dir_sizes[e.name]
            else:
                total += e.size
        self._update_footer()
        self.redraw_view()
        return total

    def _update_footer(self):
        if self._search:
            self.footer.copy_label(esc(f" search: {self._search}"))
            return
        real = [e for e in self.view if e.name != ".."]
        files = [e for e in real if not e.is_dir]
        sel = [e for e in real if e.name in self.selected]
        total = sum(self.entry_bytes(e) for e in real)
        ssel = sum(self.entry_bytes(e) for e in sel)
        self.footer.copy_label(
            f" {ssel:,} / {total:,} bytes in {len(sel)} / "
            f"{len(real)} selected")

    def set_active(self, active: bool):
        self.is_active = active
        self.header.redraw()
        self.redraw_view()

    def start_header_drag(self):
        """Drag the current directory out (to the locations toolbar or a
        file manager). Local paths only for the toolbar's own DND-in."""
        if self.vfs.scheme != "file":
            self.flash("drag dir: local only for external drop")
            return
        try:
            w = self.window()
            own = []
            ww = fltk.Fl.first_window()
            while ww:
                own.append(fltk.fl_xid(ww))
                ww = fltk.Fl.next_window(ww)
            dnd.start_file_drag(w, [self.path], own)
        except (NotImplementedError, RuntimeError) as ex:
            self.flash(f"drag: {ex}")
        ww = fltk.Fl.first_window()
        while ww:
            ww.redraw()
            ww = fltk.Fl.next_window(ww)

    def flash(self, msg: str):
        self.footer.copy_label(" " + esc(msg))
        self.footer.redraw()
