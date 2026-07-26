"""Read-only archive VFS: browse zip/tar/rar archives as directories.
Copy-out works through the normal ops engine (open() streams members);
mutation raises OSError so ops surface a clean error. Pack support later.

Formats: zip and tar (incl. .tar.gz/.tgz/.tar.bz2/.tar.xz) via stdlib;
single-stream .gz/.bz2/.xz shown as a one-member archive; rar/7z through
an external tool (7z, unrar or bsdtar) when one is on PATH."""

import bz2
import gzip
import lzma
import os
import shutil
import struct
import subprocess
import tarfile
import zipfile
from datetime import datetime

from .. import paths
from .base import VFS, DirEntry

_TAR_EXT = (".tar", ".tgz", ".tbz2", ".txz", ".tar.gz", ".tar.bz2", ".tar.xz")
_ZIP_EXT = (".zip", ".jar")
_SINGLE = {".gz": gzip.open, ".bz2": bz2.open, ".xz": lzma.open}
_EXT_EXT = (".rar", ".7z")  # need an external extractor


def is_archive(name: str) -> bool:
    n = name.lower()
    return (n.endswith(_ZIP_EXT) or n.endswith(_TAR_EXT)
            or n.endswith(_EXT_EXT) or n.endswith(tuple(_SINGLE)))


def _tool() -> list[str] | None:
    """First available external lister/extractor, as an argv prefix."""
    for exe in ("7z", "7za", "7zz", "bsdtar", "unrar"):
        p = shutil.which(exe)
        if p:
            return [p]
    return None


class ArchiveVFS(VFS):
    scheme = "arc"

    def __init__(self, arc_path: str):
        self.arc_path = paths.canon(arc_path)
        self._tree: dict[str, dict[str, DirEntry]] = {"/": {}}
        self._orig: dict[str, str] = {}  # normalized member -> archive name
        self._zip = self._tar = self._single = self._ext = None
        n = arc_path.lower()
        if n.endswith(_ZIP_EXT) or zipfile.is_zipfile(arc_path):
            self._zip = zipfile.ZipFile(arc_path)
            for zi in self._zip.infolist():
                mt = datetime(*zi.date_time).timestamp() if zi.date_time[0] else 0
                self._add(zi.filename, zi.is_dir(), zi.file_size, mt)
        elif n.endswith(_TAR_EXT) or tarfile.is_tarfile(arc_path):
            self._tar = tarfile.open(arc_path)
            for m in self._tar.getmembers():
                self._add(m.name, m.isdir(), m.size, m.mtime,
                          is_link=m.issym() or m.islnk())
        elif n.endswith(tuple(_SINGLE)):
            self._init_single(arc_path, n)
        elif n.endswith(_EXT_EXT):
            self._init_external(arc_path)
        else:
            raise OSError(f"not a supported archive: {arc_path}")

    # -- single-stream .gz/.bz2/.xz: one member named after the archive ----
    def _init_single(self, arc_path: str, n: str):
        ext = "." + n.rsplit(".", 1)[1]
        self._single = _SINGLE[ext]
        name = paths.basename(self.arc_path)[: -len(ext)] or "data"
        size = 0
        if ext == ".gz":  # gzip stores the uncompressed size (mod 2^32)
            try:
                with open(arc_path, "rb") as f:
                    f.seek(-4, os.SEEK_END)
                    size = struct.unpack("<I", f.read(4))[0]
            except OSError:
                pass
        try:
            mt = os.stat(arc_path).st_mtime
        except OSError:
            mt = 0.0
        self._add(name, False, size, mt)

    # -- rar/7z through an external tool ----------------------------------
    def _init_external(self, arc_path: str):
        tool = _tool()
        if not tool:
            raise OSError("rar/7z needs 7z, unrar or bsdtar on PATH")
        self._ext = (tool, paths.to_native(arc_path))
        exe = paths.basename(tool[0]).lower()
        if exe.startswith(("7z", "7za", "7zz")):
            self._list_7z()
        elif exe.startswith("unrar"):
            self._list_unrar()
        else:
            self._list_bsdtar()

    def _run(self, args: list[str]) -> str:
        try:
            r = subprocess.run(args, capture_output=True, text=True,
                               errors="replace", timeout=120)
        except (OSError, subprocess.SubprocessError) as e:
            raise OSError(f"archive tool failed: {e}") from e
        if r.returncode != 0 and not r.stdout:
            raise OSError((r.stderr or "archive tool failed").strip()[:200])
        return r.stdout

    def _list_7z(self):
        tool, arc = self._ext
        cur: dict = {}
        for line in self._run(tool + ["l", "-slt", "-ba", arc]).splitlines():
            if not line.strip():
                if cur.get("Path"):
                    self._add_ext(cur.get("Path"), cur.get("Attributes", ""),
                                  cur.get("Size", "0"), cur.get("Modified", ""))
                cur = {}
                continue
            k, _, v = line.partition(" = ")
            if _:
                cur[k.strip()] = v.strip()
        if cur.get("Path"):
            self._add_ext(cur.get("Path"), cur.get("Attributes", ""),
                          cur.get("Size", "0"), cur.get("Modified", ""))

    def _list_unrar(self):
        tool, arc = self._ext
        cur: dict = {}
        for line in self._run(tool + ["lt", "-idq", arc]).splitlines():
            k, _, v = line.partition(": ")
            if not _:
                continue
            k, v = k.strip(), v.strip()
            if k == "Name" and cur.get("Name"):
                self._add_ext(cur["Name"], cur.get("Attributes", ""),
                              cur.get("Size", "0"), cur.get("Modified", ""))
                cur = {}
            cur[k] = v
        if cur.get("Name"):
            self._add_ext(cur["Name"], cur.get("Attributes", ""),
                          cur.get("Size", "0"), cur.get("Modified", ""))

    def _list_bsdtar(self):
        tool, arc = self._ext
        for line in self._run(tool + ["-tvf", arc]).splitlines():
            f = line.split(None, 8)
            if len(f) < 9:
                continue
            self._add_ext(f[8], f[0], f[4], "")

    def _add_ext(self, name: str, attrs: str, size: str, modified: str):
        name = name.replace("\\", "/")
        is_dir = attrs.upper().startswith("D") or attrs.startswith("d")
        try:
            sz = int(str(size).strip() or 0)
        except ValueError:
            sz = 0
        mt = 0.0
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                mt = datetime.strptime(modified.strip()[:19], fmt).timestamp()
                break
            except ValueError:
                continue
        self._add(name, is_dir, sz, mt)

    def _add(self, member: str, is_dir: bool, size: int, mtime: float,
             is_link: bool = False):
        orig = member
        while member.startswith("./"):  # tar arcname='.' style entries
            member = member[2:]
        p = "/" + member.strip("/")
        if p == "/" or member in (".", ""):
            return
        self._orig[member.strip("/")] = orig
        parent = paths.parent(p)
        # materialize implicit parent directories
        walk = parent
        while walk != "/" and paths.basename(walk) not in self._tree.get(
                paths.parent(walk), {}):
            self._tree.setdefault(paths.parent(walk), {})[paths.basename(walk)] = \
                DirEntry(name=paths.basename(walk), is_dir=True)
            self._tree.setdefault(walk, {})
            walk = paths.parent(walk)
        self._tree.setdefault(parent, {})
        name = paths.basename(p)
        self._tree[parent][name] = DirEntry(
            name=name, size=0 if is_dir else size, mtime=mtime,
            is_dir=is_dir, is_link=is_link,
            ext="" if is_dir else paths.splitext(name)[1])
        if is_dir:
            self._tree.setdefault(p, {})

    def _member(self, path: str) -> str:
        m = paths.canon(path).lstrip("/")
        return self._orig.get(m, m)

    def listdir(self, path: str) -> list[DirEntry]:
        p = paths.canon(path) or "/"
        if p not in self._tree:
            raise OSError(f"no such directory in archive: {path}")
        return list(self._tree[p].values())

    def stat(self, path: str) -> DirEntry:
        p = paths.canon(path)
        if p == "/":
            return DirEntry(name="/", is_dir=True)
        e = self._tree.get(paths.parent(p), {}).get(paths.basename(p))
        if e is None:
            raise OSError(f"not in archive: {path}")
        return e

    def open(self, path: str, mode: str = "rb"):
        if "w" in mode or "a" in mode or "+" in mode:
            raise OSError("archive is read-only")
        m = self._member(path)
        if self._zip:
            return self._zip.open(m)
        if self._single:
            return self._single(paths.to_native(self.arc_path), "rb")
        if self._ext:
            return self._open_external(m)
        f = self._tar.extractfile(m)
        if f is None:
            raise OSError(f"cannot read member: {path}")
        return f

    def _open_external(self, member: str):
        """Stream one member out of the tool's stdout."""
        tool, arc = self._ext
        exe = paths.basename(tool[0]).lower()
        native = member.replace("/", "\\") if exe.startswith("unrar") else member
        if exe.startswith(("7z", "7za", "7zz")):
            args = tool + ["x", "-so", "-y", arc, member]
        elif exe.startswith("unrar"):
            args = tool + ["p", "-inul", "-y", arc, native]
        else:
            args = tool + ["-xOf", arc, member]
        try:
            p = subprocess.Popen(args, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL)
        except OSError as e:
            raise OSError(f"cannot read member: {e}") from e
        return p.stdout

    def readlink(self, path: str) -> str:
        if self._tar:
            return self._tar.getmember(self._member(path)).linkname
        raise OSError("not a symlink")

    def mkdir(self, path: str):
        raise OSError("archive is read-only")

    remove = rmdir = mkdir

    def rename(self, old: str, new: str):
        raise OSError("archive is read-only")

    def display(self, path: str) -> str:
        return f"{self.arc_path}:{paths.canon(path)}"

    def close(self):
        if self._zip or self._tar:
            (self._zip or self._tar).close()
