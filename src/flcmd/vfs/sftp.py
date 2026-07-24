"""SFTP-backed VFS (built-in SSH). Remote paths are already canonical
'/'-separated, so no translation is needed."""

import stat as st

from .. import paths
from .base import VFS, DirEntry


def _entry(name: str, a) -> DirEntry:
    mode = a.st_mode or 0
    is_dir = st.S_ISDIR(mode)
    return DirEntry(
        name=name,
        size=0 if is_dir else (a.st_size or 0),
        mtime=a.st_mtime or 0.0,
        is_dir=is_dir,
        is_link=st.S_ISLNK(mode),
        mode=mode,
        ext="" if is_dir else paths.splitext(name)[1],
    )


class SftpVFS(VFS):
    scheme = "sftp"

    def __init__(self, session):
        self.session = session
        self.sftp = session.sftp

    def listdir(self, path: str) -> list[DirEntry]:
        out = []
        for a in self.sftp.listdir_attr(path):
            e = _entry(a.filename, a)
            if e.is_link:  # dir symlinks must list as dirs (navigable)
                try:
                    t = self.sftp.stat(paths.join(path, a.filename))
                    e.is_dir = st.S_ISDIR(t.st_mode or 0)
                    if e.is_dir:
                        e.size, e.ext = 0, ""
                except OSError:
                    pass  # broken link: keep lstat info
            out.append(e)
        return out

    def stat(self, path: str) -> DirEntry:
        return _entry(paths.basename(path), self.sftp.lstat(path))

    def stat_follow(self, path: str) -> DirEntry:
        return _entry(paths.basename(path), self.sftp.stat(path))

    def open(self, path: str, mode: str = "rb"):
        f = self.sftp.open(path, mode.replace("b", ""), bufsize=1 << 20)
        if "r" in mode:
            try:
                f.prefetch()  # pipelined reads: big speedup on copies
            except Exception:
                pass
        return f

    def mkdir(self, path: str) -> None:
        self.sftp.mkdir(path)

    def remove(self, path: str) -> None:
        self.sftp.remove(path)

    def rmdir(self, path: str) -> None:
        self.sftp.rmdir(path)

    def rename(self, old: str, new: str) -> None:
        try:
            self.sftp.posix_rename(old, new)  # overwrites, like os.replace
        except OSError:
            self.sftp.rename(old, new)

    def readlink(self, path: str) -> str:
        return self.sftp.readlink(path)

    def symlink(self, target: str, path: str) -> None:
        self.sftp.symlink(target, path)

    def display(self, path: str) -> str:
        return f"sftp://{self.session.label}{path}"

    def close(self):
        self.session.close()
