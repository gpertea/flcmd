"""Buttons with a hover highlight (FLTK has no built-in hover state)."""

import fltk

from . import theme


class HoverButton(fltk.Fl_Button):
    """Fl_Button that tints its background while the pointer is over it."""

    def __init__(self, x, y, w, h, label=None):
        if label is None:
            super().__init__(x, y, w, h)
        else:
            super().__init__(x, y, w, h, label)
        self.hover_color = theme.HOVER_BG
        self._base_color = self.color()

    def handle(self, event):
        r = super().handle(event)
        if event == fltk.FL_ENTER:
            self._base_color = self.color()
            self.color(self.hover_color)
            self.redraw()
            return 1
        if event == fltk.FL_LEAVE:
            self.color(self._base_color)
            self.redraw()
            return 1
        return r
