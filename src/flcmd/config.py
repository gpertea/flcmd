"""Settings: flcmd.ini in the platform config dir (configparser format,
like TC's wincmd.ini). Sections of scalar values; load() parses ints,
floats and booleans back from their string form."""

import configparser
import os
import sys

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
    return paths.join(config_dir(), "flcmd.ini")


def _parse(s: str):
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    for conv in (int, float):
        try:
            return conv(s)
        except ValueError:
            continue
    return s


def load() -> dict:
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    try:
        cp.read(config_file(), encoding="utf-8")
    except (OSError, configparser.Error):
        return {}
    return {sec: {k: _parse(v) for k, v in cp[sec].items()}
            for sec in cp.sections()}


def save(cfg: dict) -> None:
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    for section, values in cfg.items():
        cp[section] = {k: str(v) for k, v in values.items()}
    os.makedirs(config_dir(), exist_ok=True)
    with open(config_file(), "w", encoding="utf-8", newline="\n") as f:
        cp.write(f)


def update(section: str, values: dict) -> None:
    """Read-modify-write one section (used for immediate persistence)."""
    cfg = load()
    cfg.setdefault(section, {}).update(values)
    save(cfg)
