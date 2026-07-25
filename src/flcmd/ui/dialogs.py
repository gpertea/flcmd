"""Small modal dialogs. All return None / a value once the user decides;
they run their own event loop (fine to call from another modal loop).
Labels are auto-width (no truncation) and '@' is escaped (FLTK symbols)."""

import fltk

from . import esc


def _run_modal(win) -> None:
    win.set_modal()
    win.show()
    while win.shown():
        fltk.Fl.wait()


def _text_w(text: str, size: int = 12) -> int:
    fltk.fl_font(fltk.FL_HELVETICA, size)
    return max(int(fltk.fl_width(line)) for line in text.split("\n"))


class _ButtonsWindow(fltk.Fl_Double_Window):
    """Enter/keypad-Enter activates the focused button (FLTK buttons only
    react to Space); with focus elsewhere it takes the first (default)
    button. Esc still closes via FLTK's usual window handling."""

    def __init__(self, *args):
        super().__init__(*args)
        self.buttons: list = []

    def handle(self, event):
        if event == fltk.FL_KEYDOWN and fltk.Fl.event_key() in (
                fltk.FL_Enter, fltk.FL_KP_Enter):
            focus = fltk.Fl.focus()
            for b in self.buttons:
                if b == focus:
                    b.do_callback()
                    return 1
            if self.buttons:
                self.buttons[0].do_callback()
                return 1
        return super().handle(event)


def ask_buttons(title: str, message: str, buttons: list[str]) -> str:
    """Modal message with arbitrary buttons; returns the clicked label.
    Closing the window answers with the last button (the safe one)."""
    result = [buttons[-1]]
    bw, bh, pad = 96, 24, 8
    lines = message.count("\n") + 1
    mh = 16 * lines + 2 * pad
    w = max(len(buttons) * (bw + pad) + pad, 380, _text_w(message) + 3 * pad)
    win = _ButtonsWindow(w, mh + bh + 2 * pad, title)
    box = fltk.Fl_Box(pad, pad, w - 2 * pad, mh - pad, esc(message))
    box.align(fltk.FL_ALIGN_INSIDE | fltk.FL_ALIGN_LEFT | fltk.FL_ALIGN_WRAP)
    box.labelsize(12)

    def cb(wid, label):
        result[0] = label
        win.hide()

    x = (w - len(buttons) * (bw + pad) + pad) // 2
    for i, label in enumerate(buttons):
        b = fltk.Fl_Button(x + i * (bw + pad), mh + pad, bw, bh, label)
        b.labelsize(12)
        b.callback(cb, label)
        win.buttons.append(b)
    win.end()
    if win.buttons:
        win.buttons[0].take_focus()  # Enter accepts the default action
    _run_modal(win)
    return result[0]


def ask_fields(title: str, fields: list[tuple[str, str]],
               secret_last: bool = False) -> list[str] | None:
    """Modal with one labeled input row per (label, default) pair.
    Returns the values in order, or None if cancelled."""
    result: list = [None]
    pad, lh, ih = 10, 18, 24
    lw = max(_text_w(lbl) for lbl, _ in fields) + 2 * pad
    w = max(460, lw + 260)
    h = pad + len(fields) * (lh + ih + 6) + 34
    win = fltk.Fl_Double_Window(w, h, title)
    inputs = []
    y = pad
    for i, (lbl, default) in enumerate(fields):
        box = fltk.Fl_Box(pad, y, w - 2 * pad, lh, esc(lbl))
        box.align(fltk.FL_ALIGN_INSIDE | fltk.FL_ALIGN_LEFT)
        box.labelsize(12)
        y += lh
        cls = (fltk.Fl_Secret_Input
               if secret_last and i == len(fields) - 1 else fltk.Fl_Input)
        inp = cls(pad, y, w - 2 * pad, ih)
        inp.textsize(12)
        inp.value(default)
        inputs.append(inp)
        y += ih + 6

    def ok(wid=None):
        result[0] = [i.value() for i in inputs]
        win.hide()

    for inp in inputs:
        inp.callback(ok)
        inp.when(fltk.FL_WHEN_ENTER_KEY)
    bok = fltk.Fl_Return_Button(w - 200, y, 90, 24, "OK")
    bok.callback(ok)
    bcan = fltk.Fl_Button(w - 100, y, 90, 24, "Cancel")
    bcan.callback(lambda wid: win.hide())
    win.end()
    inputs[0].take_focus()
    inputs[0].insert_position(0, len(fields[0][1]))
    _run_modal(win)
    return result[0]


def ask_text(title: str, label: str, default: str = "",
             secret: bool = False) -> str | None:
    """Modal text prompt (TC-style destination/name input)."""
    vals = ask_fields(title, [(label, default)], secret_last=secret)
    return vals[0] if vals else None


def ask_dest(title: str, label: str, default: str = "",
             option_label: str | None = None,
             option_default: bool = False) -> tuple[str | None, bool]:
    """Destination prompt with an optional checkbox (e.g. follow symlinks).
    Returns (text or None if cancelled, checkbox state)."""
    result: list = [None]
    pad, ih = 10, 24
    extra = 24 if option_label else 0
    w = max(460, _text_w(label) + 3 * pad)
    win = fltk.Fl_Double_Window(w, 96 + extra, title)
    box = fltk.Fl_Box(pad, 6, w - 2 * pad, 18, esc(label))
    box.align(fltk.FL_ALIGN_INSIDE | fltk.FL_ALIGN_LEFT)
    box.labelsize(12)
    inp = fltk.Fl_Input(pad, 28, w - 2 * pad, ih)
    inp.textsize(12)
    inp.value(default)
    chk = None
    if option_label:
        chk = fltk.Fl_Check_Button(pad, 56, w - 2 * pad, 20, esc(option_label))
        chk.labelsize(12)
        chk.value(1 if option_default else 0)

    def ok(wid=None):
        result[0] = inp.value()
        win.hide()

    inp.callback(ok)
    inp.when(fltk.FL_WHEN_ENTER_KEY)
    bok = fltk.Fl_Return_Button(w - 200, 62 + extra, 90, 24, "OK")
    bok.callback(ok)
    bcan = fltk.Fl_Button(w - 100, 62 + extra, 90, 24, "Cancel")
    bcan.callback(lambda wid: win.hide())
    win.end()
    inp.take_focus()
    inp.insert_position(0, len(default))
    _run_modal(win)
    return result[0], bool(chk.value()) if chk else option_default


def confirm(title: str, message: str, yes: str = "OK") -> bool:
    return ask_buttons(title, message, [yes, "Cancel"]) == yes
