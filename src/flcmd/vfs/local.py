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
                    is_link = de.is_symlink()
                    s = de.stat(follow_symlinks=False)
                    if is_link:
                        try:  # dir symlinks must list as dirs (navigable)
                            s = de.stat(follow_symlinks=True)
                        except OSError:
                            pass  # broken link: keep lstat info
                    out.append(_entry(de.name, s, is_link))
                except OSError:
                    out.append(DirEntry(name=de.name))
        return out

    def stat(self, path: str) -> DirEntry:
        s = os.lstat(path)
        return _entry(paths.basename(path), s, st.S_ISLNK(s.st_mode))

    def stat_follow(self, path: str) -> DirEntry:
        return _entry(paths.basename(path), os.stat(path), False)

    def readlink(self, path: str) -> str:
        t = os.readlink(path)  # raw target, relative links preserved
        if paths.IS_WIN:
            if t.startswith("\\\\?\\"):
                t = t[4:]
            t = t.replace("\\", "/")
        return t

    def symlink(self, target: str, path: str, is_dir: bool = False) -> None:
        # Windows stores the target verbatim and cannot resolve '/' in it;
        # dir links must also be created as directory symlinks.
        if paths.IS_WIN:
            os.symlink(target.replace("/", "\\"), path,
                       target_is_directory=is_dir)
        else:
            os.symlink(target, path)

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

    def copystat(self, src: str, dst: str) -> None:
        import shutil
        try:
            shutil.copystat(src, dst)
        except OSError:
            pass  # permissions/times are best-effort
