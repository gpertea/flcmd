"""GUI-level tests of stage-2 operations: dispatch the real actions with
the modal dialogs monkeypatched to canned answers."""

import os

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture()
def app(xdisplay, isolated_config, sample_tree, tmp_path):
    import fltk
    from flcmd.app import App

    right = tmp_path / "right"
    right.mkdir()
    a = App(sample_tree, str(right).replace("\\", "/"))
    a.show()
    for _ in range(10):
        fltk.Fl.check()
    yield a
    a.quit()
    fltk.Fl.check()


def _cursor_to(pane, name):
    for i, e in enumerate(pane.view):
        if e.name == name:
            pane.set_cursor(i)
            return
    raise AssertionError(f"{name} not in view")


def test_mkdir(app, monkeypatch):
    from flcmd.ui import dialogs
    monkeypatch.setattr(dialogs, "ask_text", lambda *a, **k: "newdir")
    app.dispatch("file.mkdir", app.left)
    assert os.path.isdir(app.left.path + "/newdir")
    assert app.left.current().name == "newdir"  # cursor lands on it


def test_copy_selection(app, monkeypatch):
    from flcmd.ui import dialogs
    pane, other = app.left, app.right
    pane.selected = {"alpha.txt", "bdir"}
    monkeypatch.setattr(dialogs, "ask_text", lambda *a, **k: other.path)
    app.dispatch("file.copy", pane)
    assert open(other.path + "/alpha.txt").read() == "hello alpha\n"
    assert open(other.path + "/bdir/deep.txt").read() == "deep\n"
    assert os.path.exists(pane.path + "/alpha.txt")
    assert {e.name for e in other.view} >= {"alpha.txt", "bdir"}


def test_move_cursor_item(app, monkeypatch):
    from flcmd.ui import dialogs
    pane, other = app.left, app.right
    _cursor_to(pane, "beta.log")
    monkeypatch.setattr(dialogs, "ask_text", lambda *a, **k: other.path)
    app.dispatch("file.move", pane)
    assert not os.path.exists(pane.path + "/beta.log")
    assert os.path.getsize(other.path + "/beta.log") == 1000


def test_delete(app, monkeypatch):
    from flcmd.ui import dialogs
    pane = app.left
    pane.selected = {"adir", "beta.log"}
    monkeypatch.setattr(dialogs, "confirm", lambda *a, **k: True)
    app.dispatch("file.delete", pane)
    assert not os.path.exists(pane.path + "/adir")
    assert not os.path.exists(pane.path + "/beta.log")
    assert os.path.exists(pane.path + "/alpha.txt")
    assert pane.selected == set()  # refresh pruned the gone names


def test_copy_creates_missing_dest(app, monkeypatch):
    from flcmd.ui import dialogs
    pane, other = app.left, app.right
    _cursor_to(pane, "alpha.txt")
    dest = other.path + "/made/up"
    monkeypatch.setattr(dialogs, "ask_text", lambda *a, **k: dest)
    monkeypatch.setattr(dialogs, "confirm", lambda *a, **k: True)
    app.dispatch("file.copy", pane)
    assert open(dest + "/alpha.txt").read() == "hello alpha\n"


def test_inline_rename(app):
    import fltk
    pane = app.left
    _cursor_to(pane, "alpha.txt")
    app.dispatch("file.rename", pane)
    assert pane._rename is not None
    pane._rename.value("omega.txt")
    pane.end_rename("omega.txt")
    fltk.Fl.check()
    assert os.path.exists(pane.path + "/omega.txt")
    assert not os.path.exists(pane.path + "/alpha.txt")
    assert pane.current().name == "omega.txt"


def test_rename_escape_cancels(app):
    pane = app.left
    _cursor_to(pane, "alpha.txt")
    pane.start_rename()
    pane.end_rename(None)
    assert os.path.exists(pane.path + "/alpha.txt")
    assert pane._rename is None


def test_dirsize_space_and_ctrl_l(app, monkeypatch):
    from flcmd.ui import dialogs
    pane = app.left
    shown = []
    monkeypatch.setattr(dialogs, "ask_buttons",
                        lambda t, m, b: shown.append(m) or b[0])
    _cursor_to(pane, "bdir")
    app.dispatch("sel.toggle_space", pane)   # Space computes dir size
    assert pane.dir_sizes["bdir"] == 5       # deep.txt
    assert "bdir" in pane.selected
    assert pane.size_text(pane.view[2]) == "5"
    _cursor_to(pane, "adir")
    pane.selected = set()
    app.dispatch("pane.dirsize", pane)       # Ctrl+L on cursor item
    assert pane.dir_sizes["adir"] == 0
    assert shown and "0 bytes" in shown[-1]


def test_props_dialog(app, monkeypatch):
    from flcmd.ui import dialogs
    pane = app.left
    shown = []
    monkeypatch.setattr(dialogs, "ask_buttons",
                        lambda t, m, b: shown.append(m) or b[0])
    _cursor_to(pane, "alpha.txt")
    app.dispatch("file.props", pane)
    assert "alpha.txt" in shown[0] and "type: file" in shown[0]
