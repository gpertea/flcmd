"""Headless tests for the file-operation engine (no GUI, no threads:
ask() is scripted and ops run on the test thread)."""

import os
import time

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


def test_copy_rename(vfs, src, dst):
    copy_op(vfs, [src + "/a.txt"], vfs, dst, ScriptedCtl(), rename="b.txt")
    assert open(dst + "/b.txt").read() == "alpha"
    assert os.path.exists(src + "/a.txt")


def test_move_rename_same_dir(vfs, src):
    copy_op(vfs, [src + "/a.txt"], vfs, src, ScriptedCtl(), move=True,
            rename="renamed.txt")
    assert open(src + "/renamed.txt").read() == "alpha"
    assert not os.path.exists(src + "/a.txt")


@pytest.fixture()
def conflict(tmp_path):
    """src/dst with the same three names; sources newer except 'mid'."""
    s, d = tmp_path / "cs", tmp_path / "cd"
    s.mkdir(), d.mkdir()
    now = time.time()
    for n, sm, dm in (("new.txt", now, now - 90000),      # source newer
                      ("old.txt", now - 90000, now),      # target newer
                      ("mid.txt", now, now - 90000)):
        (s / n).write_text("SRC-" + n)
        (d / n).write_text("DST-" + n)
        os.utime(s / n, (sm, sm))
        os.utime(d / n, (dm, dm))
    return str(s).replace("\\", "/"), str(d).replace("\\", "/")


def _names(sdir):
    return sorted(f"{sdir}/{n}" for n in ("new.txt", "old.txt", "mid.txt"))


def test_conflict_skip_all(vfs, conflict):
    s, d = conflict
    ctl = ScriptedCtl(["Skip All"])          # one prompt covers the rest
    copy_op(vfs, _names(s), vfs, d, ctl)
    assert len(ctl.asked) == 1
    for n in ("new.txt", "old.txt", "mid.txt"):
        assert open(f"{d}/{n}").read() == "DST-" + n


def test_conflict_overwrite_all(vfs, conflict):
    s, d = conflict
    ctl = ScriptedCtl(["Overwrite All"])
    copy_op(vfs, _names(s), vfs, d, ctl)
    assert len(ctl.asked) == 1
    for n in ("new.txt", "old.txt", "mid.txt"):
        assert open(f"{d}/{n}").read() == "SRC-" + n


def test_conflict_overwrite_all_older(vfs, conflict):
    """TC semantics: replace only targets the source supersedes."""
    s, d = conflict
    ctl = ScriptedCtl(["Overwrite All Older"])
    copy_op(vfs, _names(s), vfs, d, ctl)
    assert len(ctl.asked) == 1
    assert open(f"{d}/new.txt").read() == "SRC-new.txt"   # source newer
    assert open(f"{d}/mid.txt").read() == "SRC-mid.txt"   # source newer
    assert open(f"{d}/old.txt").read() == "DST-old.txt"   # target newer: kept


def test_conflict_per_item(vfs, conflict):
    s, d = conflict
    ctl = ScriptedCtl(["Skip", "Overwrite", "Skip"])  # asked once per file
    copy_op(vfs, _names(s), vfs, d, ctl)
    assert len(ctl.asked) == 3
    kept = [n for n in ("mid.txt", "new.txt", "old.txt")
            if open(f"{d}/{n}").read().startswith("DST")]
    assert len(kept) == 2  # two skipped, one overwritten


def test_copy_tree_preserves_times(vfs, src, dst):
    old = time.time() - 90000  # ~25h ago, clear of any clock skew
    for p in (src + "/a.txt", src + "/sub/b.txt", src + "/sub/deep",
              src + "/sub", src):
        os.utime(p, (old, old))
    copy_op(vfs, [src], vfs, dst, ScriptedCtl())
    for rel in ("/src/a.txt", "/src/sub/b.txt", "/src/sub", "/src"):
        assert abs(os.stat(dst + rel).st_mtime - old) < 2, rel


def test_copy_tree_times_across_vfs(src, dst):
    """Two VFS instances take the cross-VFS path (as sftp <-> local does),
    where copystat does not apply and set_times must do the work."""
    old = time.time() - 90000
    for p in (src + "/a.txt", src + "/sub/b.txt", src + "/sub", src):
        os.utime(p, (old, old))
    copy_op(LocalVFS(), [src], LocalVFS(), dst, ScriptedCtl())
    for rel in ("/src/a.txt", "/src/sub/b.txt", "/src/sub", "/src"):
        assert abs(os.stat(dst + rel).st_mtime - old) < 2, rel


def test_copy_times_off(vfs, src, dst):
    old = time.time() - 90000
    os.utime(src + "/a.txt", (old, old))
    copy_op(vfs, [src + "/a.txt"], vfs, dst, ScriptedCtl(), times=False)
    assert os.stat(dst + "/a.txt").st_mtime > old + 1000


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


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0,
                    reason="chmod 0 not enforced (Windows) or root")
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


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0,
                    reason="chmod 0 not enforced (Windows) or root")
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


@pytest.fixture()
def linked(tmp_path):
    d = tmp_path / "ln"
    (d / "real").mkdir(parents=True)
    (d / "real" / "f.txt").write_text("payload")
    try:  # native-sep targets: Windows stores them verbatim
        os.symlink(os.path.join("real", "f.txt"), d / "filelink")
    except OSError:
        pytest.skip("symlinks not available (Windows: needs developer mode)")
    os.symlink("real", d / "dirlink", target_is_directory=True)
    os.symlink("gone-target", d / "dangling")
    return str(d).replace("\\", "/")


def rl(p):
    """readlink with the target normalized to '/' separators."""
    return os.readlink(p).replace("\\", "/")


def test_copy_links_as_links(vfs, linked, dst):
    ctl = ScriptedCtl()
    copy_op(vfs, [linked + "/filelink", linked + "/dirlink",
                  linked + "/dangling"], vfs, dst, ctl)
    assert rl(dst + "/filelink") == "real/f.txt"
    assert rl(dst + "/dirlink") == "real"
    assert rl(dst + "/dangling") == "gone-target"
    assert not os.path.exists(dst + "/real")  # targets NOT copied


def test_copy_links_followed(vfs, linked, dst):
    ctl = ScriptedCtl()
    copy_op(vfs, [linked + "/filelink", linked + "/dirlink"], vfs, dst, ctl,
            follow_symlinks=True)
    assert not os.path.islink(dst + "/filelink")
    assert open(dst + "/filelink").read() == "payload"
    assert not os.path.islink(dst + "/dirlink")
    assert open(dst + "/dirlink/f.txt").read() == "payload"


def test_copy_tree_keeps_inner_links(vfs, linked, dst):
    ctl = ScriptedCtl()
    copy_op(vfs, [linked], vfs, dst, ctl)
    assert rl(dst + "/ln/filelink") == "real/f.txt"
    assert open(dst + "/ln/filelink").read() == "payload"  # relative works
    assert open(dst + "/ln/real/f.txt").read() == "payload"


def test_move_link(vfs, linked, dst):
    # force the copy+delete path (fast rename skipped via existing dst name)
    ctl = ScriptedCtl()
    copy_op(vfs, [linked + "/filelink"], vfs, dst, ctl, move=True)
    assert not os.path.lexists(linked + "/filelink")
    assert rl(dst + "/filelink") == "real/f.txt"


def test_delete_dir_symlink_not_recursive(vfs, linked):
    ctl = ScriptedCtl()
    delete_op(vfs, [linked + "/dirlink"], ctl)
    assert not os.path.lexists(linked + "/dirlink")
    assert os.path.exists(linked + "/real/f.txt")  # target untouched
