"""TC-style command line: a prompt (active pane's directory) and an input
between the panes and the function-key bar. Enter runs the command via the
app; Up/Down walk the session history; Escape returns focus to the pane."""

import fltk

from . import esc, theme

CMD_H = 24
_MAX_HIST = 50


class _CmdInput(fltk.Fl_Input):
    def __init__(self, x, y, w, h, bar):
        super().__init__(x, y, w, h)
        self.bar = bar
        self.textsize(12)
        self.when(fltk.FL_WHEN_NEVER)

    def handle(self, event):
        if event == fltk.FL_KEYDOWN:
            key = fltk.Fl.event_key()
            if key in (fltk.FL_Enter, fltk.FL_KP_Enter):
                self.bar.submit(self.value())
                return 1
            if key == fltk.FL_Escape:
                self.value("")
                self.bar.focus_pane()
                return 1
            if key == fltk.FL_Up:
                self.bar.recall(-1, self)
                return 1
            if key == fltk.FL_Down:
                self.bar.recall(+1, self)
                return 1
        return super().handle(event)


class CmdLine(fltk.Fl_Group):
    """on_command(text) runs/handles a submitted line; focus_pane() is a
    callable returning focus to the active pane."""

    def __init__(self, x, y, w, h, on_command, focus_pane):
        super().__init__(x, y, w, h)
        self.box(fltk.FL_FLAT_BOX)
        self.color(theme.FOOTER_BG)
        self.on_command = on_command
        self.focus_pane = focus_pane
        self._hist: list[str] = []
        self._hpos = 0
        self.prompt = fltk.Fl_Box(x + 2, y, 10, h)
        self.prompt.box(fltk.FL_FLAT_BOX)
        self.prompt.color(theme.FOOTER_BG)
        self.prompt.labelsize(11)
        self.prompt.labelfont(fltk.FL_HELVETICA_BOLD)
        self.prompt.align(fltk.FL_ALIGN_INSIDE | fltk.FL_ALIGN_RIGHT)
        self.input = _CmdInput(x + 12, y + 1, w - 14, h - 2, self)
        self.resizable(self.input)
        self.end()

    def set_prompt(self, path: str):
        txt = path if len(path) <= 60 else "..." + path[-57:]
        txt += ">"
        fltk.fl_font(fltk.FL_HELVETICA_BOLD, 11)
        pw = int(fltk.fl_width(txt)) + 8
        self.prompt.copy_label(esc(txt))
        self.prompt.resize(self.x() + 2, self.y(), pw, self.h())
        self.input.resize(self.x() + 2 + pw, self.y() + 1,
                          self.w() - pw - 4, self.h() - 2)
        self.redraw()

    def submit(self, text: str):
        text = text.strip()
        self.input.value("")
        if not text:
            return
        if not self._hist or self._hist[-1] != text:
            self._hist.append(text)
            del self._hist[:-_MAX_HIST]
        self._hpos = len(self._hist)
        self.on_command(text)
        self.focus_pane()

    def recall(self, step: int, inp):
        if not self._hist:
            return
        self._hpos = max(0, min(len(self._hist), self._hpos + step))
        inp.value(self._hist[self._hpos] if self._hpos < len(self._hist) else "")
