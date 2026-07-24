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


def _xserver_cmd(n: int) -> list[str] | None:
    if shutil.which("Xvfb"):
        return ["Xvfb", f":{n}", "-screen", "0", "1280x800x24",
                "-nolisten", "tcp"]
    if shutil.which("Xvnc"):  # tigervnc fallback: same headless job
        return ["Xvnc", f":{n}", "-geometry", "1280x800", "-depth", "24",
                "-SecurityTypes", "None", "-localhost"]
    return None


@pytest.fixture(scope="session")
def xdisplay():
    n = _free_display()
    cmd = _xserver_cmd(n)
    if cmd is None:
        pytest.skip("no virtual X server (install xvfb or tigervnc)")
    proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    # cover all platforms' config roots (XDG on Linux, APPDATA on Windows,
    # HOME for the macOS/other expanduser fallbacks)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    monkeypatch.setenv("HOME", str(tmp_path))
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
