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
    monkeypatch.setattr(dialogs, "ask_dest", lambda *a, **k: (other.path, False))
    app.dispatch("file.copy", pane)
    assert open(other.path + "/alpha.txt").read() == "hello alpha\n"
    assert open(other.path + "/bdir/deep.txt").read() == "deep\n"
    assert os.path.exists(pane.path + "/alpha.txt")
    assert {e.name for e in other.view} >= {"alpha.txt", "bdir"}


def test_move_cursor_item(app, monkeypatch):
    from flcmd.ui import dialogs
    pane, other = app.left, app.right
    _cursor_to(pane, "beta.log")
    monkeypatch.setattr(dialogs, "ask_dest", lambda *a, **k: (other.path, False))
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
    monkeypatch.setattr(dialogs, "ask_dest", lambda *a, **k: (dest, False))
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


def test_auto_refresh_external_change(app):
    import fltk
    import time
    pane = app.left
    names = {e.name for e in pane.view}
    assert "external.txt" not in names
    with open(pane.path + "/external.txt", "w") as f:
        f.write("surprise")
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        fltk.Fl.wait(0.1)  # watcher timeout fires in here
        if any(e.name == "external.txt" for e in pane.view):
            break
    assert any(e.name == "external.txt" for e in pane.view)
    os.remove(pane.path + "/external.txt")
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        fltk.Fl.wait(0.1)
        if not any(e.name == "external.txt" for e in pane.view):
            break
    assert not any(e.name == "external.txt" for e in pane.view)


def test_f4_editor_configured(app, monkeypatch):
    import flcmd.viewer as viewer
    calls = []
    monkeypatch.setattr(viewer.subprocess, "Popen",
                        lambda argv, **k: calls.append(argv))
    app.cfg["editor"] = {"command": "myedit --flag"}
    pane = app.left
    _cursor_to(pane, "alpha.txt")
    app.dispatch("file.edit", pane)
    assert calls == [["myedit", "--flag", pane.path + "/alpha.txt"]]


def test_f4_editor_prompts_and_saves(app, monkeypatch):
    import flcmd.viewer as viewer
    from flcmd import config
    from flcmd.ui import dialogs
    calls = []
    monkeypatch.setattr(viewer.subprocess, "Popen",
                        lambda argv, **k: calls.append(argv))
    monkeypatch.setattr(dialogs, "ask_text", lambda *a, **k: "nano")
    app.cfg.pop("editor", None)
    pane = app.left
    _cursor_to(pane, "alpha.txt")
    app.dispatch("file.edit", pane)
    assert calls and calls[0][0] == "nano"
    assert config.load()["editor"]["command"] == "nano"  # persisted to ini


def test_shift_f4_creates_and_edits(app, monkeypatch):
    import flcmd.viewer as viewer
    from flcmd.ui import dialogs
    calls = []
    monkeypatch.setattr(viewer.subprocess, "Popen",
                        lambda argv, **k: calls.append(argv))
    monkeypatch.setattr(dialogs, "ask_text", lambda *a, **k: "notes.txt")
    app.cfg["editor"] = {"command": "ed"}
    pane = app.left
    app.dispatch("file.edit_new", pane)
    assert os.path.exists(pane.path + "/notes.txt")
    assert pane.current().name == "notes.txt"
    assert calls == [["ed", pane.path + "/notes.txt"]]


def test_enter_and_leave_archive(app):
    import zipfile
    pane = app.left
    zp = pane.path + "/arc.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("inner/file.txt", "zipped")
    pane.refresh(keep_cursor_name="arc.zip")
    assert pane.current().name == "arc.zip"
    app.dispatch("nav.open", pane)               # Enter opens the archive
    assert pane.vfs.scheme == "arc"
    assert {e.name for e in pane.view} == {"..", "inner"}
    _cursor_to(pane, "inner")
    app.dispatch("nav.open", pane)               # into inner/
    assert [e.name for e in pane.view if not e.is_dir] == ["file.txt"]
    app.dispatch("nav.up", pane)                 # back to archive root
    app.dispatch("nav.up", pane)                 # pops out of the archive
    assert pane.vfs.scheme == "file"
    assert pane.current().name == "arc.zip"      # cursor back on the archive
    os.remove(zp)


def test_copy_out_of_archive_gui(app, monkeypatch):
    import zipfile
    from flcmd.ui import dialogs
    pane, other = app.left, app.right
    zp = pane.path + "/arc2.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("data.bin", "payload")
    pane.refresh(keep_cursor_name="arc2.zip")
    app.dispatch("nav.open", pane)
    _cursor_to(pane, "data.bin")
    monkeypatch.setattr(dialogs, "ask_dest", lambda *a, **k: (other.path, False))
    app.dispatch("file.copy", pane)
    assert open(other.path + "/data.bin").read() == "payload"
    app.dispatch("nav.up", pane)
    os.remove(zp)
