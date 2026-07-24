"""Procedural 16x16 mini-icons for the file list: folder, document, and
tinted document variants (executable green, archive orange), each with a
symlink variant carrying a small corner 'shortcut' arrow overlay.
Drawn from ASCII pixel art -> Fl_RGB_Image (RGBA), built once and cached."""

import fltk

from ..vfs import DirEntry
from ..vfs.archive import is_archive

ICON_W = 16          # drawn size; name text starts after ICON_W + pad

_FOLDER = (
    "................",
    "................",
    ".BBBBBB.........",
    "BthhhhtB........",
    "BhyyyyhBBBBBBBB.",
    "BhyyyyyhhhhhhhB.",
    "ByyyyyyyyyyyyyB.",
    "ByyyyyyyyyyyyyB.",
    "BssssssssssssyB.",
    "BssssssssssssyB.",
    "BssssssssssssyB.",
    "BssssssssssssyB.",
    ".BBBBBBBBBBBBB..",
    "................",
    "................",
    "................",
)

_DOC = (
    "................",
    "...BBBBBBF......",
    "...BwwwwwBFF....",
    "...BwwwwwBfFF...",
    "...BwwwwwBBBB...",
    "...BwwwwwwwwB...",
    "...BwllllllwB...",
    "...BwwwwwwwwB...",
    "...BwlllllwwB...",
    "...BwwwwwwwwB...",
    "...BwllllllwB...",
    "...BwwwwwwwwB...",
    "...BwlllwwwwB...",
    "...BwwwwwwwwB...",
    "...BBBBBBBBBB...",
    "................",
)

# bottom-left corner shortcut overlay (Windows-style, 7x7): white box,
# grey border, dark NE arrow (head top-right, tail to bottom-left)
_LINK = (
    "GGGGGGG",
    "GwwaaaG",
    "GwwwaaG",
    "GwwawaG",
    "GwawwwG",
    "GawwwwG",
    "GGGGGGG",
)

_FOLDER_COLORS = {
    "B": (168, 121, 42),     # border
    "t": (255, 236, 173),    # tab highlight
    "h": (255, 226, 138),    # upper body highlight
    "y": (252, 208, 100),    # body
    "s": (246, 194, 74),     # lower body shade
}


def _doc_colors(tint):
    """Document palette; tint is None, 'exe' (green) or 'arc' (orange)."""
    if tint == "exe":
        border, fill, lines = (96, 138, 96), (228, 243, 226), (140, 185, 140)
    elif tint == "arc":
        border, fill, lines = (162, 116, 62), (251, 235, 212), (210, 168, 116)
    else:
        border, fill, lines = (122, 128, 136), (255, 255, 255), (176, 182, 190)
    return {
        "B": border,
        "w": fill,
        "l": lines,
        "F": tuple(min(255, c + 18) for c in lines),  # fold flap
        "f": border,                                  # fold crease
    }


_LINK_COLORS = {
    "G": (118, 124, 130),    # box border
    "a": (30, 30, 30),       # arrow
    "w": (255, 255, 255),
}


def _render(art, colors, overlay=None) -> bytes:
    px = bytearray(ICON_W * ICON_W * 4)

    def put(cx, cy, rgb):
        i = (cy * ICON_W + cx) * 4
        px[i:i + 4] = bytes((*rgb, 255))

    for cy, row in enumerate(art):
        assert len(row) == ICON_W, f"row {cy} width"
        for cx, ch in enumerate(row):
            if ch != ".":
                put(cx, cy, colors[ch])
    if overlay:
        oy = ICON_W - len(overlay)
        for cy, row in enumerate(overlay):
            for cx, ch in enumerate(row):
                if ch != ".":
                    put(cx, oy + cy, _LINK_COLORS[ch])
    return bytes(px)


_data: list[bytes] = []      # keep pixel buffers alive for Fl_RGB_Image
_cache: dict = {}


def icon(kind: str, link: bool):
    """kind: 'dir' | 'file' | 'exe' | 'arc'."""
    key = (kind, link)
    if key not in _cache:
        if kind == "dir":
            art, colors = _FOLDER, _FOLDER_COLORS
        else:
            art = _DOC
            colors = _doc_colors(kind if kind in ("exe", "arc") else None)
        data = _render(art, colors, _LINK if link else None)
        _data.append(data)
        _cache[key] = fltk.Fl_RGB_Image(data, ICON_W, ICON_W, 4)
    return _cache[key]


def entry_kind(e: DirEntry) -> str:
    if e.is_dir:
        return "dir"
    if is_archive(e.name):
        return "arc"
    if e.mode & 0o111 or e.ext.lower() in ("exe", "bat", "cmd", "com"):
        return "exe"
    return "file"


def entry_icon(e: DirEntry):
    return icon(entry_kind(e), e.is_link)
