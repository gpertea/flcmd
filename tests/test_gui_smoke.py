"""GUI smoke tests: run the real app on Xvfb, drive it via dispatch()."""

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture()
def app(xdisplay, isolated_config, sample_tree):
    import fltk
    from flcmd.app import App

    a = App(sample_tree, sample_tree)
    a.show()
    for _ in range(5):
        fltk.Fl.check()
    yield a
    a.quit()
    fltk.Fl.check()


def _names(pane):
    return [e.name for e in pane.view]


def test_listing_and_layout(app):
    # dirs first after '..', then files sorted by name
    assert _names(app.left) == ["..", "adir", "bdir", "alpha.txt", "beta.log"]
    assert app.left.header.label().strip() == app.left.path


def test_navigation(app):
    import fltk
    pane = app.left
    pane.set_cursor(2)  # bdir
    app.dispatch("nav.open", pane)
    fltk.Fl.check()
    assert pane.path.endswith("/bdir")
    assert _names(pane) == ["..", "nested", "deep.txt"]
    app.dispatch("nav.up", pane)
    assert pane.current().name == "bdir"  # cursor lands on dir we left


def test_pane_switch_and_swap(app):
    import fltk
    assert app.active() is app.left
    app.dispatch("pane.switch", app.left)
    fltk.Fl.check()
    assert app.active() is app.right
    app.left.set_path(app.left.path + "/adir")
    lp, rp = app.left.path, app.right.path
    app.dispatch("pane.swap", app.left)
    assert (app.left.path, app.right.path) == (rp, lp)


def test_selection(app):
    pane = app.left
    pane.set_cursor(3)  # alpha.txt
    app.dispatch("sel.toggle", pane)
    assert pane.selected == {"alpha.txt"}
    assert pane.cursor == 4  # Insert advances
    app.dispatch("sel.invert", pane)
    assert pane.selected == {"beta.log"}
    app.dispatch("sel.all", pane)
    assert "adir" in pane.selected and "alpha.txt" in pane.selected
    app.dispatch("sel.none", pane)
    assert pane.selected == set()
    pane.select_glob("*.txt")
    assert pane.selected == {"alpha.txt"}


def test_sorting(app):
    pane = app.left
    app.dispatch("sort.size", pane)
    files = [e.name for e in pane.view if not e.is_dir]
    assert files == ["alpha.txt", "beta.log"]  # 12 < 1000
    app.dispatch("sort.size", pane)  # toggle reverse
    files = [e.name for e in pane.view if not e.is_dir]
    assert files == ["beta.log", "alpha.txt"]


def test_quick_search(app):
    pane = app.left
    pane._quick_search("be")
    assert pane.current().name == "beta.log"


def test_viewer_opens(app, sample_tree):
    import fltk
    pane = app.left
    pane.set_cursor(3)  # alpha.txt
    app.dispatch("file.view", pane)
    fltk.Fl.check()
    assert app._viewers and app._viewers[-1].visible()
    assert "hello alpha" in app._viewers[-1].buf.text()
    app._viewers[-1].hide()


def test_config_saved_on_quit(app, isolated_config):
    from flcmd import config
    app.quit()
    cfg = config.load()
    assert cfg["left"]["path"] == app.left.path
    assert "w" in cfg["window"]


def test_symlink_dir_navigation(app, sample_tree):
    import os

    import fltk
    from flcmd import paths
    os.symlink(paths.to_native(paths.join(sample_tree, "adir")),
               paths.to_native(paths.join(sample_tree, "zlink")))
    pane = app.left
    pane.refresh()
    idx = [e.name for e in pane.view].index("zlink")
    assert pane.view[idx].is_dir and pane.view[idx].is_link
    pane.set_cursor(idx)
    app.dispatch("nav.open", pane)
    fltk.Fl.check()
    assert pane.path.endswith("/zlink")  # navigated through the link


def test_symlink_f3_shows_target(app, sample_tree):
    import os

    import fltk
    from flcmd import paths
    tgt = paths.join(sample_tree, "adir")
    os.symlink(paths.to_native(tgt),
               paths.to_native(paths.join(sample_tree, "zlink")))
    pane = app.left
    pane.refresh()
    pane.set_cursor([e.name for e in pane.view].index("zlink"))
    app.dispatch("file.view", pane)
    fltk.Fl.check()
    assert "zlink ->" in pane.footer.label()


def test_history_back_forward(app):
    import fltk
    pane = app.left
    start = pane.path
    pane.set_cursor([e.name for e in pane.view].index("bdir"))
    app.dispatch("nav.open", pane)
    fltk.Fl.check()
    inside = pane.path
    assert inside.endswith("/bdir") and pane.hist_back
    app.dispatch("nav.back", pane)
    fltk.Fl.check()
    assert pane.path == start and pane.hist_fwd
    app.dispatch("nav.fwd", pane)
    fltk.Fl.check()
    assert pane.path == inside


def test_cmdline_cd(app):
    import fltk
    pane = app.active()
    start = pane.path
    app._run_command("cd bdir")
    fltk.Fl.check()
    assert pane.path == start + "/bdir"
    app._run_command("cd ..")
    assert pane.path == start
    app._run_command("cd /no/such/dir-xyz")
    assert pane.path == start  # unchanged, error flashed
    assert "cd:" in pane.footer.label()


def test_header_click_sorts(app):
    pane, tbl = app.left, app.left.table
    # simulate the release-path sort: click on the Size column header
    pane.sort("size")
    assert pane.sort_key == "size" and not pane.sort_rev
    pane.sort("size")
    assert pane.sort_rev  # second click toggles direction
    hit = tbl.header_hit(tbl.x() + 10, tbl.y() + 5)
    assert hit == (0, False)  # inside Name header, not near a border


def test_scroll_resets_on_dir_change(app, sample_tree):
    import os

    import fltk
    from flcmd import paths
    m1, m2 = paths.join(sample_tree, "many1"), paths.join(sample_tree, "many2")
    for d in (m1, m2):
        os.mkdir(d)
        for i in range(200):
            open(os.path.join(d, f"f{i:03}.txt"), "w").close()
    pane = app.left
    pane.set_path(m1)
    fltk.Fl.check()
    pane.set_cursor(len(pane.view) - 1)  # scroll to the bottom
    assert pane.table.top_row() > 0
    pane.set_path(m2)
    fltk.Fl.check()
    assert pane.table.top_row() == 0  # new dir: view starts at the top
