"""GUI tests run on their own Xvfb display, never the user's DISPLAY."""

import os
import shutil
import socket
import subprocess
import time

import pytest


def _free_display() -> int:
    for n in range(90, 190):
        if not os.path.exists(f"/tmp/.X11-unix/X{n}"):
            return n
    raise RuntimeError("no free X display")


@pytest.fixture(scope="session")
def xdisplay():
    if not shutil.which("Xvfb"):
        pytest.skip("Xvfb not installed")
    n = _free_display()
    proc = subprocess.Popen(
        ["Xvfb", f":{n}", "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    old = os.environ.get("DISPLAY")
    os.environ["DISPLAY"] = f":{n}"
    for _ in range(50):
        if os.path.exists(f"/tmp/.X11-unix/X{n}"):
            break
        time.sleep(0.1)
    yield os.environ["DISPLAY"]
    if old is None:
        os.environ.pop("DISPLAY", None)
    else:
        os.environ["DISPLAY"] = old
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture()
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    return tmp_path


@pytest.fixture()
def sample_tree(tmp_path):
    root = tmp_path / "tree"
    (root / "adir").mkdir(parents=True)
    (root / "bdir" / "nested").mkdir(parents=True)
    (root / "alpha.txt").write_text("hello alpha\n")
    (root / "beta.log").write_text("x" * 1000)
    (root / "bdir" / "deep.txt").write_text("deep\n")
    return str(root).replace("\\", "/")
