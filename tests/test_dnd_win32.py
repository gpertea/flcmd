"""Headless tests for the win32 drag-out shim: the shell-built
IDataObject must serve the dragged files as CF_HDROP exactly as a drop
target will read them (no actual drag -- SHDoDragDrop needs a mouse)."""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="win32 drag-out shim")

if sys.platform == "win32":
    import ctypes as C

    from flcmd.dnd import win32 as w


def _drag_query(hdrop, index, buf=None, count=0):
    f = C.windll.shell32.DragQueryFileW
    f.restype = C.c_uint
    f.argtypes = (C.c_void_p, C.c_uint, C.c_wchar_p, C.c_uint)
    return f(hdrop, index, buf, count)


def test_data_object_serves_hdrop(tmp_path):
    names = ("first file.txt", "second.bin")
    for n in names:
        (tmp_path / n).write_text("x")
    canon = [str(tmp_path / n).replace("\\", "/") for n in names]
    w.ole32.OleInitialize(None)
    try:
        pdo = w._file_data_object(canon)
        try:
            fmt = w.FORMATETC(w.CF_HDROP, None, w.DVASPECT_CONTENT, -1,
                              w.TYMED_HGLOBAL)
            med = w.STGMEDIUM()
            hr = w._method(pdo, 3, w._GETDATA)(pdo, C.byref(fmt),
                                               C.byref(med))
            assert hr == w.S_OK
            assert med.tymed == w.TYMED_HGLOBAL and med.hGlobal
            assert _drag_query(med.hGlobal, 0xFFFFFFFF) == len(names)
            got = []
            for i in range(len(names)):
                n = _drag_query(med.hGlobal, i)
                buf = C.create_unicode_buffer(n + 1)
                _drag_query(med.hGlobal, i, buf, n + 1)
                got.append(buf.value.replace("\\", "/"))
            assert sorted(got) == sorted(canon)
            w.ole32.ReleaseStgMedium(C.byref(med))
        finally:
            w._release(pdo)
    finally:
        w.ole32.OleUninitialize()


def test_missing_file_raises(tmp_path):
    w.ole32.OleInitialize(None)
    try:
        with pytest.raises(RuntimeError, match="cannot resolve"):
            w._file_data_object([str(tmp_path / "gone.txt")
                                 .replace("\\", "/")])
    finally:
        w.ole32.OleUninitialize()
