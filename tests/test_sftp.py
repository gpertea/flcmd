"""SFTP integration tests against a real host (pubkey auth via ssh_config
alias). Skipped when the host is unreachable. Uses a scratch dir under the
remote /tmp and cleans up after itself."""

import os
import subprocess
import time

import pytest

HOST = os.environ.get("FLCMD_TEST_SSH_HOST", "gvlin")


def _reachable() -> bool:
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4",
                        HOST, "true"], capture_output=True)
    return r.returncode == 0


pytestmark = [pytest.mark.ssh,
              pytest.mark.skipif(not _reachable(),
                                 reason=f"ssh host {HOST} not reachable")]


@pytest.fixture(scope="module")
def sess():
    from flcmd.ssh import SSHSession
    s = SSHSession(HOST)
    yield s
    s.close()


@pytest.fixture(scope="module")
def rvfs(sess):
    from flcmd.vfs.sftp import SftpVFS
    return SftpVFS(sess)


@pytest.fixture()
def rtmp(rvfs):
    d = f"/tmp/flcmd_test_{os.getpid()}_{int(time.time())}"
    rvfs.mkdir(d)
    yield d
    # best-effort recursive cleanup
    from flcmd.ops import delete_op
    from test_fileops import ScriptedCtl
    try:
        delete_op(rvfs, [d], ScriptedCtl(["Skip All"]))
    except Exception:
        pass


def test_alias_resolution():
    from flcmd.ssh.config import lookup
    info = lookup(HOST)
    assert info.get("hostname")  # the alias resolves to something


def test_home_and_listdir(sess, rvfs):
    assert sess.home.startswith("/")
    names = {e.name for e in rvfs.listdir(sess.home)}
    assert names  # a home dir has something in it


def test_roundtrip_copy(rvfs, rtmp, tmp_path):
    from flcmd.ops import copy_op
    from flcmd.vfs import LocalVFS
    from test_fileops import ScriptedCtl
    src = tmp_path / "hello.txt"
    payload = "flcmd sftp roundtrip\n" * 100
    src.write_text(payload)
    lv = LocalVFS()
    # local -> remote
    copy_op(lv, [str(src).replace("\\", "/")], rvfs, rtmp, ScriptedCtl())
    st = rvfs.stat(rtmp + "/hello.txt")
    assert st.size == len(payload)
    # remote -> local
    back = tmp_path / "back"
    back.mkdir()
    copy_op(rvfs, [rtmp + "/hello.txt"], lv,
            str(back).replace("\\", "/"), ScriptedCtl())
    assert (back / "hello.txt").read_text() == payload


def test_mkdir_rename_delete(rvfs, rtmp):
    rvfs.mkdir(rtmp + "/sub")
    assert rvfs.is_dir(rtmp + "/sub")
    with rvfs.open(rtmp + "/sub/x.bin", "wb") as f:
        f.write(b"\x00\x01\x02" * 1000)
    rvfs.rename(rtmp + "/sub/x.bin", rtmp + "/sub/y.bin")
    assert rvfs.stat(rtmp + "/sub/y.bin").size == 3000
    assert not rvfs.exists(rtmp + "/sub/x.bin")
    rvfs.remove(rtmp + "/sub/y.bin")
    rvfs.rmdir(rtmp + "/sub")
    assert not rvfs.exists(rtmp + "/sub")


def test_symlinks_remote(rvfs, rtmp):
    with rvfs.open(rtmp + "/real.txt", "wb") as f:
        f.write(b"target")
    rvfs.symlink("real.txt", rtmp + "/lnk")
    st = rvfs.stat(rtmp + "/lnk")
    assert st.is_link
    assert rvfs.readlink(rtmp + "/lnk") == "real.txt"
    assert rvfs.stat_follow(rtmp + "/lnk").size == 6


def test_copy_tree_to_remote_and_back(rvfs, rtmp, tmp_path):
    from flcmd.ops import copy_op
    from flcmd.vfs import LocalVFS
    from test_fileops import ScriptedCtl
    src = tmp_path / "tree"
    (src / "d1" / "d2").mkdir(parents=True)
    (src / "top.txt").write_text("t")
    (src / "d1" / "mid.txt").write_text("m" * 5000)
    (src / "d1" / "d2" / "leaf.txt").write_text("leaf")
    lv = LocalVFS()
    ctl = ScriptedCtl()
    copy_op(lv, [str(src).replace("\\", "/")], rvfs, rtmp, ctl)
    assert ctl.done_items == ctl.total_items
    back = tmp_path / "rback"
    back.mkdir()
    copy_op(rvfs, [rtmp + "/tree"], lv, str(back).replace("\\", "/"),
            ScriptedCtl())
    assert (back / "tree" / "d1" / "d2" / "leaf.txt").read_text() == "leaf"
    assert (back / "tree" / "d1" / "mid.txt").read_text() == "m" * 5000


@pytest.mark.gui
def test_gui_connect_disconnect(xdisplay, isolated_config, sample_tree,
                                monkeypatch):
    import fltk
    from flcmd.app import App
    from flcmd.ui import dialogs
    a = App(sample_tree, sample_tree)
    a.show()
    for _ in range(10):
        fltk.Fl.check()
    try:
        monkeypatch.setattr(dialogs, "ask_text", lambda *args, **k: HOST)
        app_pane = a.left
        a.dispatch("net.connect", app_pane)
        assert app_pane.vfs.scheme == "sftp"
        assert app_pane.path.startswith("/")
        assert app_pane.header.label().strip().startswith("sftp://")
        assert any(e.name for e in app_pane.view)
        a.dispatch("net.disconnect", app_pane)
        assert app_pane.vfs.scheme == "file"
        assert app_pane.path == sample_tree
    finally:
        a.quit()
        fltk.Fl.check()
