import pytest

from flcmd import paths
from flcmd.vfs import LocalVFS


@pytest.fixture()
def vfs():
    return LocalVFS()


def test_listdir(vfs, sample_tree):
    names = {e.name: e for e in vfs.listdir(sample_tree)}
    assert set(names) == {"adir", "bdir", "alpha.txt", "beta.log"}
    assert names["adir"].is_dir and not names["alpha.txt"].is_dir
    assert names["beta.log"].size == 1000
    assert names["beta.log"].ext == "log"
    assert names["adir"].ext == ""


def test_stat_open(vfs, sample_tree):
    p = paths.join(sample_tree, "alpha.txt")
    st = vfs.stat(p)
    assert st.name == "alpha.txt" and st.size > 0
    with vfs.open(p) as f:
        assert f.read().startswith(b"hello")


def test_symlinks(vfs, sample_tree):
    import os
    os.symlink(paths.to_native(paths.join(sample_tree, "adir")),
               paths.to_native(paths.join(sample_tree, "dlink")))
    os.symlink(paths.to_native(paths.join(sample_tree, "alpha.txt")),
               paths.to_native(paths.join(sample_tree, "flink")))
    os.symlink("no-such-target",
               paths.to_native(paths.join(sample_tree, "broken")))
    names = {e.name: e for e in vfs.listdir(sample_tree)}
    # dir symlink lists as a navigable dir but stays flagged as a link
    assert names["dlink"].is_dir and names["dlink"].is_link
    assert not names["flink"].is_dir and names["flink"].is_link
    assert not names["broken"].is_dir and names["broken"].is_link
    # lstat-based stat() still sees the link itself (op-safety invariant)
    assert vfs.stat(paths.join(sample_tree, "dlink")).is_link
    assert vfs.readlink(paths.join(sample_tree, "broken")) == "no-such-target"


def test_mutations(vfs, sample_tree):
    d = paths.join(sample_tree, "newdir")
    vfs.mkdir(d)
    assert vfs.is_dir(d)
    f = paths.join(sample_tree, "alpha.txt")
    f2 = paths.join(sample_tree, "renamed.txt")
    vfs.rename(f, f2)
    assert vfs.exists(f2) and not vfs.exists(f)
    vfs.remove(f2)
    vfs.rmdir(d)
    assert not vfs.exists(f2) and not vfs.exists(d)
