"""paramiko session wrapper: agent + pubkey auth (ssh_config aliases and
identity files respected), optional password. Toolkit-free."""

import paramiko

from .config import lookup, parse_target


class SSHSession:
    def __init__(self, target: str, password: str | None = None,
                 timeout: float = 12.0):
        user, host, port = parse_target(target)
        info = lookup(host)
        self.label = target
        self.client = paramiko.SSHClient()
        self.client.load_system_host_keys()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        keys = info.get("identityfile")
        self.client.connect(
            hostname=info.get("hostname", host),
            port=port or int(info.get("port", 22)),
            username=user or info.get("user"),
            key_filename=keys,
            password=password or None,
            allow_agent=True,
            look_for_keys=True,
            timeout=timeout,
        )
        self.sftp = self.client.open_sftp()
        self.home = self.sftp.normalize(".")

    def close(self):
        try:
            self.sftp.close()
            self.client.close()
        except Exception:
            pass
