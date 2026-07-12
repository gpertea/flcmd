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
PropModeReplace, CurrentTime, XA_ATOM = 0, 0, 4
XC_HAND2 = 60
GrabModeAsync, GrabSuccess = 1, 0


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
    return _x


class _XcursorImage(C.Structure):
    _fields_ = [("version", C.c_uint), ("size", C.c_uint),
                ("width", C.c_uint), ("height", C.c_uint),
                ("xhot", C.c_uint), ("yhot", C.c_uint),
                ("delay", C.c_uint), ("pixels", C.POINTER(C.c_uint32))]


# classic arrow pointer, 12x17: B outline, W fill, . transparent
_ARROW = (
    "B...........",
    "BB..........",
    "BWB.........",
    "BWWB........",
    "BWWWB.......",
    "BWWWWB......",
    "BWWWWWB.....",
    "BWWWWWWB....",
    "BWWWWWWWB...",
    "BWWWWWWWWB..",
    "BWWWWWBBBBB.",
    "BWWBWWB.....",
    "BWB.BWWB....",
    "BB..BWWB....",
    "B....BWWB...",
    ".....BWWB...",
    "......BB....",
)


def _paint_doc(px, size, x0, y0, w=13, h=16):
    """Draw a little document (border, fold, text lines) into the buffer."""
    border, paper, ink = 0xFF404040, 0xFFFFFFFF, 0xFFA0A0A0
    fold = 4
    for yy in range(h):
        for xx in range(w):
            gx, gy = x0 + xx, y0 + yy
            if not (0 <= gx < size and 0 <= gy < size):
                continue
            if xx >= w - fold and yy < fold:      # folded corner cut
                if xx - (w - fold) == yy:         # fold diagonal
                    px[gy * size + gx] = border
                continue
            edge = (xx in (0, w - 1) or yy in (0, h - 1)
                    or (yy == fold and xx >= w - fold - 1)
                    or (xx == w - fold - 1 and yy <= fold))
            if edge:
                px[gy * size + gx] = border
            elif yy in (5, 8, 11) and 2 < xx < w - 3:
                px[gy * size + gx] = ink
            else:
                px[gy * size + gx] = paper


def _drag_cursor(x, dpy, count: int) -> int:
    """Arrow pointer with a document symbol (two documents when dragging
    several files); themed/font-cursor fallbacks."""
    try:
        xc = C.CDLL("libXcursor.so.1")
        xc.XcursorImageCreate.restype = C.POINTER(_XcursorImage)
        xc.XcursorImageCreate.argtypes = [C.c_int, C.c_int]
        xc.XcursorImageLoadCursor.restype = C.c_ulong
        xc.XcursorImageLoadCursor.argtypes = [C.c_void_p, C.c_void_p]
        xc.XcursorImageDestroy.argtypes = [C.c_void_p]
        size = 32
        img = xc.XcursorImageCreate(size, size)
        im = img.contents
        im.xhot, im.yhot = 1, 1
        px = im.pixels
        for i in range(size * size):
            px[i] = 0
        if count > 1:
            _paint_doc(px, size, 17, 12)          # second doc peeking behind
        _paint_doc(px, size, 13, 15)
        for yy, row in enumerate(_ARROW):
            for xx, ch in enumerate(row):
                if ch == "B":
                    px[yy * size + xx] = 0xFF000000
                elif ch == "W":
                    px[yy * size + xx] = 0xFFFFFFFF
        cur = xc.XcursorImageLoadCursor(dpy, img)
        xc.XcursorImageDestroy(img)
        if cur:
            return cur
        xc.XcursorLibraryLoadCursor.restype = C.c_ulong
        xc.XcursorLibraryLoadCursor.argtypes = [C.c_void_p, C.c_char_p]
        for name in (b"dnd-copy", b"copy", b"grabbing"):
            cur = xc.XcursorLibraryLoadCursor(dpy, name)
            if cur:
                return cur
    except OSError:
        pass
    return x.XCreateFontCursor(dpy, XC_HAND2)


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
    # visual feedback: arrow+document drag cursor on the pointer grab
    mask = ButtonReleaseMask | PointerMotionMask | ButtonMotionMask
    cursor = _drag_cursor(x, dpy, len(file_paths))
    grabbed = x.XGrabPointer(dpy, src_win, 0, mask, GrabModeAsync,
                             GrabModeAsync, 0, cursor, CurrentTime)
    _dbg(f"XGrabPointer -> {grabbed}")
    if grabbed != GrabSuccess:  # keep the implicit grab, just set the cursor
        x.XChangeActivePointerGrab(dpy, mask, cursor, CurrentTime)

    target = tver = 0
    accepted = dropped = finished = False
    ev = XEvent()
    try:
        while not dropped:
            x.XNextEvent(dpy, C.byref(ev))
            if ev.type == MotionNotify:
                while x.XCheckTypedEvent(dpy, MotionNotify, C.byref(ev)):
                    pass  # compress queued motion
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
        x.XUngrabPointer(dpy, CurrentTime)
        x.XFreeCursor(dpy, cursor)
        x.XSetSelectionOwner(dpy, A["XdndSelection"], 0, CurrentTime)
        x.XFlush(dpy)
