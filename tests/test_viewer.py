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


@pytest.fixture()
def bigfile(tmp_path, isolated_config):
    from flcmd import config
    config.save({"viewer": {"window_mb": 1}})  # small window for the test
    p = tmp_path / "big.txt"
    with open(p, "w") as f:
        for i in range(120_000):
            f.write(f"line {i:07d} {'x' * 16}\n")   # ~3.7 MB, 31 B/line
    return str(p).replace("\\", "/")


@pytest.fixture()
def bwin(xdisplay, bigfile):
    import fltk
    from flcmd.viewer import ViewerWindow
    w = ViewerWindow([bigfile])
    w.show()
    for _ in range(5):
        fltk.Fl.check()
    yield w
    w.hide()
    fltk.Fl.check()


def test_paged_open_is_windowed(bwin):
    assert bwin.paged
    assert bwin.fsize > 3_000_000
    assert len(bwin.data) <= (1 << 20)
    assert bwin.text.startswith("line 0000000")


def test_paged_window_load_boundaries(bwin):
    # window starts and ends on whole lines wherever it lands
    bwin._load_window(bwin.fsize // 2)
    assert bwin.win_off > 0
    assert bwin.data.startswith(b"line ")      # opening line intact
    assert bwin.data.endswith(b"\n")           # closing line intact
    first = int(bwin.data[5:12])
    assert abs(first - 60_000) < 25_000        # roughly the middle


def test_paged_jump_to_end(bwin):
    bwin.jump_to(bwin.fsize)
    assert "line 0119999" in bwin.text         # last line reachable
    assert bwin.win_off + len(bwin.data) == bwin.fsize


def test_paged_window_overlap_forward(bwin):
    # sliding the window forward by half keeps a contiguous, advancing view
    bwin._load_window(bwin.fsize // 2)
    off0, end0 = bwin.win_off, bwin.win_off + len(bwin.data)
    mid_lines = bwin.data.split(b"\n")
    mid_line = int(mid_lines[len(mid_lines) // 2][5:12])  # a whole line
    bwin._load_window(off0 + len(bwin.data) // 2)
    assert bwin.win_off > off0                 # advanced
    assert bwin.win_off < end0                 # overlaps previous window
    assert f"line {mid_line:07d}".encode() in bwin.data


def test_paged_search_streams_whole_file(bwin):
    bwin.search_term = "line 0100000"          # ~3.1 MB in, past first window
    bwin.find(1, from_start=True)
    assert "not found" not in bwin.status.label()
    assert bwin.win_off > (1 << 20)            # window moved to the hit
    assert bwin.buf.selection_text().lower() == "line 0100000"


def test_paged_search_backward_wraps(bwin):
    hit = bwin._stream_find(b"line 0119999", bwin.fsize, -1)
    assert hit > 0
    assert bwin._read(hit, 12) == b"line 0119999"


def test_paged_hex_alignment(bwin):
    bwin.do_action("mode:hex")
    assert bwin.win_off % 16 == 0
    bwin._load_window(bwin.fsize // 2)
    first = bwin.text.splitlines()[0] if bwin.text else ""
    bwin.render()
    first = bwin.text.splitlines()[0]
    assert int(first[:8], 16) == bwin.win_off  # absolute file offsets shown
    bwin.do_action("mode:text")


@pytest.fixture()
def imgfile(tmp_path):
    from PIL import Image
    p = tmp_path / "photo.png"
    Image.new("RGB", (400, 260), (120, 40, 220)).save(p)
    return str(p).replace("\\", "/")


def test_image_mode(xdisplay, isolated_config, imgfile, tmp_path):
    import fltk
    from flcmd.viewer import ViewerWindow
    t = tmp_path / "t.txt"
    t.write_text("plain text")
    w = ViewerWindow([imgfile, str(t).replace("\\", "/")])
    w.show()
    for _ in range(5):
        fltk.Fl.check()
    try:
        assert w.kind == "image" and w.iscroll.visible()
        assert w._img.data_w() == 400
        assert "image" in w.status.label() and "400 x 260" in w.status.label()
        w.do_action("izoom:100")
        assert w._img.w() == 400 and w._img.h() == 260
        w.do_action("izoom:cycle")   # 100 -> fit
        assert w.opts["izoom"] == "fit"
        assert w._img.w() <= w.iscroll.w()
        w.do_action("mode:hex")      # raw bytes of the png
        assert w.kind == "hex" and w.disp.visible() and not w.iscroll.visible()
        assert "89 50 4e 47" in w.buf.text()[:60]   # PNG magic
        w.do_action("mode:image")    # back to image
        assert w.kind == "image"
        w.do_action("next")          # text file: image widgets hidden;
        assert not w.iscroll.visible()
        assert w.kind == "hex"       # the chosen text/hex mode is sticky
        w.do_action("mode:text")
        assert "plain text" in w.buf.text()
        w.do_action("prev")
        assert w.kind == "image"
    finally:
        w.hide()
        fltk.Fl.check()
