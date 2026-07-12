"""Headless archive VFS tests (zip and tar) + copy-out via the ops engine."""

import os
import tarfile
import zipfile

import pytest

from flcmd.ops import copy_op
from flcmd.vfs import LocalVFS
from flcmd.vfs.archive import ArchiveVFS, is_archive
from test_fileops import ScriptedCtl


@pytest.fixture()
def zip_path(tmp_path):
    p = tmp_path / "test.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("top.txt", "top content")
        z.writestr("docs/readme.md", "# readme")
        z.writestr("docs/deep/nested.txt", "nested")  # implicit dirs
    return str(p).replace("\\", "/")


@pytest.fixture()
def tar_path(tmp_path):
    src = tmp_path / "tsrc"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_text("aaa")
    (src / "sub" / "b.txt").write_text("bbb")
    os.symlink("a.txt", src / "lnk")
    p = tmp_path / "test.tar.gz"
    with tarfile.open(p, "w:gz") as t:
        t.add(src, arcname=".")
    return str(p).replace("\\", "/")


def test_is_archive():
    assert is_archive("x.zip") and is_archive("y.TAR.GZ") and is_archive("z.tgz")
    assert not is_archive("a.txt") and not is_archive("gz")


def test_zip_browse(zip_path):
    a = ArchiveVFS(zip_path)
    names = {e.name: e for e in a.listdir("/")}
    assert set(names) == {"top.txt", "docs"}
    assert names["docs"].is_dir and not names["top.txt"].is_dir
    docs = {e.name for e in a.listdir("/docs")}
    assert docs == {"readme.md", "deep"}  # implicit dir materialized
    with a.open("/docs/deep/nested.txt") as f:
        assert f.read() == b"nested"
    assert a.stat("/docs/readme.md").size == len("# readme")
    assert a.display("/docs").endswith("test.zip:/docs")
    a.close()


def test_tar_browse(tar_path):
    a = ArchiveVFS(tar_path)
    names = {e.name: e for e in a.listdir("/")}
    assert {"a.txt", "sub", "lnk"} <= set(names)
    assert names["lnk"].is_link
    assert a.readlink("/lnk") == "a.txt"
    with a.open("/sub/b.txt") as f:
        assert f.read() == b"bbb"
    a.close()


def test_archive_readonly(zip_path):
    a = ArchiveVFS(zip_path)
    for fn in (lambda: a.mkdir("/x"), lambda: a.remove("/top.txt"),
               lambda: a.rename("/top.txt", "/y"),
               lambda: a.open("/new", "wb")):
        with pytest.raises(OSError):
            fn()
    a.close()


def test_copy_out_of_archive(zip_path, tmp_path):
    dst = tmp_path / "out"
    dst.mkdir()
    a = ArchiveVFS(zip_path)
    ctl = ScriptedCtl()
    copy_op(a, ["/docs"], LocalVFS(), str(dst).replace("\\", "/"), ctl)
    assert open(dst / "docs" / "readme.md").read() == "# readme"
    assert open(dst / "docs" / "deep" / "nested.txt").read() == "nested"
    a.close()


def test_bad_archive(tmp_path):
    p = tmp_path / "fake.zip"
    p.write_text("not an archive")
    with pytest.raises(Exception):
        ArchiveVFS(str(p).replace("\\", "/"))
