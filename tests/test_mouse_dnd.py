"""Mouse selection and drag-out, driven by real X input events (xdotool)
against the app running on the test Xvfb display."""

import os
import shutil
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.gui

HELPER = os.path.join(os.path.dirname(__file__), "helpers", "gtk_drop_target.py")


def _need(tool):
    if not shutil.which(tool):
        pytest.skip(f"{tool} not installed")


@pytest.fixture()
def app(xdisplay, isolated_config, sample_tree):
    _need("xdotool")
    import fltk
    from flcmd.app import App

    a = App(sample_tree, sample_tree)
    a.win.position(0, 0)
    a.show()
    for _ in range(10):
        fltk.Fl.check()
    # park the pointer away so consecutive tests can't register double-clicks
    subprocess.run(["xdotool", "mousemove", "--sync", "640", "760"])
    fltk.Fl.check()
    yield a
    a.quit()
    fltk.Fl.check()


def _row_xy(app, pane, row):
    """Screen coords of a row center (win.x/y reflect the real position)."""
    from flcmd.panes.panel import HDR_H, ROW_H
    t = pane.table
    return (app.win.x() + t.x() + 40,
            app.win.y() + t.y() + HDR_H + row * ROW_H + ROW_H // 2)


def _click(app, pane, row, *mods):
    import fltk
    time.sleep(0.35)  # stay out of FLTK's double-click window
    x, y = _row_xy(app, pane, row)
    pre = [c for m in mods for c in ("keydown", m)]
    post = [c for m in mods for c in ("keyup", m)]
    # jitter first: 'mousemove --sync' hangs if the pointer is already there
    subprocess.run(["xdotool", "mousemove", str(x + 9), str(y + 5),
                    "mousemove", "--sync", str(x), str(y),
                    *pre, "click", "1", *post], check=True)
    deadline = time.monotonic() + 2
    while pane.cursor != row and time.monotonic() < deadline:
        fltk.Fl.wait(0.02)
    for _ in range(5):
        fltk.Fl.check()


def test_click_selection(app):
    pane = app.left  # view: .. adir bdir alpha.txt beta.log
    _click(app, pane, 3)
    assert pane.cursor == 3, "row hit-test calibration is off"
    assert pane.selected == {"alpha.txt"}
    _click(app, pane, 4, "Control_L")
    assert pane.selected == {"alpha.txt", "beta.log"}
    _click(app, pane, 4, "Control_L")  # ctrl+click toggles off
    assert pane.selected == {"alpha.txt"}
    _click(app, pane, 1)
    assert pane.selected == {"adir"}
    _click(app, pane, 3, "Shift_L")  # range from anchor (1) to 3
    assert pane.selected == {"adir", "bdir", "alpha.txt"}


def test_click_dead_space_clears(app):
    import fltk
    pane = app.left
    _click(app, pane, 3)
    assert pane.selected == {"alpha.txt"}
    t = pane.table
    x = app.win.x() + t.x() + 40
    y = app.win.y() + t.y() + t.h() - 30  # well below the 5 rows
    subprocess.run(["xdotool", "mousemove", str(x + 9), str(y + 5),
                    "mousemove", "--sync", str(x), str(y),
                    "click", "1"], check=True)
    deadline = time.monotonic() + 2
    while pane.selected and time.monotonic() < deadline:
        fltk.Fl.wait(0.02)
    assert pane.selected == set()


def test_drag_out_to_gtk(app, tmp_path):
    import fltk
    syspy = "/usr/bin/python3"
    if subprocess.run([syspy, "-c", "import gi"], capture_output=True).returncode:
        pytest.skip("pygobject not available in system python")
    out = str(tmp_path / "dropped.txt")
    helper = subprocess.Popen([syspy, HELPER, out],
                              stdout=subprocess.PIPE, text=True)
    try:
        assert helper.stdout.readline().strip() == "READY"
        time.sleep(0.3)
        pane = app.left
        _click(app, pane, 3)  # select alpha.txt
        x, y = _row_xy(app, pane, 3)
        # press, cross the drag threshold, travel to the GTK window, drop.
        # Separate xdotool calls in a detached script: a single chained
        # invocation stalls, and the app thread blocks in the drag loop.
        script = f"""
sleep 0.4
xdotool mousemove {x + 9} {y + 5}
xdotool mousemove --sync {x} {y}; xdotool mousedown 1; sleep 0.2
xdotool mousemove --sync {x + 30} {y + 10}; sleep 0.2
xdotool mousemove --sync 600 200; sleep 0.2
xdotool mousemove --sync 1100 250; sleep 0.4
xdotool mouseup 1
"""
        subprocess.Popen(["bash", "-c", script])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            fltk.Fl.wait(0.05)  # the drag loop runs inside this
            if os.path.exists(out) and helper.poll() is not None:
                break
        assert os.path.exists(out), "GTK target never received the drop"
        received = open(out).read()
        assert "file://" in received and "/alpha.txt" in received
    finally:
        if helper.poll() is None:
            helper.kill()
