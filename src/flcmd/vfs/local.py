"""Local filesystem VFS. Canonical '/' paths are passed straight to os.*
(valid on Windows too); to_native is not needed here."""

import os
import stat as st

from .. import paths
from .base import VFS, DirEntry


def _entry(name: str, s: os.stat_result, is_link: bool) -> DirEntry:
    is_dir = st.S_ISDIR(s.st_mode)
    return DirEntry(
        name=name,
        size=0 if is_dir else s.st_size,
        mtime=s.st_mtime,
        is_dir=is_dir,
        is_link=is_link,
        mode=s.st_mode,
        ext="" if is_dir else paths.splitext(name)[1],
    )


class LocalVFS(VFS):
    def listdir(self, path: str) -> list[DirEntry]:
        out = []
        with os.scandir(path) as it:
            for de in it:
                try:
                    out.append(_entry(de.name, de.stat(follow_symlinks=False), de.is_symlink()))
                except OSError:
                    out.append(DirEntry(name=de.name))
        return out

    def stat(self, path: str) -> DirEntry:
        s = os.lstat(path)
        return _entry(paths.basename(path), s, st.S_ISLNK(s.st_mode))

    def open(self, path: str, mode: str = "rb"):
        return open(path, mode)

    def mkdir(self, path: str) -> None:
        os.mkdir(path)

    def remove(self, path: str) -> None:
        os.remove(path)

    def rmdir(self, path: str) -> None:
        os.rmdir(path)

    def rename(self, old: str, new: str) -> None:
        os.replace(old, new)
