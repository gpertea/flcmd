"""Built-in file viewer, a TC Lister equivalent: text (UTF-8 by default,
ASCII-only option) and hex modes, line wrap, search, configurable font --
all persisted in flcmd.ini [viewer]. Also standalone: `flcmd-view FILE...`
(n/p move between files). Keys: 1 text, 3 hex, W wrap, A ascii, F7/Ctrl+F
search, F3 next, Shift+F3 previous, Q/Esc close."""

import subprocess
import sys

import fltk

from .. import config, paths

MENU_H, STATUS_H = 25, 20
FONTS = {"courier": fltk.FL_COURIER, "helvetica": fltk.FL_HELVETICA,
         "times": fltk.FL_TIMES, "screen": fltk.FL_SCREEN}
SIZES = (9, 10, 11, 12, 14, 16, 18, 20)
DEFAULTS = {"font": "courier", "size": 12, "wrap": True, "ascii": False,
            "mode": "text", "max_mb": 32}


def _hexdump(data: bytes) -> str:
    out = []
    for off in range(0, len(data), 16):
        row = data[off:off + 16]
        hx = " ".join(f"{b:02x}" for b in row)
        hx = hx[:23] + " " + hx[23:] if len(row) > 8 else hx
        txt = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        out.append(f"{off:08x}  {hx:<48}  {txt}")
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
        self.truncated = False
        self.menubar = fltk.Fl_Menu_Bar(0, 0, w, MENU_H)
        self.menubar.box(fltk.FL_THIN_UP_BOX)
        self._build_menu()
        self.disp = fltk.Fl_Text_Display(0, MENU_H, w, h - MENU_H - STATUS_H)
        self.buf = fltk.Fl_Text_Buffer()
        self.disp.buffer(self.buf)
        self.status = fltk.Fl_Box(0, h - STATUS_H, w, STATUS_H)
        self.status.box(fltk.FL_FLAT_BOX)
        self.status.color(fltk.fl_rgb_color(240, 240, 240))
        self.status.align(fltk.FL_ALIGN_INSIDE | fltk.FL_ALIGN_LEFT
                          | fltk.FL_ALIGN_CLIP)
        self.status.labelsize(11)
        self.end()
        self.resizable(self.disp)
        self.load_file()

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

    # -- content ------------------------------------------------------------
    def path(self) -> str:
        return self.files[self.idx]

    def load_file(self):
        cap = int(self.opts["max_mb"]) * (1 << 20)
        try:
            with open(self.path(), "rb") as f:
                self.data = f.read(cap + 1)
        except OSError as e:
            self.data = f"cannot open {self.path()}: {e}".encode()
        self.truncated = len(self.data) > cap
        self.data = self.data[:cap]
        self.render()

    def render(self):
        o = self.opts
        if o["mode"] == "hex":
            text = _hexdump(self.data)
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
        self.disp.show_insert_position()
        self.label(f"flcmd-view - {self.path()}")
        self._status()
        self.redraw()

    def _status(self):
        o = self.opts
        parts = [paths.basename(self.path()), f"{len(self.data):,} bytes",
                 o["mode"], "ascii" if o["ascii"] else "utf-8"]
        if o["wrap"] and o["mode"] == "text":
            parts.append("wrap")
        if self.truncated:
            parts.append(f"TRUNCATED at {o['max_mb']} MB")
        if len(self.files) > 1:
            parts.append(f"file {self.idx + 1}/{len(self.files)}")
        if self.search_term:
            parts.append(f"search: {self.search_term}")
        self.status.copy_label("  " + "   ".join(str(p) for p in parts))

    def _persist(self):
        config.update("viewer", self.opts)

    # -- actions --------------------------------------------------------------
    def do_action(self, action: str) -> bool:
        o = self.opts
        if action == "close":
            self.hide()
        elif action == "next" and self.idx < len(self.files) - 1:
            self.idx += 1
            self.load_file()
        elif action == "prev" and self.idx > 0:
            self.idx -= 1
            self.load_file()
        elif action in ("wrap", "ascii"):
            o[action] = not o[action]
            self._persist()
            self.render()
        elif action.startswith(("mode:", "font:", "size:")):
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
        else:
            return False
        return True

    def _ask_search(self):
        from ..ui import dialogs
        term = dialogs.ask_text("Search", "Find:", self.search_term)
        if term:
            self.search_term = term
            self.find(1, from_start=True)

    def find(self, direction: int, from_start: bool = False):
        if not self.search_term:
            self._ask_search()
            return
        hay, needle = self.text.lower(), self.search_term.lower()
        pos = 0 if from_start else self.disp.insert_position()
        if direction > 0:
            hit = hay.find(needle, pos + (0 if from_start else 1))
            if hit < 0:
                hit = hay.find(needle)  # wrap around
        else:
            hit = hay.rfind(needle, 0, max(0, pos - 1))
            if hit < 0:
                hit = hay.rfind(needle)
        self._status()
        if hit < 0:
            self.status.copy_label(f"  not found: {self.search_term}")
            return
        self.buf.select(hit, hit + len(needle))
        self.disp.insert_position(hit)
        self.disp.show_insert_position()
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
            if state & fltk.FL_CTRL and key == ord("f"):
                return self.do_action("search") and 1
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
