"""Custom compact title bar for undecorated (border(0)) windows: drag to
move, double-click or button to maximize, minimize/close buttons, and a
window subclass that restores edge-drag resizing (lost with the native
frame). Saves the OS title bar height -- notably tall on Windows."""

import fltk

from . import theme
from .buttons import HoverButton

TITLEBAR_H = 24
_BTN_W = 34
_EDGE = 5  # resize grip margin, px
_MIN_W, _MIN_H = 400, 300


class _CaptionBtn(HoverButton):
    """Minimize / maximize / close buttons with line-drawn glyphs."""

    def __init__(self, x, y, w, h, kind, cb):
        super().__init__(x, y, w, h)
        self.kind = kind
        self.box(fltk.FL_FLAT_BOX)
        if kind == "close":
            self.hover_color = theme.CLOSE_HOVER
        self.clear_visible_focus()
        self.callback(cb)

    def draw(self):
        fltk.fl_color(self.color())
        fltk.fl_rectf(self.x(), self.y(), self.w(), self.h())
        on_red = self.kind == "close" and self.color() == theme.CLOSE_HOVER
        fltk.fl_color(fltk.FL_WHITE if on_red else theme.TEXT)
        cx, cy, g = self.x() + self.w() // 2, self.y() + self.h() // 2, 4
        if self.kind == "min":
            fltk.fl_line(cx - g, cy + 2, cx + g, cy + 2)
        elif self.kind == "max":
            fltk.fl_rect(cx - g, cy - g + 1, 2 * g + 1, 2 * g)
        else:  # close: an X
            fltk.fl_line(cx - g, cy - g + 1, cx + g, cy + g + 1)
            fltk.fl_line(cx - g, cy + g + 1, cx + g, cy - g + 1)


class TitleBar(fltk.Fl_Group):
    def __init__(self, x, y, w, h, win, title="flcmd"):
        super().__init__(x, y, w, h)
        self.win = win
        self.box(fltk.FL_FLAT_BOX)
        self._title = title
        self._drag = None
        bx = x + w - 3 * _BTN_W
        self._btns = [
            _CaptionBtn(bx, y, _BTN_W, h, "min", lambda wid: win.iconize()),
            _CaptionBtn(bx + _BTN_W, y, _BTN_W, h, "max",
                        lambda wid: self.toggle_max()),
            _CaptionBtn(bx + 2 * _BTN_W, y, _BTN_W, h, "close",
                        lambda wid: win.do_callback()),
        ]
        self.end()

    def resize(self, x, y, w, h):
        super().resize(x, y, w, h)
        bx = x + w - 3 * _BTN_W
        for i, b in enumerate(self._btns):
            b.resize(bx + i * _BTN_W, y, _BTN_W, h)

    def draw(self):
        super().draw()
        fltk.fl_color(theme.TEXT)
        fltk.fl_font(fltk.FL_HELVETICA_BOLD, 12)
        fltk.fl_draw(self._title, self.x() + 8, self.y(),
                     self.w() - 3 * _BTN_W - 16, self.h(), fltk.FL_ALIGN_LEFT)

    def toggle_max(self):
        if self.win.maximize_active():
            self.win.un_maximize()
        else:
            self.win.maximize()

    def handle(self, event):
        if (event == fltk.FL_PUSH
                and fltk.Fl.event_button() == fltk.FL_LEFT_MOUSE):
            if super().handle(event):  # caption buttons first
                return 1
            if fltk.Fl.event_clicks():
                self.toggle_max()
                return 1
            self._drag = (fltk.Fl.event_x_root() - self.win.x(),
                          fltk.Fl.event_y_root() - self.win.y())
            return 1
        if event == fltk.FL_DRAG and self._drag:
            if self.win.maximize_active():
                self.win.un_maximize()
                self._drag = (self.win.w() // 2, TITLEBAR_H // 2)
            self.win.position(fltk.Fl.event_x_root() - self._drag[0],
                              fltk.Fl.event_y_root() - self._drag[1])
            return 1
        if event == fltk.FL_RELEASE:
            self._drag = None
        return super().handle(event)


_CURSORS = {
    "": fltk.FL_CURSOR_DEFAULT,
    "l": fltk.FL_CURSOR_WE, "r": fltk.FL_CURSOR_WE,
    "t": fltk.FL_CURSOR_NS, "b": fltk.FL_CURSOR_NS,
    "tl": fltk.FL_CURSOR_NWSE, "br": fltk.FL_CURSOR_NWSE,
    "tr": fltk.FL_CURSOR_NESW, "bl": fltk.FL_CURSOR_NESW,
}


class BorderlessWindow(fltk.Fl_Double_Window):
    """Undecorated top-level window with edge-drag resizing."""

    def __init__(self, w, h, title):
        super().__init__(w, h, title)
        self.border(0)
        self._rs = None

    def _zone(self, ex, ey) -> str:
        if self.maximize_active():
            return ""
        v = "t" if ey < _EDGE else ("b" if ey >= self.h() - _EDGE else "")
        s = "l" if ex < _EDGE else ("r" if ex >= self.w() - _EDGE else "")
        return v + s

    def handle(self, event):
        if event in (fltk.FL_MOVE, fltk.FL_ENTER, fltk.FL_LEAVE):
            z = "" if event == fltk.FL_LEAVE else self._zone(
                fltk.Fl.event_x(), fltk.Fl.event_y())
            self.cursor(_CURSORS[z])
        elif (event == fltk.FL_PUSH
              and fltk.Fl.event_button() == fltk.FL_LEFT_MOUSE):
            z = self._zone(fltk.Fl.event_x(), fltk.Fl.event_y())
            if z:
                self._rs = (z, self.x(), self.y(), self.w(), self.h(),
                            fltk.Fl.event_x_root(), fltk.Fl.event_y_root())
                return 1
        elif event == fltk.FL_DRAG and self._rs:
            z, x0, y0, w0, h0, mx, my = self._rs
            dx = fltk.Fl.event_x_root() - mx
            dy = fltk.Fl.event_y_root() - my
            x, y, w, h = x0, y0, w0, h0
            if "l" in z:
                x, w = x0 + dx, w0 - dx
            elif "r" in z:
                w = w0 + dx
            if "t" in z:
                y, h = y0 + dy, h0 - dy
            elif "b" in z:
                h = h0 + dy
            if w < _MIN_W:
                if "l" in z:
                    x = x0 + w0 - _MIN_W
                w = _MIN_W
            if h < _MIN_H:
                if "t" in z:
                    y = y0 + h0 - _MIN_H
                h = _MIN_H
            self.resize(x, y, w, h)
            return 1
        elif event == fltk.FL_RELEASE and self._rs:
            self._rs = None
            return 1
        return super().handle(event)
