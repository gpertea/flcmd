"""Thumbnail grid view (TC 'Thumbnail View', but with configurable tile
size). Shares the pane's entries/cursor/selection, so all keyboard and
file operations keep working; thumbnails decode incrementally on a
timeout so the UI never blocks."""

import math

import fltk

from .. import config, paths
from ..ui import theme
from .. import images
from .panel import table_click, table_handle

_T = fltk.Fl_Table
LABEL_H = 16
PAD = 6
TILE_SIZES = (64, 96, 128, 160, 192, 256)


class ThumbView(fltk.Fl_Table):
    def __init__(self, x, y, w, h, pane):
        super().__init__(x, y, w, h)
        self.pane = pane
        self.tile = int(config.load().get("thumbs", {}).get("size", 128))
        self.col_header(0)
        self.row_header(0)
        self.color(theme.ROW_BG)
        self.callback(self._on_click)
        self.when(fltk.FL_WHEN_CHANGED | fltk.FL_WHEN_RELEASE)
        self._push_xy = None
        self._dragging = False
        self._cell_pushed = False
        self._cache: dict[str, object] = {}  # name -> image | False(failed)
        self._pending: list[str] = []
        self._ticking = False
        self._cols = 1
        self.end()
        self.relayout()

    def cell_w(self) -> int:
        return self.tile + 2 * PAD

    def cell_h(self) -> int:
        return self.tile + LABEL_H + 2 * PAD

    def set_tile(self, ts: int):
        self.tile = ts
        self._cache.clear()
        self._pending.clear()
        config.update("thumbs", {"size": ts})
        self.relayout()

    def relayout(self):
        sb = self.scrollbar_size() or fltk.Fl.scrollbar_size()
        self._cols = max(1, (self.w() - sb - 4) // self.cell_w())
        n = len(self.pane.view)
        self.rows(max(1, math.ceil(n / self._cols)))
        self.cols(self._cols)
        self.col_width_all(self.cell_w())
        self.row_height_all(self.cell_h())
        names = {e.name for e in self.pane.view}
        for k in list(self._cache):
            if k not in names:
                del self._cache[k]
        self._pending = [n_ for n_ in self._pending if n_ in names]
        self.redraw()

    def resize(self, x, y, w, h):
        super().resize(x, y, w, h)
        self.relayout()

    # -- shared pane input ----------------------------------------------------
    def cell_index(self, r: int, c: int) -> int:
        return r * self._cols + c

    def nav_key(self, key: int) -> bool:
        p = self.pane
        vis = max(1, self.h() // self.cell_h())
        step = {fltk.FL_Left: -1, fltk.FL_Right: 1,
                fltk.FL_Up: -self._cols, fltk.FL_Down: self._cols,
                fltk.FL_Page_Up: -self._cols * vis,
                fltk.FL_Page_Down: self._cols * vis}.get(key)
        if step is not None:
            p.set_cursor(p.cursor + step)
            return True
        if key == fltk.FL_Home:
            p.set_cursor(0)
            return True
        if key == fltk.FL_End:
            p.set_cursor(len(p.view) - 1)
            return True
        return False

    def ensure_visible(self, idx: int):
        row = idx // self._cols
        r1 = self.top_row()
        vis = max(1, self.h() // self.cell_h())
        if row < r1:
            self.top_row(row)
        elif row >= r1 + vis:
            self.top_row(row - vis + 1)

    def _on_click(self, wid):
        table_click(self)

    def handle(self, event):
        return table_handle(self, event, super().handle)

    # -- async thumbnail loading ------------------------------------------------
    def _enqueue(self, name: str):
        if name in self._cache or name in self._pending:
            return
        self._pending.append(name)
        if not self._ticking:
            self._ticking = True
            fltk.Fl.add_timeout(0.01, self._load_tick)

    def _load_tick(self, data=None):
        budget = 3
        while self._pending and budget:
            name = self._pending.pop(0)
            if not any(e.name == name for e in self.pane.view):
                continue
            if self.pane.vfs.scheme == "file":
                img = images.load_thumb(paths.join(self.pane.path, name),
                                        self.tile)
            else:
                img = None
            self._cache[name] = img if img else False
            budget -= 1
        if len(self._cache) > 800:  # bound memory on huge directories
            for k in list(self._cache)[:200]:
                del self._cache[k]
        self.redraw()
        if self._pending and self.visible():
            fltk.Fl.repeat_timeout(0.02, self._load_tick)
        else:
            self._ticking = False

    # -- painting -----------------------------------------------------------------
    def draw_cell(self, ctx, r=0, c=0, x=0, y=0, w=0, h=0):
        if ctx != _T.CONTEXT_CELL:
            return
        fltk.fl_push_clip(x, y, w, h)
        idx = self.cell_index(r, c)
        view = self.pane.view
        if idx >= len(view):
            fltk.fl_color(theme.ROW_BG)
            fltk.fl_rectf(x, y, w, h)
            fltk.fl_pop_clip()
            return
        e = view[idx]
        cursor = idx == self.pane.cursor
        focused = self.pane.is_active
        selected = e.name in self.pane.selected
        fltk.fl_color(theme.CURSOR_BG if (cursor and focused) else theme.ROW_BG)
        fltk.fl_rectf(x, y, w, h)
        if cursor and not focused:
            fltk.fl_color(theme.CURSOR_EDGE)
            fltk.fl_rect(x, y, w, h)
        tx, ty, ts = x + PAD, y + PAD, self.tile
        if e.is_dir:
            self._draw_folder(tx, ty, ts, e.name == "..")
        elif images.is_image(e.name):
            img = self._cache.get(e.name)
            if img is None:
                self._enqueue(e.name)
                self._draw_placeholder(tx, ty, ts, "...")
            elif img is False:
                self._draw_placeholder(tx, ty, ts, e.ext)
            else:
                img.draw(tx + (ts - img.w()) // 2, ty + (ts - img.h()) // 2)
        else:
            self._draw_placeholder(tx, ty, ts, e.ext or "file")
        if selected:
            fltk.fl_color(theme.SEL_TEXT)
            fltk.fl_rect(x + 1, y + 1, w - 2, h - 2)
            fltk.fl_rect(x + 2, y + 2, w - 4, h - 4)
        fltk.fl_font(fltk.FL_HELVETICA, 11)
        fltk.fl_color(theme.SEL_TEXT if selected else theme.TEXT)
        name = e.name
        while len(name) > 3 and fltk.fl_width(name) > w - 8:
            name = name[:-2]
        if name != e.name:
            name += ".."
        fltk.fl_draw(name, x + 4, y + PAD + ts, w - 8, LABEL_H,
                     fltk.FL_ALIGN_CENTER, None, 0)
        fltk.fl_pop_clip()

    def _draw_folder(self, x, y, ts, up: bool):
        fw, fh = int(ts * 0.72), int(ts * 0.52)
        fx, fy = x + (ts - fw) // 2, y + (ts - fh) // 2 + 4
        fltk.fl_color(fltk.fl_rgb_color(247, 207, 106))
        fltk.fl_rectf(fx, fy - 8, fw // 3, 8)  # tab
        fltk.fl_rectf(fx, fy, fw, fh)
        fltk.fl_color(fltk.fl_rgb_color(196, 155, 53))
        fltk.fl_rect(fx, fy, fw, fh)
        if up:
            fltk.fl_color(theme.TEXT)
            fltk.fl_font(fltk.FL_HELVETICA, max(11, ts // 6))
            fltk.fl_draw("..", fx, fy, fw, fh, fltk.FL_ALIGN_CENTER)

    def _draw_placeholder(self, x, y, ts, label: str):
        m = ts // 5
        fltk.fl_color(fltk.fl_rgb_color(226, 232, 240))
        fltk.fl_rectf(x + m, y + m // 2, ts - 2 * m, ts - m)
        fltk.fl_color(fltk.fl_rgb_color(160, 170, 184))
        fltk.fl_rect(x + m, y + m // 2, ts - 2 * m, ts - m)
        fltk.fl_font(fltk.FL_HELVETICA, max(9, ts // 10))
        fltk.fl_draw(label[:6], x + m, y + m // 2, ts - 2 * m, ts - m,
                     fltk.FL_ALIGN_CENTER)
