"""Small modal dialogs. All return None / a value once the user decides;
they run their own event loop (fine to call from another modal loop)."""

import fltk


def _run_modal(win) -> None:
    win.set_modal()
    win.show()
    while win.shown():
        fltk.Fl.wait()


def ask_buttons(title: str, message: str, buttons: list[str]) -> str:
    """Modal message with arbitrary buttons; returns the clicked label.
    Closing the window answers with the last button (the safe one)."""
    result = [buttons[-1]]
    bw, bh, pad = 96, 24, 8
    lines = message.count("\n") + 1
    mh = 16 * lines + 2 * pad
    w = max(len(buttons) * (bw + pad) + pad, 380)
    win = fltk.Fl_Double_Window(w, mh + bh + 2 * pad, title)
    box = fltk.Fl_Box(pad, pad, w - 2 * pad, mh - pad, message)
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
    win.end()
    _run_modal(win)
    return result[0]


def ask_text(title: str, label: str, default: str = "") -> str | None:
    """Modal text prompt (TC-style destination/name input)."""
    result = [None]
    w, ih = 460, 24
    win = fltk.Fl_Double_Window(w, 96, title)
    box = fltk.Fl_Box(10, 6, w - 20, 18, label)
    box.align(fltk.FL_ALIGN_INSIDE | fltk.FL_ALIGN_LEFT)
    box.labelsize(12)
    inp = fltk.Fl_Input(10, 28, w - 20, ih)
    inp.textsize(12)
    inp.value(default)

    def ok(wid=None):
        result[0] = inp.value()
        win.hide()

    def cancel(wid):
        win.hide()

    inp.callback(ok)
    inp.when(fltk.FL_WHEN_ENTER_KEY)
    bok = fltk.Fl_Return_Button(w - 200, 62, 90, 24, "OK")
    bok.callback(ok)
    bcan = fltk.Fl_Button(w - 100, 62, 90, 24, "Cancel")
    bcan.callback(cancel)
    win.end()
    inp.take_focus()
    inp.insert_position(0, len(default))  # preselect for quick overtype
    _run_modal(win)
    return result[0]


def ask_dest(title: str, label: str, default: str = "",
             option_label: str | None = None,
             option_default: bool = False) -> tuple[str | None, bool]:
    """Destination prompt with an optional checkbox (e.g. follow symlinks).
    Returns (text or None if cancelled, checkbox state)."""
    result: list = [None]
    w, ih = 460, 24
    extra = 24 if option_label else 0
    win = fltk.Fl_Double_Window(w, 96 + extra, title)
    box = fltk.Fl_Box(10, 6, w - 20, 18, label)
    box.align(fltk.FL_ALIGN_INSIDE | fltk.FL_ALIGN_LEFT)
    box.labelsize(12)
    inp = fltk.Fl_Input(10, 28, w - 20, ih)
    inp.textsize(12)
    inp.value(default)
    chk = None
    if option_label:
        chk = fltk.Fl_Check_Button(10, 56, w - 20, 20, option_label)
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
