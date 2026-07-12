"""Viewer (TC Lister equivalent) tests: modes, wrap, ascii, search,
multi-file navigation, ini persistence."""

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture()
def files(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("hello viewer\nsecond line with WORD\nthird WORD line\n")
    b = tmp_path / "b.bin"
    b.write_bytes(bytes(range(256)))
    u = tmp_path / "u.txt"
    u.write_text("café naïve\n", encoding="utf-8")
    return [str(p).replace("\\", "/") for p in (a, b, u)]


@pytest.fixture()
def win(xdisplay, isolated_config, files):
    import fltk
    from flcmd.viewer import ViewerWindow

    w = ViewerWindow(files)
    w.show()
    for _ in range(5):
        fltk.Fl.check()
    yield w
    w.hide()
    fltk.Fl.check()


def test_text_mode_utf8(win):
    assert "hello viewer" in win.buf.text()
    assert win.opts["mode"] == "text"


def test_hex_mode(win):
    win.do_action("mode:hex")
    lines = win.buf.text().splitlines()
    assert lines[0].startswith("00000000  68 65 6c 6c 6f")  # 'hello'
    assert lines[0].rstrip().endswith("hello viewer.sec")  # \n shown as .
    win.do_action("mode:text")


def test_ascii_option(win):
    win.idx = 2  # u.txt with accents
    win.load_file()
    assert "café" in win.buf.text()
    win.do_action("ascii")
    assert "caf." in win.buf.text()
    assert "é" not in win.buf.text()
    win.do_action("ascii")


def test_next_prev_file(win, files):
    assert win.path() == files[0]
    win.do_action("next")
    assert win.path() == files[1]
    win.do_action("prev")
    assert win.path() == files[0]
    win.do_action("prev")  # already first: no-op
    assert win.path() == files[0]


def test_search(win):
    win.search_term = "word"
    win.find(1, from_start=True)
    first = win.disp.insert_position()
    assert win.text[first:first + 4] == "WORD"  # case-insensitive
    win.find(1)
    second = win.disp.insert_position()
    assert second > first
    win.find(1)  # wraps around
    assert win.disp.insert_position() == first
    win.find(-1)
    assert win.disp.insert_position() == second


def test_search_not_found(win):
    win.search_term = "zebra"
    win.find(1, from_start=True)
    assert "not found" in win.status.label()


def test_options_persist(win, files):
    import fltk
    from flcmd import config
    from flcmd.viewer import ViewerWindow

    win.do_action("size:16")
    win.do_action("wrap")  # default True -> False
    cfg = config.load()["viewer"]
    assert cfg["size"] == 16 and cfg["wrap"] is False
    w2 = ViewerWindow(files)
    assert w2.opts["size"] == 16 and w2.opts["wrap"] is False
    w2.hide()
    fltk.Fl.check()


def test_hexmode_disables_wrap(win):
    win.opts["wrap"] = True
    win.do_action("mode:hex")
    assert "wrap" not in win.status.label()
    win.do_action("mode:text")
