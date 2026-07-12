"""ssh_config handling: aliases resolve exactly like the OpenSSH client.
A custom config path (Windows, unusual setups) comes from flcmd.ini
[ssh] config_file."""

import os

import paramiko

from .. import config as appconfig


def ssh_config_path() -> str:
    p = appconfig.load().get("ssh", {}).get("config_file", "")
    return os.path.expanduser(p) if p else os.path.expanduser("~/.ssh/config")


def lookup(host: str) -> dict:
    """Resolved ssh_config entry (hostname, user, port, identityfile...)."""
    sc = paramiko.SSHConfig()
    try:
        with open(ssh_config_path()) as f:
            sc.parse(f)
    except OSError:
        pass
    return sc.lookup(host)


def parse_target(target: str) -> tuple[str | None, str, int | None]:
    """'[user@]host[:port]' -> (user, host, port); missing parts None."""
    user = port = None
    if "@" in target:
        user, target = target.split("@", 1)
    if ":" in target:
        target, p = target.rsplit(":", 1)
        if p.isdigit():
            port = int(p)
    return user, target, port
