"""Built-in file viewer, a TC Lister equivalent: text (UTF-8 by default,
ASCII-only option) and hex modes, line wrap, search, configurable font --
persisted in flcmd.ini [viewer]. Files of ANY size open instantly: only a
sliding window (window_mb, default 8 MB) is held in memory; the right-hand
scrollbar maps the whole file, the window follows scrolling and search
streams over the file on disk. Standalone: `flcmd-view FILE...` (n/p moves
between files). Keys: 1 text, 3 hex, W wrap, A ascii, F7/Ctrl+F search,
F3 next, Shift+F3 previous, Ctrl+Home/End file start/end, Q/Esc close."""

import os
import subprocess
import sys

import fltk

from .. import config, paths

MENU_H, STATUS_H, FBAR_W = 25, 20, 16
FONTS = {"courier": fltk.FL_COURIER, "helvetica": fltk.FL_HELVETICA,
         "times": fltk.FL_TIMES, "screen": fltk.FL_SCREEN}
SIZES = (9, 10, 11, 12, 14, 16, 18, 20)
DEFAULTS = {"font": "courier", "size": 12, "wrap": True, "ascii": False,
            "mode": "text", "window_mb": 8}
HEXW = 77  # fixed hex line width incl newline: 10 + 48 + 2 + 16 + 1


def _hexdump(data: bytes, base: int = 0) -> str:
    out = []
    for off in range(0, len(data), 16):
        row = data[off:off + 16]
        hx = " ".join(f"{b:02x}" for b in row)
        hx = hx[:23] + " " + hx[23:] if len(row) > 8 else hx
        txt = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        out.append(f"{base + off:08x}  {hx:<48}  {txt}")
    return "\n".join(out)


def _asciify(text: str) -> str:
    return "".join(c if c == "\n" or c == "\t" or 32 <= ord(c) < 127 else "."
                   for c in text)


class ViewerWindow(fltk.Fl_Double_Window):
    def __init__(self, files: list[str], w=860, h=620):
        super().__init__(w, h, "flcmd-view")
        self.files = [paths.canon(f) for f in files]
        self.idx = 0
        self.opts = dict(DEFAULTS)
        self.opts.update(config.load().get("viewer", {}))
        self.search_term = ""
        self.fsize = 0
        self.win_off = 0
        self.data = b""
        self.text = ""
        self.menubar = fltk.Fl_Menu_Bar(0, 0, w, MENU_H)
        self.menubar.box(fltk.FL_THIN_UP_BOX)
        self._build_menu()
        body = fltk.Fl_Group(0, MENU_H, w, h - MENU_H - STATUS_H)
        self.disp = fltk.Fl_Text_Display(0, MENU_H, w - FBAR_W,
                                         h - MENU_H - STATUS_H)
        self.buf = fltk.Fl_Text_Buffer()
        self.disp.buffer(self.buf)
        self.fbar = fltk.Fl_Scrollbar(w - FBAR_W, MENU_H, FBAR_W,
                                      h - MENU_H - STATUS_H)
        self.fbar.type(fltk.FL_VERTICAL)
        self.fbar.callback(self._fbar_cb)
        body.resizable(self.disp)
        body.end()
        self.status = fltk.Fl_Box(0, h - STATUS_H, w, STATUS_H)
        self.status.box(fltk.FL_FLAT_BOX)
        self.status.color(fltk.fl_rgb_color(240, 240, 240))
        self.status.align(fltk.FL_ALIGN_INSIDE | fltk.FL_ALIGN_LEFT
                          | fltk.FL_ALIGN_CLIP)
        self.status.labelsize(11)
        self.end()
        self.resizable(body)
        self.load_file()
        fltk.Fl.add_timeout(0.15, self._page_poll)

    # -- menu ---------------------------------------------------------------
    def _build_menu(self):
        mb, cb = self.menubar, self._menu_cb
        mb.add("&File/&Next file\tn", 0, cb, "next")
        mb.add("&File/&Previous file\tp", 0, cb, "prev", fltk.FL_MENU_DIVIDER)
        mb.add("&File/&Close\tEsc", 0, cb, "close")
        mb.add("&Edit/&Search...\tF7", 0, cb, "search")
        mb.add("&Edit/Find &Next\tF3", 0, cb, "next_match")
        mb.add("&Edit/Find &Previous\tShift+F3", 0, cb, "prev_match")
        mb.add("&Options/&Text mode\t1", 0, cb, "mode:text")
        mb.add("&Options/&Hex mode\t3", 0, cb, "mode:hex", fltk.FL_MENU_DIVIDER)
        mb.add("&Options/&Wrap lines\tw", 0, cb, "wrap")
        mb.add("&Options/&ASCII only\ta", 0, cb, "ascii", fltk.FL_MENU_DIVIDER)
        for name in FONTS:
            mb.add(f"&Options/&Font/{name}", 0, cb, f"font:{name}")
        for s in SIZES:
            mb.add(f"&Options/Si&ze/{s}", 0, cb, f"size:{s}")

    def _menu_cb(self, wid, action):
        self.do_action(action)

    # -- windowed file access -------------------------------------------------
    def path(self) -> str:
        return self.files[self.idx]

    def _win_bytes(self) -> int:
        return max(1, int(self.opts["window_mb"])) << 20

    def _read(self, off: int, ln: int) -> bytes:
        try:
            with open(self.path(), "rb") as f:
                f.seek(off)
                return f.read(ln)
        except OSError:
            return b""

    @property
    def paged(self) -> bool:
        return self.fsize > self._win_bytes()

    def load_file(self):
        try:
            self.fsize = os.stat(self.path()).st_size
            err = None
        except OSError as e:
            err = f"cannot open {self.path()}: {e}".encode()
            self.fsize = len(err)
        if err is not None:
            self.win_off, self.data = 0, err
            self.render()
            return
        self.jump_to(0)

    def _load_window(self, off: int):
        wb = self._win_bytes()
        off = max(0, min(off, max(0, self.fsize - wb)))
        if self.opts["mode"] == "hex":
            off -= off % 16
        data = self._read(off, wb)
        if self.opts["mode"] != "hex":
            if off > 0:  # start at a whole line
                i = data.find(b"\n", 0, 1 << 16)
                if 0 <= i:
                    off += i + 1
                    data = data[i + 1:]
            if off + len(data) < self.fsize:  # end at a whole line
                j = data.rfind(b"\n")
                if j > 0:
                    data = data[:j + 1]
        self.win_off, self.data = off, data

    def jump_to(self, off: int):
        self._load_window(off)
        self.render()

    def render(self):
        o = self.opts
        if o["mode"] == "hex":
            text = _hexdump(self.data, self.win_off)
        else:
            text = self.data.decode("utf-8", errors="replace")
            if o["ascii"]:
                text = _asciify(text)
        self.text = text
        self.buf.text(text)
        self.disp.textfont(FONTS.get(o["font"], fltk.FL_COURIER))
        self.disp.textsize(int(o["size"]))
        wrap = o["wrap"] and o["mode"] == "text"
        self.disp.wrap_mode(
            fltk.Fl_Text_Display.WRAP_AT_BOUNDS if wrap
            else fltk.Fl_Text_Display.WRAP_NONE, 0)
        self.disp.insert_position(0)
        self.disp.scroll(1, 0)
        self._sync_fbar()
        self.label(f"flcmd-view - {self.path()}")
        self._status()
        self.redraw()

    # -- paging ---------------------------------------------------------------
    def _vis_rows(self) -> int:
        fltk.fl_font(FONTS.get(self.opts["font"], fltk.FL_COURIER),
                     int(self.opts["size"]))
        return max(1, self.disp.h() // max(1, fltk.fl_height()))

    def _total_rows(self) -> int:
        return self.disp.count_lines(0, self.buf.length(), True) + 1

    def _row_to_byte(self, row: int) -> int:
        """Approximate file byte offset of a 0-based display row."""
        if self.opts["mode"] == "hex":
            return self.win_off + row * 16
        total = max(1, self._total_rows())
        return self.win_off + int(len(self.data) * min(row, total) / total)

    def _byte_to_row(self, off: int) -> int:
        if self.opts["mode"] == "hex":
            return max(0, (off - self.win_off) // 16)
        ln = max(1, len(self.data))
        return int(self._total_rows() * max(0, off - self.win_off) / ln)

    def _page_poll(self, data=None):
        if not self.visible():
            fltk.Fl.repeat_timeout(0.5, self._page_poll)
            return
        if self.paged:
            top = self.disp.scroll_row() - 1
            total, vis = self._total_rows(), self._vis_rows()
            if top <= 0 and self.win_off > 0:
                self._slide(top)
            elif (top + vis >= total
                  and self.win_off + len(self.data) < self.fsize):
                self._slide(top)
            elif fltk.Fl.pushed() is not self.fbar:
                self._sync_fbar()
        fltk.Fl.repeat_timeout(0.15, self._page_poll)

    def _slide(self, top_row: int):
        """Reload the window centered on the current view position."""
        anchor = self._row_to_byte(max(0, top_row))
        self._load_window(anchor - self._win_bytes() // 2)
        self.render()
        self.disp.scroll(self._byte_to_row(anchor) + 1, 0)
        self._sync_fbar()

    def _sync_fbar(self):
        if not self.paged:
            if self.fbar.visible():
                self.fbar.hide()
                self.disp.resize(0, MENU_H, self.w(), self.disp.h())
            return
        if not self.fbar.visible():
            self.fbar.show()
            self.disp.resize(0, MENU_H, self.w() - FBAR_W, self.disp.h())
        self.fbar.activate()
        pos = self._row_to_byte(max(0, self.disp.scroll_row() - 1))
        self.fbar.value(min(pos, self.fsize), max(1, len(self.data)),
                        0, self.fsize)

    def _fbar_cb(self, wid):
        target = int(self.fbar.value())
        self.jump_to(max(0, target - (0 if target == 0 else 4096)))

    # -- status / options -------------------------------------------------------
    def _status(self):
        o = self.opts
        parts = [paths.basename(self.path()), f"{self.fsize:,} bytes",
                 o["mode"], "ascii" if o["ascii"] else "utf-8"]
        if o["wrap"] and o["mode"] == "text":
            parts.append("wrap")
        if self.paged:
            parts.append(f"{100 * self.win_off / max(1, self.fsize):.0f}%")
        if len(self.files) > 1:
            parts.append(f"file {self.idx + 1}/{len(self.files)}")
        if self.search_term:
            parts.append(f"search: {self.search_term}")
        self.status.copy_label("  " + "   ".join(str(p) for p in parts))

    def _persist(self):
        config.update("viewer", self.opts)

    def do_action(self, action: str) -> bool:
        o = self.opts
        if action == "close":
            self.hide()
        elif action == "next" and self.idx < len(self.files) - 1:
            self.idx += 1
            self.search_term = ""
            self.load_file()
        elif action == "prev" and self.idx > 0:
            self.idx -= 1
            self.search_term = ""
            self.load_file()
        elif action in ("wrap", "ascii"):
            o[action] = not o[action]
            self._persist()
            self.render()
        elif action.startswith("mode:"):
            o["mode"] = action.split(":")[1]
            self._persist()
            self.jump_to(self.win_off)  # realign window for the new mode
        elif action.startswith(("font:", "size:")):
            key, val = action.split(":")
            o[key] = int(val) if key == "size" else val
            self._persist()
            self.render()
        elif action == "search":
            self._ask_search()
        elif action == "next_match":
            self.find(1)
        elif action == "prev_match":
            self.find(-1)
        elif action == "home":
            self.jump_to(0)
        elif action == "end":
            self.jump_to(self.fsize)
        else:
            return False
        return True

    # -- search -----------------------------------------------------------------
    def _ask_search(self):
        from ..ui import dialogs
        term = dialogs.ask_text("Search", "Find:", self.search_term)
        if term:
            self.search_term = term
            self.find(1, from_start=True)

    def _stream_find(self, needle: bytes, start: int, direction: int) -> int:
        """Case-insensitive (ASCII) byte search over the file on disk."""
        ch, ov = 4 << 20, len(needle) - 1
        if direction > 0:
            off = max(0, start)
            while off < self.fsize:
                i = self._read(off, ch + ov).lower().find(needle)
                if i >= 0:
                    return off + i
                off += ch
            return -1
        end = min(start, self.fsize)
        while end > 0:
            off = max(0, end - ch)
            i = self._read(off, end - off + ov).lower().rfind(needle)
            if i >= 0 and off + i < end:
                return off + i
            end = off
        return -1

    def find(self, direction: int, from_start: bool = False):
        if not self.search_term:
            self._ask_search()
            return
        needle = self.search_term.encode("utf-8").lower()
        cur = self._cursor_byte()
        start = 0 if from_start else cur + (1 if direction > 0 else -1)
        hit = self._stream_find(needle, start, direction)
        if hit < 0 and not from_start:  # wrap around
            hit = self._stream_find(needle, 0 if direction > 0 else self.fsize,
                                    direction)
            if hit == cur:
                hit = -1 if direction > 0 else hit
        self._status()
        if hit < 0:
            self.status.copy_label(f"  not found: {self.search_term}")
            return
        if not (self.win_off <= hit < self.win_off + len(self.data) - len(needle)):
            self._load_window(hit - self._win_bytes() // 2)
            self.render()
        self._show_hit(hit, len(needle))

    def _cursor_byte(self) -> int:
        pos = self.disp.insert_position()
        if self.opts["mode"] == "hex":
            return self.win_off + (pos // HEXW) * 16
        ln = max(1, len(self.text))
        return self.win_off + int(len(self.data) * pos / ln)

    def _show_hit(self, off: int, nlen: int):
        local = off - self.win_off
        if self.opts["mode"] == "hex":
            line = local // 16
            a = line * HEXW
            b = min(len(self.text), a + HEXW - 1)
        else:
            # exact char position: decode the bytes before the hit
            cpos = len(self.data[:local].decode("utf-8", "replace"))
            hay = self.text.lower()
            term = self.search_term.lower()
            if hay.startswith(term, cpos):
                a = cpos
            else:  # small drift (replacement chars): search near the guess
                a = hay.find(term, max(0, cpos - 64), cpos + 64 + len(term))
                if a < 0:
                    a = hay.find(term)
            if a < 0:
                return
            b = a + len(term)
        self.buf.select(a, b)
        self.disp.insert_position(a)
        row = self.disp.count_lines(0, a, True)
        self.disp.scroll(max(1, row - self._vis_rows() // 3), 0)
        self._sync_fbar()
        self.redraw()

    KEYS = {ord("q"): "close", ord("w"): "wrap", ord("a"): "ascii",
            ord("n"): "next", ord("p"): "prev",
            ord("1"): "mode:text", ord("3"): "mode:hex",
            fltk.FL_F + 7: "search"}

    def handle(self, event):
        if event in (fltk.FL_KEYDOWN, fltk.FL_SHORTCUT):
            key = fltk.Fl.event_key()
            state = fltk.Fl.event_state()
            if key == fltk.FL_F + 3:
                return self.do_action("prev_match" if state & fltk.FL_SHIFT
                                      else "next_match") and 1
            if state & fltk.FL_CTRL:
                if key == ord("f"):
                    return self.do_action("search") and 1
                if key == fltk.FL_Home:
                    return self.do_action("home") and 1
                if key == fltk.FL_End:
                    return self.do_action("end") and 1
            if not state & (fltk.FL_CTRL | fltk.FL_ALT) and key in self.KEYS:
                return self.do_action(self.KEYS[key]) and 1
        return super().handle(event)


def view_file(path: str) -> ViewerWindow:
    win = ViewerWindow([path])
    win.show()
    return win


def edit_file(cfg: dict, path: str, flash=lambda m: None) -> bool:
    """Launch the configured external editor (F4). No internal editor."""
    from ..ui import dialogs
    cmd = cfg.get("editor", {}).get("command", "")
    if not cmd:
        cmd = dialogs.ask_text(
            "Configure editor",
            "Editor command (e.g. 'gedit' or 'code -w'):", "")
        if not cmd:
            return False
        cfg.setdefault("editor", {})["command"] = cmd
        config.update("editor", {"command": cmd})
    import shlex
    try:
        subprocess.Popen(shlex.split(cmd) + [paths.to_native(path)],
                         start_new_session=True)
        return True
    except OSError as e:
        flash(f"editor: {e}")
        return False


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: flcmd-view FILE...", file=sys.stderr)
        return 2
    fltk.Fl.scheme("gtk+")
    win = ViewerWindow(argv)
    win.show()
    return fltk.Fl.run()
