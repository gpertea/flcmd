# Installing flcmd on Windows (dev build)

TL;DR -- after cloning, run in the repo root:

    uv sync

then `uv run flcmd`. That is the whole install: PyPI ships binary pyfltk
wheels for Windows, so no compiler, no MSYS2, and no preinstalled Python
are needed (uv provisions a suitable CPython itself -- 3.12 as of pyfltk
1.4.5.0, whose wheels are the constraint). Every step below was verified
on Windows 10 x64, 2026-07.

## Prerequisites

- `uv` (https://astral.sh/uv). The standalone installer puts it in
  `%USERPROFILE%\.local\bin` -- make sure that is on PATH (the installer
  normally does this for `cmd`/PowerShell; MSYS2 bash users may need to
  add it to `.bashrc` or call it by full path).

Nothing else. No Visual Studio, no MinGW, no fltk-config.

## Build and run

    git clone <repo> flcmd
    cd flcmd
    uv sync            # creates .venv, installs pyfltk wheel + deps
    uv run flcmd       # main app
    uv run flcmd-view  # standalone viewer

`uv sync` also generates the entry-point executables
`.venv\Scripts\flcmd.exe` and `.venv\Scripts\flcmd-view.exe`. These are
*console* launchers: started from Explorer they open a console window
next to the GUI. For a console-free launch use pythonw from the same
venv:

    .venv\Scripts\pythonw.exe -m flcmd
    .venv\Scripts\pythonw.exe -m flcmd.viewer <file>

The project is installed editable, so source edits are live -- no
re-sync needed except after changing dependencies or entry points.

## Desktop shortcuts

Tested PowerShell recipe (adjust the repo path):

    $ws = New-Object -ComObject WScript.Shell
    $desktop = $ws.SpecialFolders('Desktop')
    $py = 'D:\_work_\flcmd\.venv\Scripts\pythonw.exe'
    $s = $ws.CreateShortcut("$desktop\flcmd (dev).lnk")
    $s.TargetPath = $py; $s.Arguments = '-m flcmd'
    $s.WorkingDirectory = $env:USERPROFILE; $s.Save()
    $v = $ws.CreateShortcut("$desktop\flcmd viewer (dev).lnk")
    $v.TargetPath = $py; $v.Arguments = '-m flcmd.viewer'
    $v.WorkingDirectory = $env:USERPROFILE; $v.Save()

Dropping a file onto the viewer shortcut opens it in the viewer.

## Tests

    uv run pytest -m "not gui"

Expected on Windows: the two chmod-based error tests skip (chmod 0 is
not enforced on Windows) and the GUI tests are deselected (they need an
X display / Xvfb; run them on Linux). Notes:

- Symlink tests need symlink creation rights: enable Windows Developer
  Mode (Settings > Update & Security > For developers) or run elevated;
  otherwise they skip.
- ssh-marked tests connect to a real host (`FLCMD_TEST_SSH_HOST`,
  default `gvlin`, resolved via your ssh config). Without a reachable
  host deselect them: `uv run pytest -m "not gui and not ssh"`.
- Config/bookmark tests write only under pytest tmp dirs (the
  `isolated_config` fixture overrides `APPDATA`), never to your real
  `%APPDATA%\flcmd`.

## Where the app puts its files

Settings live in `%APPDATA%\flcmd\` (`flcmd.ini`, `bookmarks.json`),
created on first run.

## Distribution (planned, not yet built)

The goal is a plain unpack-anywhere zip -- no installer. That will be a
PyInstaller (or equivalent) bundle produced later in the roadmap; for
now the dev build above is the only supported way to run on Windows.
