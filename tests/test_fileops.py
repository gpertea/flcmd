"""Headless tests for the file-operation engine (no GUI, no threads:
ask() is scripted and ops run on the test thread)."""

import os

import pytest

from flcmd import paths
from flcmd.ops import Cancelled, OpControl, copy_op, delete_op, scan
from flcmd.vfs import LocalVFS


class ScriptedCtl(OpControl):
    def __init__(self, answers=()):
        super().__init__()
        self.answers = list(answers)
        self.asked: list[str] = []

    def ask(self, text, buttons):
        self.check_cancel()
        self.asked.append(text)
        assert self.answers, f"unexpected prompt: {text}"
        ans = self.answers.pop(0)
        if ans == "Cancel":
            raise Cancelled()
        return ans


@pytest.fixture()
def vfs():
    return LocalVFS()


@pytest.fixture()
def src(tmp_path):
    d = tmp_path / "src"
    (d / "sub" / "deep").mkdir(parents=True)
    (d / "a.txt").write_text("alpha")
    (d / "sub" / "b.txt").write_text("beta" * 100)
    (d / "sub" / "deep" / "c.txt").write_text("c")
    return str(d).replace("\\", "/")


@pytest.fixture()
def dst(tmp_path):
    d = tmp_path / "dst"
    d.mkdir()
    return str(d).replace("\\", "/")


def test_scan(vfs, src):
    total, items = scan(vfs, [src])
    assert total == 5 + 400 + 1
    assert items == 6  # 3 dirs + 3 files


def test_copy_tree(vfs, src, dst):
    ctl = ScriptedCtl()
    copy_op(vfs, [src], vfs, dst, ctl)
    assert open(dst + "/src/sub/deep/c.txt").read() == "c"
    assert open(dst + "/src/a.txt").read() == "alpha"
    assert ctl.done_bytes == ctl.total_bytes == 406
    assert ctl.done_items == ctl.total_items == 6
    assert os.path.exists(src + "/a.txt")  # copy keeps sources


def test_copy_conflict_skip_and_overwrite(vfs, src, dst):
    os.mkdir(dst + "/src")
    with open(dst + "/src/a.txt", "w") as f:
        f.write("OLD")
    ctl = ScriptedCtl(["Skip"])
    copy_op(vfs, [src + "/a.txt"], vfs, dst + "/src", ctl)
    assert open(dst + "/src/a.txt").read() == "OLD"
    ctl = ScriptedCtl(["Overwrite"])
    copy_op(vfs, [src + "/a.txt"], vfs, dst + "/src", ctl)
    assert open(dst + "/src/a.txt").read() == "alpha"


def test_copy_overwrite_all(vfs, src, dst):
    copy_op(vfs, [src], vfs, dst, ScriptedCtl())
    with open(src + "/a.txt", "w") as f:
        f.write("new-a")
    with open(src + "/sub/b.txt", "w") as f:
        f.write("new-b")
    ctl = ScriptedCtl(["Overwrite All"])  # one answer covers every conflict
    copy_op(vfs, [src], vfs, dst, ctl)
    assert open(dst + "/src/a.txt").read() == "new-a"
    assert open(dst + "/src/sub/b.txt").read() == "new-b"


def test_move_fast_rename(vfs, src, dst):
    copy_op(vfs, [src + "/a.txt"], vfs, dst, ScriptedCtl(), move=True)
    assert not os.path.exists(src + "/a.txt")
    assert open(dst + "/a.txt").read() == "alpha"


def test_move_tree_with_conflict(vfs, src, dst):
    os.mkdir(dst + "/src")
    with open(dst + "/src/a.txt", "w") as f:
        f.write("OLD")
    ctl = ScriptedCtl(["Overwrite"])
    copy_op(vfs, [src], vfs, dst, ctl, move=True)
    assert not os.path.exists(src)
    assert open(dst + "/src/a.txt").read() == "alpha"
    assert open(dst + "/src/sub/deep/c.txt").read() == "c"


def test_delete(vfs, src):
    ctl = ScriptedCtl()
    delete_op(vfs, [src + "/sub"], ctl)
    assert not os.path.exists(src + "/sub")
    assert os.path.exists(src + "/a.txt")
    assert ctl.done_items == ctl.total_items == 4


def test_cancel(vfs, src, dst):
    ctl = ScriptedCtl()
    ctl.cancel_evt.set()
    with pytest.raises(Cancelled):
        copy_op(vfs, [src], vfs, dst, ctl)
    assert not os.path.exists(dst + "/src/a.txt")


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_error_skip(vfs, src, dst):
    os.chmod(src + "/a.txt", 0)
    try:
        ctl = ScriptedCtl(["Skip"])
        copy_op(vfs, [src + "/a.txt", src + "/sub/b.txt"], vfs, dst, ctl)
        assert ctl.asked and "a.txt" in ctl.asked[0]
        assert not os.path.exists(dst + "/a.txt")
        assert os.path.exists(dst + "/b.txt")
    finally:
        os.chmod(src + "/a.txt", 0o644)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_error_skip_all(vfs, tmp_path, dst):
    d = tmp_path / "s2"
    d.mkdir()
    for n in ("x.txt", "y.txt", "z.txt"):
        (d / n).write_text(n)
        os.chmod(d / n, 0)
    try:
        ctl = ScriptedCtl(["Skip All"])  # single prompt, rest silent
        copy_op(LocalVFS(), [str(d / n).replace("\\", "/")
                             for n in ("x.txt", "y.txt", "z.txt")],
                LocalVFS(), dst, ctl)
        assert len(ctl.asked) == 1
    finally:
        for n in ("x.txt", "y.txt", "z.txt"):
            os.chmod(d / n, 0o644)
