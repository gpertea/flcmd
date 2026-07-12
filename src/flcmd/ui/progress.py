"""Progress dialog + UI pump for a running file operation. The worker
blocks on OpControl.ask(); the pump shows those prompts here on the UI
thread and feeds the answer back."""

import fltk

from . import dialogs


def _fmt_bytes(n: int) -> str:
    if n >= 1 << 30:
        return f"{n / (1 << 30):.2f} G"
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f} M"
    if n >= 1 << 10:
        return f"{n / (1 << 10):.0f} k"
    return str(n)


class ProgressDialog:
    def __init__(self, title: str, detail: str):
        w = 460
        self.win = fltk.Fl_Double_Window(w, 132, title)
        self.detail = fltk.Fl_Box(10, 6, w - 20, 18, detail)
        self.detail.align(fltk.FL_ALIGN_INSIDE | fltk.FL_ALIGN_LEFT
                          | fltk.FL_ALIGN_CLIP)
        self.detail.labelsize(12)
        self.current = fltk.Fl_Box(10, 26, w - 20, 18)
        self.current.align(fltk.FL_ALIGN_INSIDE | fltk.FL_ALIGN_LEFT
                           | fltk.FL_ALIGN_CLIP)
        self.current.labelsize(11)
        self.bar = fltk.Fl_Progress(10, 50, w - 20, 20)
        self.bar.minimum(0.0)
        self.bar.maximum(1.0)
        self.bar.color(fltk.FL_WHITE)
        self.bar.selection_color(fltk.fl_rgb_color(153, 180, 209))
        self.stats = fltk.Fl_Box(10, 74, w - 20, 16)
        self.stats.align(fltk.FL_ALIGN_INSIDE | fltk.FL_ALIGN_LEFT)
        self.stats.labelsize(11)
        self.cancel_btn = fltk.Fl_Button(w - 110, 98, 100, 26, "Cancel")
        self.win.end()
        self.win.set_modal()
        self._cancelled = False
        self.cancel_btn.callback(self._on_cancel)
        self.win.callback(self._on_cancel)  # window close = cancel

    def _on_cancel(self, wid=None):
        self._cancelled = True

    def pump(self, ctl, thread) -> bool:
        """Run the UI loop until the worker finishes. True unless cancelled."""
        self.win.show()
        while thread.is_alive():
            if self._cancelled:
                ctl.cancel_evt.set()
                self._cancelled = False
            ask = ctl.pending_ask()
            if ask:
                text, buttons = ask
                ctl.answer(dialogs.ask_buttons("flcmd", text, buttons))
            db, tb, di, ti, cur = ctl.snapshot()
            frac = (db / tb) if tb else (di / ti if ti else 0.0)
            self.bar.value(frac)
            self.current.copy_label(cur)
            self.stats.copy_label(
                f"{_fmt_bytes(db)} / {_fmt_bytes(tb)}   "
                f"({di} / {ti} items)")
            fltk.Fl.wait(0.03)
        self.win.hide()
        # drain a final ask that may have raced the thread's exit
        ask = ctl.pending_ask()
        if ask:
            ctl.answer("Cancel")
        return ctl.error is None


def run_operation(title: str, detail: str, ctl, worker_fn) -> bool:
    """Start worker_fn in a thread and pump progress; returns success."""
    from ..ops import run_in_thread
    dlg = ProgressDialog(title, detail)
    t = run_in_thread(worker_fn, ctl)
    ok = dlg.pump(ctl, t)
    if not ok and ctl.error != "cancelled":
        dialogs.ask_buttons("flcmd", f"Operation failed:\n{ctl.error}", ["OK"])
    return ok
