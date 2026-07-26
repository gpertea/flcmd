"""Locations toolbar: a row of directory-shortcut buttons under the menu,
spanning both panes. Drop a directory (from a pane, the panel header, or an
external file manager) to add a button; left-click chdir's the active pane;
right-click edits or deletes the button."""

import fltk

from .. import bookmarks, config, paths
from . import esc
from .buttons import HoverButton

TOOLBAR_H = 26
BTN_H = 22
BTN_PAD = 6


class _LocBtn(HoverButton):
    def __init__(self, x, y, w, h, toolbar, index):
        super().__init__(x, y, w, h)
        self.toolbar = toolbar
        self.index = index
        self.box(fltk.FL_THIN_UP_BOX)
        self.labelsize(11)
        self.clear_visible_focus()
        self.callback(lambda wid: toolbar.activate_button(index))

    def handle(self, event):
        if event == fltk.FL_PUSH and fltk.Fl.event_button() == fltk.FL_RIGHT_MOUSE:
            self.toolbar.context_menu(self.index)
            return 1
        return super().handle(event)


class LocationsToolbar(fltk.Fl_Group):
    def __init__(self, x, y, w, h, on_go, host_win, nav_cb=None):
        super().__init__(x, y, w, h)
        # flat strip, TC buttonbar style; the menubar's 1px bevel above
        # already separates the two
        self.box(fltk.FL_FLAT_BOX)
        self.on_go = on_go          # callable(location) -> chdir active pane
        self.host_win = host_win
        self.nav_cb = nav_cb        # callable(-1|+1) -> history back/forward
        self._btns: list[_LocBtn] = []
        self._nav_btns: list[fltk.Fl_Button] = []
        self.end()
        self.rebuild()

    # -- data ---------------------------------------------------------------
    def _buttons(self) -> list:
        return bookmarks.load()["toolbar"]

    def rebuild(self):
        for b in self._btns + self._nav_btns:
            self.remove(b)
            fltk.Fl.delete_widget(b)
        self._btns = []
        self._nav_btns = []
        self.begin()
        bx = self.x() + BTN_PAD
        by = self.y() + (self.h() - BTN_H) // 2
        if self.nav_cb and bool(config.load().get("toolbar", {}).get("nav", True)):
            for sym, d, tip in (("@<-", -1, "Back (Alt+Left)"),
                                ("@->", +1, "Forward (Alt+Right)")):
                b = HoverButton(bx, by, 28, BTN_H)
                b.copy_label(sym)  # '@' kept: FLTK arrow symbols
                b.box(fltk.FL_THIN_UP_BOX)
                b.labelsize(11)
                b.clear_visible_focus()
                b.copy_tooltip(tip)
                b.callback(lambda wid, dd=d: self.nav_cb(dd))
                self._nav_btns.append(b)
                bx += 28 + 2
            bx += BTN_PAD
        for i, item in enumerate(self._buttons()):
            cap = esc(item.get("caption", "?"))
            fltk.fl_font(fltk.FL_HELVETICA, 11)
            bw = max(48, int(fltk.fl_width(cap)) + 16)
            b = _LocBtn(bx, by, bw, BTN_H, self, i)
            b.copy_label(cap)
            b.copy_tooltip(item.get("path", ""))
            self._btns.append(b)
            bx += bw + BTN_PAD
        self.end()
        self.redraw()

    def activate_button(self, index):
        items = self._buttons()
        if 0 <= index < len(items):
            self.on_go(items[index]["path"])

    # -- editing ------------------------------------------------------------
    def add_location(self, location: str):
        data = bookmarks.load()
        bookmarks.add_toolbar(data, bookmarks.short_title(location), location)
        bookmarks.save(data)
        self.rebuild()

    def context_menu(self, index):
        from . import dialogs
        items = bookmarks.load()["toolbar"]
        if not (0 <= index < len(items)):
            return
        from . import menus

        def build(add):
            add("Edit...", "edit")
            add("Delete", "delete")

        result = [menus.popup(build)]
        if result[0] == "edit":
            it = items[index]
            vals = dialogs.ask_fields(
                "Edit toolbar button",
                [("Caption:", it.get("caption", "")),
                 ("Location (path or sftp://host/path):", it.get("path", ""))])
            if vals:
                data = bookmarks.load()
                data["toolbar"][index] = {"caption": vals[0], "path": vals[1]}
                bookmarks.save(data)
                self.rebuild()
        elif result[0] == "delete":
            if dialogs.confirm("Delete button",
                               f"Delete toolbar button\n"
                               f"'{items[index].get('caption')}' ?",
                               yes="Delete"):
                data = bookmarks.load()
                del data["toolbar"][index]
                bookmarks.save(data)
                self.rebuild()

    # -- drop-in (a directory dragged onto the toolbar) ----------------------
    def handle(self, event):
        if event in (fltk.FL_DND_ENTER, fltk.FL_DND_DRAG, fltk.FL_DND_RELEASE):
            return 1
        if event == fltk.FL_PASTE:
            for line in fltk.Fl.event_text().splitlines():
                line = line.strip()
                loc = None
                if line.startswith("file://"):
                    loc = paths.from_uri(line)
                elif line.startswith("/"):
                    loc = paths.canon(line)
                if loc:
                    self.add_location(loc)
                    break
            return 1
        return super().handle(event)
