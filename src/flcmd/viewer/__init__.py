"""Built-in file viewer (F3), also standalone: `flcmd-view FILE` or
`python -m flcmd.viewer FILE`. Stage 1 stub: read-only text display with
encoding fallback; hex/image modes and search land in stage 3."""

import sys

import fltk

MAX_BYTES = 16 * 1024 * 1024


def _load_text(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read(MAX_BYTES)
    try:
        txt = data.decode("utf-8")
    except UnicodeDecodeError:
        txt = data.decode("latin-1")
    return txt.replace("\0", "\\0")


class ViewerWindow(fltk.Fl_Double_Window):
    def __init__(self, path: str, w=820, h=600):
        super().__init__(w, h, f"flcmd-view - {path}")
        self.buf = fltk.Fl_Text_Buffer()
        disp = fltk.Fl_Text_Display(0, 0, w, h)
        disp.buffer(self.buf)
        disp.textfont(fltk.FL_COURIER)
        disp.textsize(12)
        self.resizable(disp)
        self.end()
        try:
            self.buf.text(_load_text(path))
        except OSError as e:
            self.buf.text(f"cannot open {path}: {e}")


def view_file(path: str) -> ViewerWindow:
    win = ViewerWindow(path)
    win.show()
    return win


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: flcmd-view FILE", file=sys.stderr)
        return 2
    view_file(argv[0])
    return fltk.Fl.run()
