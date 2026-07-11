"""Canonical paths: '/'-separated on ALL platforms, no trailing slash except
roots. Windows: 'C:/Users/x', UNC: '//server/share/dir'. This module is the
only place converting to/from native form (see CLAUDE.md)."""

import re
import sys

IS_WIN = sys.platform == "win32"

_DRIVE = re.compile(r"^[A-Za-z]:")


def canon(p: str) -> str:
    """Any native/mixed path -> canonical form."""
    p = p.replace("\\", "/")
    unc = p.startswith("//")
    p = re.sub(r"/{2,}", "/", p)
    if unc:
        p = "/" + p
    if _DRIVE.match(p):
        p = p[0].upper() + p[1:]
        if len(p) == 2:
            return p + "/"
    # strip trailing '/' except filesystem root and drive roots ('X:/')
    while len(p) > 1 and p.endswith("/") and not (len(p) == 3 and _DRIVE.match(p)):
        p = p[:-1]
    return p


def is_root(p: str) -> bool:
    if p == "/":
        return True
    if _DRIVE.match(p) and p[2:] in ("", "/"):
        return True
    if p.startswith("//"):  # UNC: //server or //server/share is a root
        return len([s for s in p[2:].split("/") if s]) <= 2
    return False


def parent(p: str) -> str:
    p = canon(p)
    if is_root(p):
        return p
    q = p[: p.rfind("/")]
    if q == "":
        return "/"
    if _DRIVE.match(q) and len(q) == 2:
        return q + "/"
    return q


def join(base: str, *parts: str) -> str:
    p = canon(base)
    for part in parts:
        part = canon(part).strip("/")
        if part:
            p = (p if p.endswith("/") else p + "/") + part
    return p


def basename(p: str) -> str:
    p = canon(p)
    if is_root(p):
        return p
    return p[p.rfind("/") + 1 :]


def splitext(name: str) -> tuple[str, str]:
    """('archive.tar', 'gz') style split; dotfiles have no extension."""
    i = name.rfind(".")
    if i <= 0:
        return name, ""
    return name[:i], name[i + 1 :]


def to_native(p: str) -> str:
    """Canonical -> native OS form. Only for OS/plugin API boundaries."""
    p = canon(p)
    return p.replace("/", "\\") if IS_WIN else p


def from_native(p: str) -> str:
    return canon(p)


def from_uri(uri: str) -> str:
    """file:// URI -> canonical path ('file:///C:/x' and UNC forms too)."""
    from urllib.parse import unquote, urlparse
    u = urlparse(uri)
    p = unquote(u.path)
    if re.match(r"^/[A-Za-z]:", p):
        p = p[1:]
    if u.netloc and u.netloc.lower() != "localhost":
        p = "//" + u.netloc + p
    return canon(p)
