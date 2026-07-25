"""OLE drag-out via the shell's own machinery (ctypes, no pywin32):
SHParseDisplayName -> shell item array -> BindToHandler(BHID_DataObject)
-> SHDoDragDrop. The shell builds the data object (CF_HDROP plus shell
IDList/async formats, so Explorer, archives, Outlook etc. all accept it)
and supplies the drop source and drag visuals; we implement no COM
interfaces ourselves.

SHDoDragDrop runs the usual modal drag loop pumping this thread's
messages, so it nests inside the widget's handle() like the X11 shim's
nested event loop. FLTK already ran OleInitialize on the UI thread.
"""

import ctypes as C
import os
import sys
from ctypes import wintypes as W

from .. import paths

_DEBUG = bool(os.environ.get("FLCMD_DND_DEBUG"))


def _dbg(*args):
    if _DEBUG:
        print("[dnd]", *args, file=sys.stderr, flush=True)

ole32 = C.windll.ole32
shell32 = C.windll.shell32

S_OK, S_FALSE = 0, 1
DRAGDROP_S_DROP = 0x00040100
DRAGDROP_S_CANCEL = 0x00040101
CF_HDROP = 15
DVASPECT_CONTENT = 1
TYMED_HGLOBAL = 1
DROPEFFECT_COPY, DROPEFFECT_MOVE, DROPEFFECT_LINK = 1, 2, 4


class GUID(C.Structure):
    _fields_ = [("b", C.c_ubyte * 16)]


def _iid(s: str) -> GUID:
    p = s.split("-")
    raw = (int(p[0], 16).to_bytes(4, "little")
           + int(p[1], 16).to_bytes(2, "little")
           + int(p[2], 16).to_bytes(2, "little")
           + bytes.fromhex(p[3]) + bytes.fromhex(p[4]))
    g = GUID()
    C.memmove(C.byref(g), raw, 16)
    return g

IID_IDataObject = _iid("0000010e-0000-0000-c000-000000000046")
BHID_DataObject = _iid("b8c0bd9f-ed24-455c-83e6-d5390c4fe8c4")


class FORMATETC(C.Structure):
    _fields_ = [("cfFormat", C.c_ushort), ("ptd", C.c_void_p),
                ("dwAspect", W.DWORD), ("lindex", C.c_long),
                ("tymed", W.DWORD)]


class STGMEDIUM(C.Structure):  # union collapsed: all arms are handles
    _fields_ = [("tymed", W.DWORD), ("hGlobal", C.c_void_p),
                ("pUnkForRelease", C.c_void_p)]

ole32.OleInitialize.restype = C.c_long
ole32.OleInitialize.argtypes = (C.c_void_p,)
ole32.OleUninitialize.restype = None
ole32.ReleaseStgMedium.restype = None
ole32.ReleaseStgMedium.argtypes = (C.POINTER(STGMEDIUM),)
shell32.SHParseDisplayName.restype = C.c_long
shell32.SHParseDisplayName.argtypes = (C.c_wchar_p, C.c_void_p,
                                       C.POINTER(C.c_void_p), C.c_ulong,
                                       C.POINTER(C.c_ulong))
shell32.SHCreateShellItemArrayFromIDLists.restype = C.c_long
shell32.SHCreateShellItemArrayFromIDLists.argtypes = (
    C.c_uint, C.POINTER(C.c_void_p), C.POINTER(C.c_void_p))
# SHDoDragDrop MUST keep the GIL (PyDLL): its modal loop dispatches
# messages to FLTK windows, and pyfltk's Python-side handle()/draw()
# overrides assume the GIL is held (as under Fl.run) -- with a plain
# windll call the GIL is released and any such callback crashes in
# python3xx.dll.
_shell32_gil = C.PyDLL("shell32")
_shell32_gil.SHDoDragDrop.restype = C.c_long
_shell32_gil.SHDoDragDrop.argtypes = (W.HWND, C.c_void_p, C.c_void_p,
                                      W.DWORD, C.POINTER(W.DWORD))
shell32.ILFree.restype = None
shell32.ILFree.argtypes = (C.c_void_p,)

# calling (not implementing) COM: fetch a method out of the vtable
_RELEASE = C.WINFUNCTYPE(C.c_ulong, C.c_void_p)
_GETDATA = C.WINFUNCTYPE(C.c_long, C.c_void_p, C.POINTER(FORMATETC),
                         C.POINTER(STGMEDIUM))
_BINDTOHANDLER = C.WINFUNCTYPE(C.c_long, C.c_void_p, C.c_void_p,
                               C.POINTER(GUID), C.POINTER(GUID),
                               C.POINTER(C.c_void_p))  # IShellItemArray[3]


def _method(punk, slot, proto):
    vtbl = C.cast(C.c_void_p(punk), C.POINTER(C.POINTER(C.c_void_p))).contents
    return proto(vtbl[slot])


def _release(punk):
    return _method(punk, 2, _RELEASE)(punk)


def _file_data_object(file_paths) -> int:
    """Shell-standard IDataObject for existing local files (caller must
    _release() it)."""
    pidls = []
    try:
        for p in file_paths:
            pidl = C.c_void_p()
            hr = shell32.SHParseDisplayName(paths.to_native(p), None,
                                            C.byref(pidl), 0, None)
            if hr != S_OK or not pidl.value:
                raise RuntimeError(f"drag: cannot resolve {p} "
                                   f"(hr=0x{hr & 0xFFFFFFFF:08x})")
            pidls.append(pidl)
        arr = (C.c_void_p * len(pidls))(*[p.value for p in pidls])
        psia = C.c_void_p()
        hr = shell32.SHCreateShellItemArrayFromIDLists(len(pidls), arr,
                                                       C.byref(psia))
        if hr != S_OK or not psia.value:
            raise RuntimeError(f"SHCreateShellItemArrayFromIDLists failed "
                               f"(hr=0x{hr & 0xFFFFFFFF:08x})")
        try:
            # Explorer's own data object: CF_HDROP + shell formats
            pdo = C.c_void_p()
            hr = _method(psia.value, 3, _BINDTOHANDLER)(
                psia.value, None, C.byref(BHID_DataObject),
                C.byref(IID_IDataObject), C.byref(pdo))
            if hr != S_OK or not pdo.value:
                raise RuntimeError(f"BindToHandler(BHID_DataObject) failed "
                                   f"(hr=0x{hr & 0xFFFFFFFF:08x})")
            return pdo.value
        finally:
            _release(psia.value)
    finally:
        for p in pidls:
            shell32.ILFree(p)


def drag_files(file_paths) -> bool:
    """Modal OLE drag of local files; True if a target accepted the drop.
    Our own windows stay valid drop targets (pane-to-pane drag works:
    FLTK delivers the drop as FL_PASTE just like an external one)."""
    _dbg("drag_files:", file_paths)
    hr = ole32.OleInitialize(None)
    if hr not in (S_OK, S_FALSE):
        raise RuntimeError(f"OleInitialize failed (hr=0x{hr & 0xFFFFFFFF:08x})")
    try:
        pdo = _file_data_object(file_paths)
        try:
            effect = W.DWORD(0)
            # NULL drop source: the shell provides one (plus drag visuals)
            hr = _shell32_gil.SHDoDragDrop(
                None, pdo, None,
                DROPEFFECT_COPY | DROPEFFECT_MOVE | DROPEFFECT_LINK,
                C.byref(effect))
            _dbg(f"SHDoDragDrop hr=0x{hr & 0xFFFFFFFF:08x} "
                 f"effect={effect.value}")
            if hr not in (DRAGDROP_S_DROP, DRAGDROP_S_CANCEL):
                raise RuntimeError(
                    f"SHDoDragDrop failed (hr=0x{hr & 0xFFFFFFFF:08x})")
            return hr == DRAGDROP_S_DROP and effect.value != 0
        finally:
            _release(pdo)
    finally:
        ole32.OleUninitialize()  # balance our (nested) OleInitialize
