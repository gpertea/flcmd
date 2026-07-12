"""Bookmarks store + folder-shortcuts menu + locations toolbar."""

import json

import pytest


def test_store_roundtrip(isolated_config):
    from flcmd import bookmarks
    data = bookmarks.load()
    assert data == {"bookmarks": [], "toolbar": []}
    bookmarks.add_bookmark(data, "Work", "/home/x/work")
    data["bookmarks"].append({"title": "Remotes", "items": [
        {"title": "gvlin home", "path": "sftp://gvlin/home/x"}]})
    bookmarks.add_toolbar(data, "work", "/home/x/work")
    bookmarks.save(data)
    again = bookmarks.load()
    assert again["bookmarks"][0] == {"title": "Work", "path": "/home/x/work"}
    assert again["bookmarks"][1]["items"][0]["path"] == "sftp://gvlin/home/x"
    assert again["toolbar"][0]["caption"] == "work"
    # valid JSON file on disk
    with open(bookmarks._store_path()) as f:
        json.load(f)


def test_make_location_and_title(isolated_config):
    from flcmd import bookmarks

    class FakeSess:
        label = "gvlin"

    class FakeSftp:
        scheme = "sftp"
        session = FakeSess()

    class FakeLocal:
        scheme = "file"

    assert bookmarks.make_location(FakeLocal(), "/a/b/c") == "/a/b/c"
    assert (bookmarks.make_location(FakeSftp(), "/home/x")
            == "sftp://gvlin/home/x")
    assert bookmarks.short_title("/a/b/photos") == "photos"
    assert bookmarks.short_title("sftp://gvlin/opt/data") == "data [gvlin]"
    assert bookmarks.short_title("sftp://gvlin/") == "gvlin"


@pytest.mark.gui
class TestGui:
    @pytest.fixture()
    def app(self, xdisplay, isolated_config, sample_tree, tmp_path):
        import fltk
        from flcmd.app import App
        other = tmp_path / "other"
        (other / "target").mkdir(parents=True)
        a = App(sample_tree, str(other).replace("\\", "/"))
        a.show()
        for _ in range(8):
            fltk.Fl.check()
        yield a
        a.quit()
        fltk.Fl.check()

    def test_active_pane_persists_across_dialog(self, app, monkeypatch):
        import fltk
        from flcmd.ui import dialogs
        app.set_active_pane(app.right)
        assert app.active() is app.right and app.right.is_active
        assert not app.left.is_active
        # a modal dialog steals FLTK focus but must not change active pane
        monkeypatch.setattr(dialogs, "ask_text", lambda *a, **k: None)
        app.dispatch("file.mkdir", app.right)
        for _ in range(3):
            fltk.Fl.check()
        assert app.active() is app.right and app.right.is_active

    def test_add_and_go_bookmark(self, app, monkeypatch):
        from flcmd import bookmarks
        from flcmd.ui import dialogs
        pane = app.left
        monkeypatch.setattr(dialogs, "ask_text", lambda *a, **k: "MyTree")
        app.dispatch("bookmarks.add", pane)
        data = bookmarks.load()
        assert data["bookmarks"][0] == {"title": "MyTree",
                                        "path": pane.path}
        # navigate somewhere else, then jump back via the stored location
        app.dispatch("nav.up", pane)
        assert pane.path != data["bookmarks"][0]["path"]
        app.dispatch("bookmark.go:" + data["bookmarks"][0]["path"], pane)
        assert pane.path == data["bookmarks"][0]["path"]

    def test_go_nonexistent(self, app):
        pane = app.left
        p0 = pane.path
        app.dispatch("bookmark.go:/no/such/dir/here", pane)
        assert pane.path == p0  # unchanged
        assert "no such" in pane.footer.label()

    def test_toolbar_add_and_activate(self, app):
        pane, other = app.left, app.right
        target = other.path + "/target"
        app.toolbar.add_location(target)
        assert len(app.toolbar._btns) == 1
        assert app.toolbar._btns[0].label() == "target"
        # activating the button chdir's the ACTIVE pane
        app.set_active_pane(pane)
        app.toolbar.activate_button(0)
        assert pane.path == target

    def test_toolbar_edit_delete(self, app, monkeypatch):
        from flcmd import bookmarks
        from flcmd.ui import dialogs
        app.toolbar.add_location(app.left.path)
        # edit
        monkeypatch.setattr(dialogs, "ask_fields",
                            lambda *a, **k: ["Renamed", "/tmp"])
        data = bookmarks.load()
        data["toolbar"][0] = {"caption": "Renamed", "path": "/tmp"}
        bookmarks.save(data)
        app.toolbar.rebuild()
        assert app.toolbar._btns[0].label() == "Renamed"
        # delete
        data = bookmarks.load()
        del data["toolbar"][0]
        bookmarks.save(data)
        app.toolbar.rebuild()
        assert app.toolbar._btns == []

    def test_toolbar_toggle(self, app):
        assert app.toolbar.visible()
        app.dispatch("toolbar.toggle", app.left)
        assert not app.toolbar.visible()
        assert app.tile.y() == app.menubar.h()  # tile reclaimed the space
        app.dispatch("toolbar.toggle", app.left)
        assert app.toolbar.visible()


@pytest.mark.gui
class TestEditor:
    @pytest.fixture()
    def ed(self, xdisplay, isolated_config):
        import fltk
        from flcmd.ui.bmedit import _Editor
        nodes = [{"title": "Work", "path": "/w"},
                 {"title": "Remotes", "items": [
                     {"title": "gv home", "path": "sftp://gvlin/home/x"}]},
                 {"title": "Tmp", "path": "/tmp"}]
        e = _Editor(nodes)
        e.win.show()
        for _ in range(3):
            fltk.Fl.check()
        yield e
        e.win.hide()
        fltk.Fl.check()

    def test_rows_and_display(self, ed):
        titles = [r[0]["title"] for r in ed.rows]
        assert titles == ["Work", "Remotes", "gv home", "Tmp"]
        assert ed.browser.size() == 4
        assert "Remotes/" in ed.browser.text(2)
        assert "sftp://gvlin/home/x" in ed.browser.text(3)

    def test_add_bookmark_after_selection(self, ed, monkeypatch):
        from flcmd.ui import dialogs
        ed.browser.select(1)  # Work
        monkeypatch.setattr(dialogs, "ask_fields",
                            lambda *a, **k: ["New", "/n"])
        ed.add_bookmark()
        assert [r[0]["title"] for r in ed.rows][:2] == ["Work", "New"]
        assert ed.browser.value() == 2  # selection follows the new node

    def test_add_into_submenu(self, ed, monkeypatch):
        from flcmd.ui import dialogs
        ed.browser.select(2)  # Remotes submenu -> insert at its top
        monkeypatch.setattr(dialogs, "ask_fields",
                            lambda *a, **k: ["gv opt", "sftp://gvlin/opt"])
        ed.add_bookmark()
        rem = ed.nodes[1]
        assert [n["title"] for n in rem["items"]] == ["gv opt", "gv home"]

    def test_edit_and_delete(self, ed, monkeypatch):
        from flcmd.ui import dialogs
        ed.browser.select(1)
        monkeypatch.setattr(dialogs, "ask_fields",
                            lambda *a, **k: ["Work2", "/w2"])
        ed.edit()
        assert ed.nodes[0] == {"title": "Work2", "path": "/w2"}
        ed.browser.select(2)  # Remotes (has 1 entry)
        monkeypatch.setattr(dialogs, "confirm", lambda *a, **k: True)
        ed.delete()
        assert [n["title"] for n in ed.nodes] == ["Work2", "Tmp"]

    def test_move_and_indent_outdent(self, ed):
        ed.browser.select(4)  # Tmp
        ed.move(-1)           # above Remotes
        assert [n["title"] for n in ed.nodes] == ["Work", "Tmp", "Remotes"]
        # move Tmp below Remotes again, then indent INTO Remotes
        node = ed.nodes[1]
        ed.move(1)
        assert ed.nodes[2] is node
        ed.indent()
        assert node in ed.nodes[1]["items"]
        assert [n["title"] for n in ed.nodes] == ["Work", "Remotes"]
        ed.outdent()          # back out, right after Remotes
        assert [n["title"] for n in ed.nodes] == ["Work", "Remotes", "Tmp"]

    def test_save_only_on_ok(self, xdisplay, isolated_config, monkeypatch):
        import fltk
        from flcmd import bookmarks
        from flcmd.ui import bmedit
        data = bookmarks.load()
        bookmarks.add_bookmark(data, "Keep", "/k")
        bookmarks.save(data)

        # cancel: mutation discarded
        def run_cancel(self):
            self.nodes.append({"title": "X", "path": "/x"})
            return False
        monkeypatch.setattr(bmedit._Editor, "run", run_cancel)
        assert bmedit.edit_bookmarks() is False
        assert [n["title"] for n in bookmarks.load()["bookmarks"]] == ["Keep"]

        # ok: mutation persisted
        def run_ok(self):
            self.nodes.append({"title": "X", "path": "/x"})
            return True
        monkeypatch.setattr(bmedit._Editor, "run", run_ok)
        assert bmedit.edit_bookmarks() is True
        assert [n["title"] for n in bookmarks.load()["bookmarks"]] == ["Keep", "X"]
