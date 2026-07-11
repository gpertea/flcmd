"""VFS abstraction: panes and file ops only ever talk to a VFS.
All paths are canonical (see flcmd.paths)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(slots=True)
class DirEntry:
    name: str
    size: int = 0
    mtime: float = 0.0
    is_dir: bool = False
    is_link: bool = False
    mode: int = 0
    ext: str = field(default="", compare=False)


class VFS(ABC):
    scheme = "file"

    @abstractmethod
    def listdir(self, path: str) -> list[DirEntry]: ...

    @abstractmethod
    def stat(self, path: str) -> DirEntry: ...

    @abstractmethod
    def open(self, path: str, mode: str = "rb"): ...

    @abstractmethod
    def mkdir(self, path: str) -> None: ...

    @abstractmethod
    def remove(self, path: str) -> None: ...

    @abstractmethod
    def rmdir(self, path: str) -> None: ...

    @abstractmethod
    def rename(self, old: str, new: str) -> None: ...

    def is_dir(self, path: str) -> bool:
        try:
            return self.stat(path).is_dir
        except OSError:
            return False

    def exists(self, path: str) -> bool:
        try:
            self.stat(path)
            return True
        except OSError:
            return False

    def display(self, path: str) -> str:
        """Path as shown in the pane header."""
        return path
