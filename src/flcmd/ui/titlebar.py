"""Custom compact title bar for undecorated (border(0)) windows: drag to
move, double-click or button to maximize, minimize/close buttons, and a
window subclass that restores edge-drag resizing (lost with the native
frame). Saves the OS title bar height -- notably tall on Windows.

Windows notes: FLTK creates border(0) windows with WS_EX_TOOLWINDOW (no
taskbar button; minimizing collapses to a desktop strip), so the native
styles are patched after show(). Maximize is done manually against the
monitor work area -- FLTK's maximize() compensates for frame decorations
this window does not have and leaves a gap above the taskbar."""

import ctypes
import sys

import fltk

from . import theme
from .buttons import HoverButton

TITLEBAR_H = 24
_BTN_W = 34
_EDGE = 5  # resize grip margin, px
_MIN_W, _MIN_H = 400, 300
IS_WIN = sys.platform == "win32"

if IS_WIN:
    # PyDLL, not windll: SetWindowLongPtr/SetWindowPos/ShowWindow send
    # messages synchronously to FLTK's WndProc, whose pyfltk callbacks
    # need the GIL held (see docs/NOTES-pyfltk-win32-dnd.md). Exact
    # prototypes: default int marshalling truncates HWNDs.
    _u32 = ctypes.PyDLL("user32")
    _u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _u32.GetWindowLongPtrW.argtypes = (ctypes.c_void_p, ctypes.c_int)
    _u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _u32.SetWindowLongPtrW.argtypes = (ctypes.c_void_p, ctypes.c_int,
                                       ctypes.c_ssize_t)
    _u32.SetWindowPos.restype = ctypes.c_int
    _u32.SetWindowPos.argtypes = (ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_uint)
    _u32.ShowWindow.restype = ctypes.c_int
    _u32.ShowWindow.argtypes = (ctypes.c_void_p, ctypes.c_int)
    _u32.GetForegroundWindow.restype = ctypes.c_void_p
    _u32.GetForegroundWindow.argtypes = ()
    _u32.SystemParametersInfoW.restype = ctypes.c_int
    _u32.SystemParametersInfoW.argtypes = (ctypes.c_uint, ctypes.c_uint,
                                           ctypes.c_void_p, ctypes.c_uint)

    class _LOGFONTW(ctypes.Structure):
        _fields_ = [("lfHeight", ctypes.c_long), ("lfWidth", ctypes.c_long),
                    ("lfEscapement", ctypes.c_long),
                    ("lfOrientation", ctypes.c_long),
                    ("lfWeight", ctypes.c_long), ("lfItalic", ctypes.c_byte),
                    ("lfUnderline", ctypes.c_byte),
                    ("lfStrikeOut", ctypes.c_byte),
                    ("lfCharSet", ctypes.c_byte),
                    ("lfOutPrecision", ctypes.c_byte),
                    ("lfClipPrecision", ctypes.c_byte),
                    ("lfQuality", ctypes.c_byte),
                    ("lfPitchAndFamily", ctypes.c_byte),
                    ("lfFaceName", ctypes.c_wchar * 32)]

    class _NONCLIENTMETRICSW(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint),
                    ("iBorderWidth", ctypes.c_int),
                    ("iScrollWidth", ctypes.c_int),
                    ("iScrollHeight", ctypes.c_int),
                    ("iCaptionWidth", ctypes.c_int),
                    ("iCaptionHeight", ctypes.c_int),
                    ("lfCaptionFont", _LOGFONTW),
                    ("iSmCaptionWidth", ctypes.c_int),
                    ("iSmCaptionHeight", ctypes.c_int),
                    ("lfSmCaptionFont", _LOGFONTW),
                    ("iMenuWidth", ctypes.c_int),
                    ("iMenuHeight", ctypes.c_int),
                    ("lfMenuFont", _LOGFONTW),
                    ("lfStatusFont", _LOGFONTW),
                    ("lfMessageFont", _LOGFONTW),
                    ("iPaddedBorderWidth", ctypes.c_int)]


_caption_font: tuple | None = None  # (Fl_Font, size), resolved lazily


def caption_font() -> tuple:
    """The OS window-caption font (face, weight and size from the
    current Windows settings); FLTK default elsewhere / on failure."""
    global _caption_font
    if _caption_font is None:
        _caption_font = (fltk.FL_HELVETICA, 12)
        if IS_WIN:
            try:
                ncm = _NONCLIENTMETRICSW()
                ncm.cbSize = ctypes.sizeof(ncm)
                if _u32.SystemParametersInfoW(0x29, ncm.cbSize,
                                              ctypes.byref(ncm), 0):
                    lf = ncm.lfCaptionFont
                    # FLTK face prefix: ' ' plain, 'B' bold
                    face = ("B" if lf.lfWeight >= 600 else " ") + lf.lfFaceName
                    fltk.Fl.set_font(fltk.FL_FREE_FONT, face)
                    size = -lf.lfHeight if lf.lfHeight < 0 else lf.lfHeight
                    _caption_font = (fltk.FL_FREE_FONT, max(10, size))
            except Exception:
                pass
    return _caption_font


class _CaptionBtn(HoverButton):
    """Minimize / maximize-restore / close buttons, line-drawn glyphs."""

    def __init__(self, x, y, w, h, kind, win, cb):
        super().__init__(x, y, w, h)
        self.kind = kind
        self.win = win
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
            if self.win.is_maximized():  # restore: two offset squares
                fltk.fl_rect(cx - g, cy - g + 3, 2 * g - 2, 2 * g - 2)
                fltk.fl_line(cx - g + 2, cy - g + 1, cx + g, cy - g + 1)
                fltk.fl_line(cx + g, cy - g + 1, cx + g, cy + g - 3)
            else:
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
            _CaptionBtn(bx, y, _BTN_W, h, "min", win,
                        lambda wid: win.minimize()),
            _CaptionBtn(bx + _BTN_W, y, _BTN_W, h, "max", win,
                        lambda wid: win.toggle_maximize()),
            _CaptionBtn(bx + 2 * _BTN_W, y, _BTN_W, h, "close", win,
                        lambda wid: win.do_callback()),
        ]
        self.end()
        # FLTK does not reliably hand the window FL_FOCUS on OS
        # re-activation; poll the activation state instead
        self._active = True
        fltk.Fl.add_timeout(0.3, self._poll_active)

    def _is_active(self) -> bool:
        if IS_WIN:
            return _u32.GetForegroundWindow() == fltk.fl_xid(self.win)
        return fltk.Fl.focus() is not None

    def _poll_active(self, data=None):
        if self.win.shown():
            a = self._is_active()
            if a != self._active:
                self._active = a
                self.redraw()
        fltk.Fl.repeat_timeout(0.3, self._poll_active)

    def resize(self, x, y, w, h):
        super().resize(x, y, w, h)
        bx = x + w - 3 * _BTN_W
        for i, b in enumerate(self._btns):
            b.resize(bx + i * _BTN_W, y, _BTN_W, h)

    def draw(self):
        super().draw()
        # focus feedback like TC: same background, clearer text when active
        fltk.fl_color(theme.TEXT if self._active else theme.TITLE_IDLE)
        fltk.fl_font(*caption_font())
        fltk.fl_draw(self._title, self.x() + 8, self.y(),
                     self.w() - 3 * _BTN_W - 16, self.h(), fltk.FL_ALIGN_LEFT)

    def handle(self, event):
        if (event == fltk.FL_PUSH
                and fltk.Fl.event_button() == fltk.FL_LEFT_MOUSE):
            if super().handle(event):  # caption buttons first
                return 1
            if fltk.Fl.event_clicks():
                self.win.toggle_maximize()
                return 1
            self._drag = (fltk.Fl.event_x_root() - self.win.x(),
                          fltk.Fl.event_y_root() - self.win.y())
            return 1
        if event == fltk.FL_DRAG and self._drag:
            if self.win.is_maximized():
                self.win.toggle_maximize()  # drag off the maximized state
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
    """Undecorated top-level window with edge-drag resizing, taskbar
    presence on Windows, and manual maximize to the work area."""

    def __init__(self, w, h, title):
        super().__init__(w, h, title)
        self.border(0)
        self._rs = None
        self._max_saved = None  # geometry to restore from maximized

    # -- native window fixes (Windows) ----------------------------------
    def show(self, *args):
        super().show(*args)
        if IS_WIN:
            self._fix_win_styles()

    def _fix_win_styles(self):
        """border(0) FLTK windows get WS_EX_TOOLWINDOW: no taskbar entry
        and minimize-to-desktop-strip. Patch the styles in place."""
        hwnd = fltk.fl_xid(self)
        GWL_STYLE, GWL_EXSTYLE = -16, -20
        WS_MINIMIZEBOX, WS_MAXIMIZEBOX = 0x00020000, 0x00010000
        WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = 0x00000080, 0x00040000
        st = _u32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        _u32.SetWindowLongPtrW(hwnd, GWL_STYLE,
                               st | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
        ex = _u32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        _u32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE,
                               (ex | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW)
        # SWP_NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED: apply the style change
        _u32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x27)

    # -- caption actions -------------------------------------------------
    def minimize(self):
        if IS_WIN:
            _u32.ShowWindow(fltk.fl_xid(self), 6)  # SW_MINIMIZE
        else:
            self.iconize()

    def is_maximized(self) -> bool:
        return self._max_saved is not None

    def toggle_maximize(self):
        if self._max_saved is not None:
            x, y, w, h = self._max_saved
            self._max_saved = None
            self.resize(x, y, w, h)
        else:
            self._max_saved = (self.x(), self.y(), self.w(), self.h())
            wx, wy, ww, wh = fltk.Fl.screen_work_area(
                self.x() + self.w() // 2, self.y() + self.h() // 2)
            self.resize(wx, wy, ww, wh)

    # -- edge resize ------------------------------------------------------
    def _zone(self, ex, ey) -> str:
        if self.is_maximized():
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
