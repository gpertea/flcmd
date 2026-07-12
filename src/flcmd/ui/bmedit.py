"""Bookmark tree editor ('* Configure...' in the folder-shortcuts menu).
Indented list of the bookmark tree; submenus end with '/'. Edits apply to
a working copy and are saved only on OK."""

import copy

import fltk

from .. import bookmarks
from . import dialogs, esc

W, H = 640, 420
BTN_W, BTN_H, PAD = 118, 24, 8


class _Editor:
    def __init__(self, nodes: list):
        self.nodes = nodes
        self.rows: list[tuple] = []  # (node, chain, depth); chain=[(list,idx)..]
        self.saved = False
        self.win = fltk.Fl_Double_Window(W, H, "Folder shortcuts")
        bw = W - BTN_W - 3 * PAD
        self.browser = fltk.Fl_Hold_Browser(PAD, PAD, bw, H - BTN_H - 3 * PAD)
        self.browser.textsize(12)
        self.browser.column_char(9)  # tab separates title | location
        self.browser.column_widths((int(bw * 0.45), 0))
        bx = W - BTN_W - PAD
        self.win.begin()
        y = PAD
        for label, cb in (("Add bookmark...", self.add_bookmark),
                          ("Add submenu...", self.add_submenu),
                          ("Edit...", self.edit),
                          ("Delete", self.delete),
                          (None, None),
                          ("Move up", lambda w=None: self.move(-1)),
                          ("Move down", lambda w=None: self.move(1)),
                          ("Indent >", self.indent),
                          ("< Outdent", self.outdent)):
            if label is None:
                y += 10
                continue
            b = fltk.Fl_Button(bx, y, BTN_W, BTN_H, label)
            b.labelsize(11)
            b.callback(lambda w, f=cb: f())
            y += BTN_H + 4
        ok = fltk.Fl_Return_Button(W - 200, H - BTN_H - PAD, 90, BTN_H, "OK")
        ok.callback(self._ok)
        can = fltk.Fl_Button(W - 100, H - BTN_H - PAD, 90, BTN_H, "Cancel")
        can.callback(lambda w: self.win.hide())
        self.win.end()
        self.win.set_modal()
        self.rebuild()

    # -- model <-> browser ---------------------------------------------------
    def rebuild(self, keep=None):
        self.rows = []

        def walk(nodes, depth, chain):
            for i, node in enumerate(nodes):
                self.rows.append((node, chain + [(nodes, i)], depth))
                if "items" in node:
                    walk(node["items"], depth + 1, chain + [(nodes, i)])

        walk(self.nodes, 0, [])
        self.browser.clear()
        for node, _chain, depth in self.rows:
            t = esc(node.get("title", "?"))
            if "items" in node:
                line = f"{'     ' * depth}{t}/\t"
            else:
                line = f"{'     ' * depth}{t}\t{esc(node.get('path', ''))}"
            self.browser.add(line)
        if keep is not None:
            for i, (node, _c, _d) in enumerate(self.rows):
                if node is keep:
                    self.browser.select(i + 1)
                    break

    def _sel(self):
        i = self.browser.value()
        return self.rows[i - 1] if 1 <= i <= len(self.rows) else None

    def _insert_ctx(self):
        """(container, index) to insert after the selection, else append."""
        sel = self._sel()
        if not sel:
            return self.nodes, len(self.nodes)
        node, chain, _d = sel
        if "items" in node:  # inserting after a submenu: into it, at top
            return node["items"], 0
        lst, idx = chain[-1]
        return lst, idx + 1

    # -- operations ------------------------------------------------------------
    def add_bookmark(self, wid=None):
        vals = dialogs.ask_fields(
            "Add bookmark",
            [("Menu title:", ""), ("Location (path or sftp://host/path):", "")])
        if not vals or not vals[0]:
            return
        lst, idx = self._insert_ctx()
        node = {"title": vals[0], "path": vals[1]}
        lst.insert(idx, node)
        self.rebuild(keep=node)

    def add_submenu(self, wid=None):
        title = dialogs.ask_text("Add submenu", "Submenu title:")
        if not title:
            return
        lst, idx = self._insert_ctx()
        node = {"title": title, "items": []}
        lst.insert(idx, node)
        self.rebuild(keep=node)

    def edit(self, wid=None):
        sel = self._sel()
        if not sel:
            return
        node, _c, _d = sel
        if "items" in node:
            title = dialogs.ask_text("Edit submenu", "Submenu title:",
                                     node.get("title", ""))
            if title:
                node["title"] = title
        else:
            vals = dialogs.ask_fields(
                "Edit bookmark",
                [("Menu title:", node.get("title", "")),
                 ("Location (path or sftp://host/path):",
                  node.get("path", ""))])
            if vals and vals[0]:
                node["title"], node["path"] = vals[0], vals[1]
        self.rebuild(keep=node)

    def delete(self, wid=None):
        sel = self._sel()
        if not sel:
            return
        node, chain, _d = sel
        what = node.get("title", "?")
        if "items" in node and node["items"]:
            what += f" (submenu with {len(node['items'])} entries)"
        if not dialogs.confirm("Delete", f"Delete '{what}' ?", yes="Delete"):
            return
        lst, idx = chain[-1]
        del lst[idx]
        self.rebuild()

    def move(self, delta: int):
        sel = self._sel()
        if not sel:
            return
        node, chain, _d = sel
        lst, idx = chain[-1]
        j = idx + delta
        if 0 <= j < len(lst):
            lst[idx], lst[j] = lst[j], lst[idx]
            self.rebuild(keep=node)

    def indent(self, wid=None):
        """Move the node into the submenu right above it."""
        sel = self._sel()
        if not sel:
            return
        node, chain, _d = sel
        lst, idx = chain[-1]
        if idx > 0 and "items" in lst[idx - 1] and lst[idx - 1] is not node:
            del lst[idx]
            lst[idx - 1]["items"].append(node)
            self.rebuild(keep=node)

    def outdent(self, wid=None):
        """Move the node out, right after its parent submenu."""
        sel = self._sel()
        if not sel:
            return
        node, chain, _d = sel
        if len(chain) < 2:
            return
        lst, idx = chain[-1]
        gp_lst, p_idx = chain[-2]
        del lst[idx]
        gp_lst.insert(p_idx + 1, node)
        self.rebuild(keep=node)

    # -- lifecycle -----------------------------------------------------------------
    def _ok(self, wid=None):
        self.saved = True
        self.win.hide()

    def run(self) -> bool:
        self.win.show()
        while self.win.shown():
            fltk.Fl.wait()
        return self.saved


def edit_bookmarks() -> bool:
    """Open the editor on a working copy; persist on OK. True if saved."""
    data = bookmarks.load()
    work = copy.deepcopy(data["bookmarks"])
    ed = _Editor(work)
    if ed.run():
        data["bookmarks"] = work
        bookmarks.save(data)
        return True
    return False
