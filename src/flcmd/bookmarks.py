"""Folder shortcuts (bookmarks menu) and the locations toolbar, persisted
as JSON in the config dir. A bookmark location is a canonical local path or
an 'sftp://alias/path' URL so remote shortcuts work too.

Bookmark tree node: {"title": str, "path": str}   -> leaf (chdir target)
                    {"title": str, "items": [...]} -> submenu
Toolbar button:     {"caption": str, "path": str}
"""

import json
import os

from . import config, paths


def _store_path() -> str:
    return paths.join(config.config_dir(), "bookmarks.json")


def load() -> dict:
    try:
        with open(_store_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.setdefault("bookmarks", [])   # tree of nodes
    data.setdefault("toolbar", [])     # flat list of buttons
    return data


def save(data: dict) -> None:
    os.makedirs(config.config_dir(), exist_ok=True)
    with open(_store_path(), "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1, ensure_ascii=True)


# -- location <-> display helpers -------------------------------------------
def make_location(vfs, path: str) -> str:
    """Encode a pane's (vfs, path) as a portable bookmark location."""
    if getattr(vfs, "scheme", "file") == "sftp":
        return f"sftp://{vfs.session.label}{path}"
    return paths.canon(path)


def short_title(location: str) -> str:
    """Default label for a location: last path component (or host root)."""
    if location.startswith("sftp://"):
        rest = location[len("sftp://"):]
        host, _, p = rest.partition("/")
        base = paths.basename("/" + p) if p else host
        return f"{base} [{host}]" if p else host
    return paths.basename(location) or location


def add_bookmark(data: dict, title: str, location: str) -> None:
    data["bookmarks"].append({"title": title, "path": location})


def add_toolbar(data: dict, caption: str, location: str) -> None:
    data["toolbar"].append({"caption": caption, "path": location})
