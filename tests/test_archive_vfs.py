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


# -- single-stream .gz/.bz2/.xz: one member named after the archive --------
@pytest.mark.parametrize("ext,opener", [
    (".gz", "gzip"), (".bz2", "bz2"), (".xz", "lzma")])
def test_single_stream(tmp_path, ext, opener):
    import importlib
    mod = importlib.import_module(opener)
    payload = b"single stream payload\n" * 10
    p = tmp_path / ("notes.txt" + ext)
    with mod.open(p, "wb") as f:
        f.write(payload)
    ap = str(p).replace("\\", "/")
    assert is_archive(ap)
    v = ArchiveVFS(ap)
    entries = v.listdir("/")
    assert [e.name for e in entries] == ["notes.txt"]
    assert not entries[0].is_dir
    with v.open("/notes.txt") as f:
        assert f.read() == payload
    if ext == ".gz":  # size comes from the gzip trailer
        assert entries[0].size == len(payload)


def test_single_stream_copy_out(tmp_path):
    import gzip
    p = tmp_path / "data.bin.gz"
    with gzip.open(p, "wb") as f:
        f.write(b"x" * 5000)
    dst = tmp_path / "out"
    dst.mkdir()
    v = ArchiveVFS(str(p).replace("\\", "/"))
    copy_op(v, ["/data.bin"], LocalVFS(), str(dst).replace("\\", "/"),
            ScriptedCtl())
    assert (dst / "data.bin").read_bytes() == b"x" * 5000


def test_tar_gz_still_a_tar(tmp_path):
    """A .tar.gz must browse as a tar, not as a single .gz stream."""
    src = tmp_path / "s"
    src.mkdir()
    (src / "one.txt").write_text("1")
    (src / "two.txt").write_text("2")
    p = tmp_path / "bundle.tar.gz"
    with tarfile.open(p, "w:gz") as t:
        for n in ("one.txt", "two.txt"):
            t.add(src / n, arcname=n)
    v = ArchiveVFS(str(p).replace("\\", "/"))
    assert sorted(e.name for e in v.listdir("/")) == ["one.txt", "two.txt"]


def test_rar_without_tool_reports_clearly(tmp_path, monkeypatch):
    import flcmd.vfs.archive as arc
    monkeypatch.setattr(arc.shutil, "which", lambda *_: None)
    p = tmp_path / "x.rar"
    p.write_bytes(b"Rar!\x1a\x07\x00")
    assert is_archive(str(p))
    with pytest.raises(OSError, match="7z, unrar or bsdtar"):
        arc.ArchiveVFS(str(p).replace("\\", "/"))
