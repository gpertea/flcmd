"""Drag files OUT to other applications (drop-in is handled by FLTK events
in the panes). Per-platform shims; only local files can be dragged."""

import sys


def start_file_drag(fltk_win, file_paths: list[str], own_xids=()) -> bool:
    """Run a modal drag of file_paths (canonical local paths). Blocks until
    the drag ends; returns True if a target accepted the drop."""
    if not file_paths:
        return False
    if sys.platform.startswith("linux"):
        import fltk

        from . import x11
        return x11.drag_files(fltk.fl_xid(fltk_win), file_paths, own_xids)
    if sys.platform == "win32":
        from . import win32
        return win32.drag_files(file_paths)
    # darwin: NSDraggingSession via pyobjc, later
    raise NotImplementedError(f"file drag-out not implemented on {sys.platform}")
