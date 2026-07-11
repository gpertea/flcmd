"""Settings: TOML file in the platform config dir. Values are flat sections
of scalars / string lists -- enough for settings and keybindings."""

import os
import sys
import tomllib

from . import paths

APP = "flcmd"


def config_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return paths.join(paths.canon(base), APP)


def config_file() -> str:
    return paths.join(config_dir(), "flcmd.toml")


def load() -> dict:
    try:
        with open(config_file(), "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def save(cfg: dict) -> None:
    os.makedirs(config_dir(), exist_ok=True)
    lines = []
    for section, values in cfg.items():
        lines.append(f"[{section}]")
        for k, v in values.items():
            lines.append(f"{k} = {_fmt(v)}")
        lines.append("")
    with open(config_file(), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
