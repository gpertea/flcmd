"""Popup menus, and the one rule FLTK menus need in pyFLTK.

pyFLTK increfs a menu item's *callback* but NOT its *user_data*: FLTK
keeps the raw PyObject*. A computed token ("go:" + path, an f-string)
is therefore freed as soon as the caller drops it, and picking that
item hands the callback a dangling pointer -- heap corruption that
surfaces later as an access violation in an unrelated redraw. String
*literals* live in the code object and never showed the bug, which is
why "+ Add current dir" always worked while bookmark entries crashed.

So: every token handed to FLTK must be kept referenced for as long as
the menu can be picked -- use token() for long-lived menus (menubar)
and popup()'s add() for transient ones.
"""

import fltk

_kept: list = []      # menubar tokens: alive for the process
_mb = None            # one reusable popup widget
_tokens: list = []    # current popup's callback + tokens


def token(t):
    """Keep a strong ref to a long-lived menu user_data value."""
    _kept.append(t)
    return t


def popup(build):
    """Pop up a menu at the mouse; `build(add)` fills it with
    add(label, token, flags=0). Returns the picked token, or None."""
    global _mb
    result = [None]

    def pick(wid, tok):
        result[0] = tok

    if _mb is None:
        _mb = fltk.Fl_Menu_Button(0, 0, 0, 0)
        if _mb.parent():  # never owned by whatever group was current
            _mb.parent().remove(_mb)
        _mb.type(fltk.Fl_Menu_Button.POPUP3)
    _mb.clear()
    _tokens.clear()
    _tokens.append(pick)

    def add(label, tok, flags=0):
        _tokens.append(tok)
        _mb.add(label, 0, pick, tok, flags)

    build(add)
    _mb.popup()
    return result[0]
