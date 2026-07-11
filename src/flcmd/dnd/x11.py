"""XDND drag source over FLTK's own X11 connection (ctypes, no extra deps).

FLTK cannot drag files out, only text. This speaks the XDND protocol
directly: during the drag we run a nested event loop on FLTK's Display --
the X server's implicit pointer grab from the initiating button press
belongs to that connection, so motion/release/SelectionRequest events all
arrive here while FLTK's loop is paused inside the widget's handle().
Works under XWayland too (the compositor bridges XDND to Wayland apps).
"""

import ctypes as C
import ctypes.util
import os
import sys
import time
import urllib.parse

_DEBUG = bool(os.environ.get("FLCMD_DND_DEBUG"))


def _dbg(*args):
    if _DEBUG:
        print("[dnd]", *args, file=sys.stderr, flush=True)

Window = Atom = Time = C.c_ulong

# X protocol constants
ButtonRelease, MotionNotify, Expose = 5, 6, 12
SelectionClear, SelectionRequest, SelectionNotify, ClientMessage = 29, 30, 31, 33
ButtonReleaseMask, PointerMotionMask, ButtonMotionMask = 1 << 3, 1 << 6, 1 << 13
ExposureMask = 1 << 15
PropModeReplace, CurrentTime, XA_ATOM = 0, 0, 4
XC_HAND2 = 60
GrabModeAsync, GrabSuccess = 1, 0
CWOverrideRedirect = 1 << 9


class _XSetWindowAttributes(C.Structure):
    _fields_ = [("background_pixmap", C.c_ulong), ("background_pixel", C.c_ulong),
                ("border_pixmap", C.c_ulong), ("border_pixel", C.c_ulong),
                ("bit_gravity", C.c_int), ("win_gravity", C.c_int),
                ("backing_store", C.c_int), ("backing_planes", C.c_ulong),
                ("backing_pixel", C.c_ulong), ("save_under", C.c_int),
                ("event_mask", C.c_long), ("do_not_propagate_mask", C.c_long),
                ("override_redirect", C.c_int), ("colormap", C.c_ulong),
                ("cursor", C.c_ulong)]


class _XAny(C.Structure):
    _fields_ = [("type", C.c_int), ("serial", C.c_ulong), ("send_event", C.c_int),
                ("display", C.c_void_p), ("window", Window)]


class _CMData(C.Union):
    _fields_ = [("b", C.c_char * 20), ("s", C.c_short * 10), ("l", C.c_long * 5)]


class _XClientMessage(C.Structure):
    _fields_ = _XAny._fields_ + [("message_type", Atom), ("format", C.c_int),
                                 ("data", _CMData)]


class _XMotion(C.Structure):
    _fields_ = _XAny._fields_ + [
        ("root", Window), ("subwindow", Window), ("time", Time),
        ("x", C.c_int), ("y", C.c_int), ("x_root", C.c_int), ("y_root", C.c_int),
        ("state", C.c_uint), ("is_hint", C.c_char), ("same_screen", C.c_int)]


class _XButton(C.Structure):
    _fields_ = _XAny._fields_ + [
        ("root", Window), ("subwindow", Window), ("time", Time),
        ("x", C.c_int), ("y", C.c_int), ("x_root", C.c_int), ("y_root", C.c_int),
        ("state", C.c_uint), ("button", C.c_uint), ("same_screen", C.c_int)]


class _XSelReq(C.Structure):
    _fields_ = [("type", C.c_int), ("serial", C.c_ulong), ("send_event", C.c_int),
                ("display", C.c_void_p), ("owner", Window), ("requestor", Window),
                ("selection", Atom), ("target", Atom), ("property", Atom),
                ("time", Time)]


class _XSelNotify(C.Structure):
    _fields_ = [("type", C.c_int), ("serial", C.c_ulong), ("send_event", C.c_int),
                ("display", C.c_void_p), ("requestor", Window), ("selection", Atom),
                ("target", Atom), ("property", Atom), ("time", Time)]


class XEvent(C.Union):
    _fields_ = [("type", C.c_int), ("xany", _XAny), ("xclient", _XClientMessage),
                ("xmotion", _XMotion), ("xbutton", _XButton),
                ("xselectionrequest", _XSelReq), ("xselection", _XSelNotify),
                ("pad", C.c_long * 24)]


_x = None
_dpy = None


def _xlib():
    global _x
    if _x is None:
        _x = C.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        _x.XInternAtom.restype = Atom
        _x.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]
        _x.XDefaultRootWindow.restype = Window
        _x.XDefaultRootWindow.argtypes = [C.c_void_p]
        _x.XGetSelectionOwner.restype = Window
        _x.XGetSelectionOwner.argtypes = [C.c_void_p, Atom]
        _x.XSetSelectionOwner.argtypes = [C.c_void_p, Atom, Window, Time]
        _x.XSendEvent.argtypes = [C.c_void_p, Window, C.c_int, C.c_long, C.c_void_p]
        _x.XNextEvent.argtypes = [C.c_void_p, C.c_void_p]
        _x.XPending.argtypes = [C.c_void_p]
        _x.XCheckTypedEvent.argtypes = [C.c_void_p, C.c_int, C.c_void_p]
        _x.XFlush.argtypes = [C.c_void_p]
        _x.XChangeProperty.argtypes = [C.c_void_p, Window, Atom, Atom, C.c_int,
                                       C.c_int, C.c_char_p, C.c_int]
        _x.XQueryPointer.argtypes = [C.c_void_p, Window] + [C.c_void_p] * 7
        _x.XGetWindowProperty.argtypes = [C.c_void_p, Window, Atom, C.c_long,
                                          C.c_long, C.c_int, Atom] + [C.c_void_p] * 5
        _x.XFree.argtypes = [C.c_void_p]
        _x.XCreateFontCursor.restype = C.c_ulong
        _x.XCreateFontCursor.argtypes = [C.c_void_p, C.c_uint]
        _x.XChangeActivePointerGrab.argtypes = [C.c_void_p, C.c_uint, C.c_ulong, Time]
        _x.XGrabPointer.restype = C.c_int
        _x.XGrabPointer.argtypes = [C.c_void_p, Window, C.c_int, C.c_uint,
                                    C.c_int, C.c_int, Window, C.c_ulong, Time]
        _x.XUngrabPointer.argtypes = [C.c_void_p, Time]
        _x.XFreeCursor.argtypes = [C.c_void_p, C.c_ulong]
        _x.XCreateSimpleWindow.restype = Window
        _x.XCreateSimpleWindow.argtypes = [C.c_void_p, Window, C.c_int, C.c_int,
                                           C.c_uint, C.c_uint, C.c_uint,
                                           C.c_ulong, C.c_ulong]
        _x.XChangeWindowAttributes.argtypes = [C.c_void_p, Window, C.c_ulong,
                                               C.c_void_p]
        _x.XSelectInput.argtypes = [C.c_void_p, Window, C.c_long]
        _x.XMapRaised.argtypes = [C.c_void_p, Window]
        _x.XMoveWindow.argtypes = [C.c_void_p, Window, C.c_int, C.c_int]
        _x.XDestroyWindow.argtypes = [C.c_void_p, Window]
        _x.XCreateGC.restype = C.c_void_p
        _x.XCreateGC.argtypes = [C.c_void_p, Window, C.c_ulong, C.c_void_p]
        _x.XFreeGC.argtypes = [C.c_void_p, C.c_void_p]
        _x.XSetForeground.argtypes = [C.c_void_p, C.c_void_p, C.c_ulong]
        _x.XDrawString.argtypes = [C.c_void_p, Window, C.c_void_p, C.c_int,
                                   C.c_int, C.c_char_p, C.c_int]
        _x.XBlackPixel.restype = C.c_ulong
        _x.XBlackPixel.argtypes = [C.c_void_p, C.c_int]
        _x.XWhitePixel.restype = C.c_ulong
        _x.XWhitePixel.argtypes = [C.c_void_p, C.c_int]
    return _x


def _dnd_cursor(x, dpy) -> int:
    """A themed dnd/copy cursor if libXcursor has one, else the hand."""
    try:
        xc = C.CDLL("libXcursor.so.1")
        xc.XcursorLibraryLoadCursor.restype = C.c_ulong
        xc.XcursorLibraryLoadCursor.argtypes = [C.c_void_p, C.c_char_p]
        for name in (b"dnd-copy", b"copy", b"dnd-move", b"grabbing"):
            cur = xc.XcursorLibraryLoadCursor(dpy, name)
            if cur:
                return cur
    except OSError:
        pass
    return x.XCreateFontCursor(dpy, XC_HAND2)


class _DragIcon:
    """Small override-redirect window following the pointer during a drag."""

    def __init__(self, x, dpy, root, label: str):
        self.x, self.dpy = x, dpy
        self.label = label.encode("utf-8", "replace")
        self.w = 7 * len(label) + 18
        black, white = x.XBlackPixel(dpy, 0), x.XWhitePixel(dpy, 0)
        self.win = x.XCreateSimpleWindow(dpy, root, -100, -100, self.w, 20,
                                         1, black, white)
        attrs = _XSetWindowAttributes()
        attrs.override_redirect = 1
        x.XChangeWindowAttributes(dpy, self.win, CWOverrideRedirect,
                                  C.byref(attrs))
        x.XSelectInput(dpy, self.win, ExposureMask)
        self.gc = x.XCreateGC(dpy, self.win, 0, None)
        x.XSetForeground(dpy, self.gc, black)
        x.XMapRaised(dpy, self.win)

    def move(self, px: int, py: int):
        self.x.XMoveWindow(self.dpy, self.win, px + 14, py + 12)

    def expose(self):
        self.x.XDrawString(self.dpy, self.win, self.gc, 8, 14,
                           self.label, len(self.label))

    def destroy(self):
        self.x.XFreeGC(self.dpy, self.gc)
        self.x.XDestroyWindow(self.dpy, self.win)
        self.x.XFlush(self.dpy)


def _fltk_display() -> int:
    """FLTK's Display* -- the fl_display global exported by libfltk."""
    global _dpy
    if _dpy:
        return _dpy
    for name in (None, "libfltk.so.1.4", "libfltk.so", "libfltk.1.4.dylib"):
        try:
            d = C.c_void_p.in_dll(C.CDLL(name), "fl_display")
            if d.value:
                _dpy = d.value
                return _dpy
        except (OSError, ValueError):
            continue
    raise RuntimeError("cannot locate FLTK's X display (fl_display)")


def _atoms(x, dpy):
    names = ["XdndAware", "XdndSelection", "XdndEnter", "XdndPosition",
             "XdndStatus", "XdndLeave", "XdndDrop", "XdndFinished",
             "XdndActionCopy", "text/uri-list", "text/plain", "UTF8_STRING",
             "TARGETS"]
    return {n: x.XInternAtom(dpy, n.encode(), 0) for n in names}


def _aware_version(x, dpy, win, aware_atom) -> int:
    at, af = Atom(), C.c_int()
    ni, ba, data = C.c_ulong(), C.c_ulong(), C.c_void_p()
    r = x.XGetWindowProperty(dpy, win, aware_atom, 0, 1, 0, XA_ATOM,
                             C.byref(at), C.byref(af), C.byref(ni),
                             C.byref(ba), C.byref(data))
    ver = 0
    if r == 0 and data.value and ni.value:
        ver = C.cast(data.value, C.POINTER(C.c_ulong))[0]
    if data.value:
        x.XFree(data)
    return min(5, ver)


def _target_under_pointer(x, dpy, root, aware_atom) -> tuple[int, int]:
    """Descend from root; the XdndAware window on the path is the target."""
    win, aware, ver = root, 0, 0
    while True:
        v = _aware_version(x, dpy, win, aware_atom)
        if v:
            aware, ver = win, v
        r, child = Window(), Window()
        rx, ry, wx, wy, mask = (C.c_int(), C.c_int(), C.c_int(), C.c_int(),
                                C.c_uint())
        if not x.XQueryPointer(dpy, win, C.byref(r), C.byref(child),
                               C.byref(rx), C.byref(ry), C.byref(wx),
                               C.byref(wy), C.byref(mask)) or not child.value:
            break
        win = child.value
    return aware, ver


def _send_cm(x, dpy, target, mtype, l0=0, l1=0, l2=0, l3=0, l4=0):
    ev = XEvent()
    ev.xclient.type = ClientMessage
    ev.xclient.window = target
    ev.xclient.message_type = mtype
    ev.xclient.format = 32
    for i, v in enumerate((l0, l1, l2, l3, l4)):
        ev.xclient.data.l[i] = v
    x.XSendEvent(dpy, target, 0, 0, C.byref(ev))
    x.XFlush(dpy)


def _convert_selection(x, dpy, ev, A, uris: bytes, plain: bytes):
    req = ev.xselectionrequest
    prop = req.property or req.target
    ok = True
    if req.target == A["text/uri-list"]:
        x.XChangeProperty(dpy, req.requestor, prop, req.target, 8,
                          PropModeReplace, uris, len(uris))
    elif req.target in (A["UTF8_STRING"], A["text/plain"]):
        x.XChangeProperty(dpy, req.requestor, prop, req.target, 8,
                          PropModeReplace, plain, len(plain))
    elif req.target == A["TARGETS"]:
        arr = (Atom * 4)(A["TARGETS"], A["text/uri-list"], A["UTF8_STRING"],
                         A["text/plain"])
        x.XChangeProperty(dpy, req.requestor, prop, XA_ATOM, 32,
                          PropModeReplace, C.cast(arr, C.c_char_p), 4)
    else:
        ok = False
    rep = XEvent()
    rep.xselection.type = SelectionNotify
    rep.xselection.requestor = req.requestor
    rep.xselection.selection = req.selection
    rep.xselection.target = req.target
    rep.xselection.property = prop if ok else 0
    rep.xselection.time = req.time
    x.XSendEvent(dpy, req.requestor, 0, 0, C.byref(rep))
    x.XFlush(dpy)


def drag_files(src_win: int, file_paths: list[str], own_xids=()) -> bool:
    """Nested-loop XDND source. Call from inside a mouse-drag handler."""
    x = _xlib()
    dpy = _fltk_display()
    A = _atoms(x, dpy)
    root = x.XDefaultRootWindow(dpy)
    own = set(own_xids) | {src_win}

    uris = "".join("file://" + urllib.parse.quote(p) + "\r\n"
                   for p in file_paths).encode()
    plain = "\n".join(file_paths).encode()

    _dbg(f"drag start: src={src_win:#x} files={file_paths}")
    x.XSetSelectionOwner(dpy, A["XdndSelection"], src_win, CurrentTime)
    if x.XGetSelectionOwner(dpy, A["XdndSelection"]) != src_win:
        _dbg("failed to own XdndSelection")
        return False
    # visual feedback: dnd cursor on the grab + a label following the pointer
    mask = ButtonReleaseMask | PointerMotionMask | ButtonMotionMask
    cursor = _dnd_cursor(x, dpy)
    grabbed = x.XGrabPointer(dpy, src_win, 0, mask, GrabModeAsync,
                             GrabModeAsync, 0, cursor, CurrentTime)
    _dbg(f"XGrabPointer -> {grabbed}")
    if grabbed != GrabSuccess:  # keep the implicit grab, just set the cursor
        x.XChangeActivePointerGrab(dpy, mask, cursor, CurrentTime)
    n = len(file_paths)
    icon = _DragIcon(x, dpy, root,
                     file_paths[0].rsplit("/", 1)[-1] if n == 1
                     else f"{n} items")
    own.add(icon.win)

    target = tver = 0
    accepted = dropped = finished = False
    ev = XEvent()
    try:
        while not dropped:
            x.XNextEvent(dpy, C.byref(ev))
            if ev.type == MotionNotify:
                while x.XCheckTypedEvent(dpy, MotionNotify, C.byref(ev)):
                    pass  # compress queued motion
                icon.move(ev.xmotion.x_root, ev.xmotion.y_root)
                tgt, ver = _target_under_pointer(x, dpy, root, A["XdndAware"])
                if tgt in own:
                    tgt = 0  # own windows can't answer: FLTK loop is paused
                if tgt != target:
                    _dbg(f"target change {target:#x} -> {tgt:#x} v{ver}")
                    if target:
                        _send_cm(x, dpy, target, A["XdndLeave"], src_win)
                    target, tver, accepted = tgt, ver, False
                    if target:
                        _send_cm(x, dpy, target, A["XdndEnter"], src_win,
                                 tver << 24, A["text/uri-list"],
                                 A["text/plain"], 0)
                if target:
                    _send_cm(x, dpy, target, A["XdndPosition"], src_win, 0,
                             (ev.xmotion.x_root << 16) | ev.xmotion.y_root,
                             ev.xmotion.time, A["XdndActionCopy"])
            elif ev.type == ClientMessage:
                if ev.xclient.message_type == A["XdndStatus"]:
                    accepted = bool(ev.xclient.data.l[1] & 1)
                    _dbg(f"XdndStatus accepted={accepted}")
            elif ev.type == Expose and ev.xany.window == icon.win:
                icon.expose()
            elif ev.type == SelectionRequest:
                _dbg("SelectionRequest (pre-drop)")
                _convert_selection(x, dpy, ev, A, uris, plain)
            elif ev.type == ButtonRelease:
                _dbg(f"release: target={target:#x} accepted={accepted}")
                drop_time = ev.xbutton.time
                if target and not accepted:
                    # XdndStatus for the last XdndPosition may still be in
                    # flight (fast drags); give the target a moment to answer
                    end = time.monotonic() + 0.5
                    ev2 = XEvent()
                    while not accepted and time.monotonic() < end:
                        while x.XPending(dpy):
                            x.XNextEvent(dpy, C.byref(ev2))
                            if (ev2.type == ClientMessage and
                                    ev2.xclient.message_type == A["XdndStatus"]):
                                accepted = bool(ev2.xclient.data.l[1] & 1)
                            elif ev2.type == SelectionRequest:
                                _convert_selection(x, dpy, ev2, A, uris, plain)
                        time.sleep(0.005)
                if target and accepted:
                    _dbg("sending XdndDrop")
                    _send_cm(x, dpy, target, A["XdndDrop"], src_win, 0,
                             drop_time)
                    dropped = True
                else:
                    _dbg("drop refused / no target")
                    if target:
                        _send_cm(x, dpy, target, A["XdndLeave"], src_win)
                    return False
            elif ev.type == SelectionClear:
                return False
        # serve data requests until the target reports XdndFinished
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not finished:
            while x.XPending(dpy):
                x.XNextEvent(dpy, C.byref(ev))
                if ev.type == SelectionRequest:
                    _convert_selection(x, dpy, ev, A, uris, plain)
                elif (ev.type == ClientMessage
                      and ev.xclient.message_type == A["XdndFinished"]):
                    finished = True
                    break
            time.sleep(0.005)
        return True  # drop was sent and accepted
    finally:
        icon.destroy()
        x.XUngrabPointer(dpy, CurrentTime)
        x.XFreeCursor(dpy, cursor)
        x.XSetSelectionOwner(dpy, A["XdndSelection"], 0, CurrentTime)
        x.XFlush(dpy)
