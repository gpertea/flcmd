"""Thumbnail view + quick-view preview panel tests (generated images)."""

import time

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture()
def imgdir(tmp_path):
    from PIL import Image
    d = tmp_path / "pics"
    (d / "sub").mkdir(parents=True)
    Image.new("RGB", (300, 200), (200, 30, 30)).save(d / "red.png")
    Image.new("RGB", (200, 300), (30, 30, 200)).save(d / "blue.jpg")
    Image.new("RGB", (640, 480), (30, 200, 30)).save(d / "green.webp")
    (d / "notes.txt").write_text("not an image")
    return str(d).replace("\\", "/")


@pytest.fixture()
def app(xdisplay, isolated_config, imgdir, tmp_path):
    import fltk
    from flcmd.app import App
    other = tmp_path / "other"
    other.mkdir()
    a = App(imgdir, str(other).replace("\\", "/"))
    a.show()
    for _ in range(10):
        fltk.Fl.check()
    yield a
    a.quit()
    fltk.Fl.check()


def _pump(secs):
    import fltk
    end = time.monotonic() + secs
    while time.monotonic() < end:
        fltk.Fl.wait(0.02)


def _cursor_to(pane, name):
    for i, e in enumerate(pane.view):
        if e.name == name:
            pane.set_cursor(i)
            return
    raise AssertionError(f"{name} not in view")


def test_loader(imgdir, xdisplay):
    from flcmd.panes import images
    img = images.load_full(imgdir + "/red.png")
    assert img and img.data_w() == 300 and img.data_h() == 200
    images.release_full(img)
    th = images.load_thumb(imgdir + "/blue.jpg", 96)
    assert th and max(th.w(), th.h()) == 96
    wp = images.load_full(imgdir + "/green.webp")  # Pillow fallback
    assert wp and wp.data_w() == 640
    images.release_full(wp)
    assert images.load_full(imgdir + "/notes.txt") is None
    assert images.is_image("a.PNG") and not images.is_image("a.txt")


def test_thumbs_mode(app):
    pane = app.left
    app.dispatch("pane.thumbs", pane)
    assert pane.mode == "thumbs" and pane.thumbs.visible()
    _pump(0.5)  # let the incremental loader run
    assert isinstance(pane.thumbs._cache.get("red.png"), object)
    assert pane.thumbs._cache["red.png"] is not False
    th = pane.thumbs._cache["red.png"]
    assert max(th.w(), th.h()) <= pane.thumbs.tile
    # grid navigation and selection still work
    _cursor_to(pane, "red.png")
    app.dispatch("sel.toggle", pane)
    assert "red.png" in pane.selected
    app.dispatch("pane.thumbs", pane)  # toggles back
    assert pane.mode == "list"


def test_thumb_size_config(app):
    from flcmd import config
    pane = app.left
    app.dispatch("pane.thumbs", pane)
    app.dispatch("thumbs.size:192", pane)
    assert pane.thumbs.tile == 192
    assert pane.thumbs.cell_w() == 192 + 12
    assert config.load()["thumbs"]["size"] == 192


def test_quickview_panel(app):
    import fltk
    pane, other = app.left, app.right
    app.dispatch("pane.quickview", pane)   # other pane becomes the preview
    assert other.mode == "preview" and other.preview.visible()
    _cursor_to(pane, "red.png")
    _pump(0.3)  # debounce + load
    pv = other.preview
    assert pv._img is not None
    assert pv._img.data_w() == 300
    assert "Preview: red.png" in other.header.label()
    # zoom lock: 100% must show the image at its native size
    pv.set_zoom("100")
    assert pv._img.w() == 300 and pv._img.h() == 200
    pv.set_zoom("fitw")
    sb = fltk.Fl.scrollbar_size()
    assert pv._img.w() == pv.scroll.w() - sb
    pv.set_zoom("fit")
    assert pv._img.w() <= pv.scroll.w() and pv._img.h() <= pv.scroll.h()
    # non-image file: message, image cleared
    _cursor_to(pane, "notes.txt")
    _pump(0.3)
    assert pv._img is None
    # toggle off restores the previous mode
    app.dispatch("pane.quickview", pane)
    assert other.mode == "list"


def test_quickview_focus_stays(app):
    pane, other = app.left, app.right
    app.dispatch("pane.quickview", pane)
    app.dispatch("pane.switch", pane)  # must NOT focus the preview pane
    assert app.active() is pane
    app.dispatch("pane.quickview", pane)
