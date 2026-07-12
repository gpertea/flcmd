"""Read-only archive VFS: browse zip/tar archives as directories.
Copy-out works through the normal ops engine (open() streams members);
mutation raises OSError so ops surface a clean error. Pack support later."""

import tarfile
import zipfile
from datetime import datetime

from .. import paths
from .base import VFS, DirEntry

_TAR_EXT = (".tar", ".tgz", ".tbz2", ".txz", ".tar.gz", ".tar.bz2", ".tar.xz")
_ZIP_EXT = (".zip", ".jar")


def is_archive(name: str) -> bool:
    n = name.lower()
    return n.endswith(_ZIP_EXT) or n.endswith(_TAR_EXT)


class ArchiveVFS(VFS):
    scheme = "arc"

    def __init__(self, arc_path: str):
        self.arc_path = paths.canon(arc_path)
        self._tree: dict[str, dict[str, DirEntry]] = {"/": {}}
        self._orig: dict[str, str] = {}  # normalized member -> archive name
        n = arc_path.lower()
        if n.endswith(_ZIP_EXT) or zipfile.is_zipfile(arc_path):
            self._zip = zipfile.ZipFile(arc_path)
            self._tar = None
            for zi in self._zip.infolist():
                mt = datetime(*zi.date_time).timestamp() if zi.date_time[0] else 0
                self._add(zi.filename, zi.is_dir(), zi.file_size, mt)
        elif tarfile.is_tarfile(arc_path):
            self._zip = None
            self._tar = tarfile.open(arc_path)
            for m in self._tar.getmembers():
                self._add(m.name, m.isdir(), m.size, m.mtime,
                          is_link=m.issym() or m.islnk())
        else:
            raise OSError(f"not a supported archive: {arc_path}")

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
        f = self._tar.extractfile(m)
        if f is None:
            raise OSError(f"cannot read member: {path}")
        return f

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
        (self._zip or self._tar).close()
