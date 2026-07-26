"""Transient popup menus.

A per-call Fl_Menu_Button is parentless, so Python owns it and frees the
C++ widget as soon as the call returns -- while FLTK still holds
pointers to it (pushed widget, damage list, the picked item's callback
data). The use-after-free surfaces later as an access violation in an
unrelated redraw. One reusable widget avoids that entirely.
"""

import fltk

_mb = None


def popup(build):
    """Pop up a menu at the mouse; `build(mb, pick)` adds the items with
    `pick` as callback. Returns the token of the item chosen, or None."""
    global _mb
    result = [None]

    def pick(wid, token):
        result[0] = token

    if _mb is None:
        _mb = fltk.Fl_Menu_Button(0, 0, 0, 0)
        if _mb.parent():  # never owned by whatever group was current
            _mb.parent().remove(_mb)
        _mb.type(fltk.Fl_Menu_Button.POPUP3)
    _mb.clear()
    _mb.position(fltk.Fl.event_x_root(), fltk.Fl.event_y_root())
    build(_mb, pick)
    _mb.popup()
    return result[0]
