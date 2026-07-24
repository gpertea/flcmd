# Installing flcmd on Linux

TL;DR -- after cloning, run:

    scripts/setup.sh

then `uv run flcmd`. That is the whole install. The script is idempotent;
re-running it is always safe. Windows/macOS do not need it: there `uv sync`
alone works because PyPI ships binary pyfltk wheels.

## Why plain `uv sync` fails on a fresh Linux clone

PyPI has **no Linux wheels for pyfltk** (only Windows/macOS), so uv builds
pyfltk from source. That build needs `fltk-config` from an **FLTK 1.4.x**
development install -- and no mainstream distro packages FLTK 1.4 yet
(Ubuntu 24.04 ships 1.3.8, which pyfltk 1.4.x refuses). Without it, the
build dies with a confusing setuptools traceback ("No distribution was
found...") whose real message is printed much earlier: "fltk-config not
found".

`scripts/setup.sh` closes that gap: if no FLTK 1.4 is found, it downloads
the FLTK 1.4.5 source release, builds it in ~2 minutes, and installs it to
`~/.local` (no sudo). Then it runs `uv sync` and verifies `import fltk`.

## Prerequisites

- `uv` (https://astral.sh/uv), plus a C++ toolchain and cmake:
  `sudo apt install build-essential cmake` (Debian/Ubuntu)
- X11 development headers. Debian/Ubuntu:

      sudo apt install libx11-dev libxft-dev libxext-dev libxinerama-dev \
          libxcursor-dev libxrender-dev libxfixes-dev

  The script checks for all of these up front and prints the exact install
  command for anything missing (Fedora hints included). Nothing else is
  needed: no OpenGL/GLU, no Wayland libs, no system jpeg/png dev packages,
  no system swig.
- Optional, only for running the GUI test suite: `sudo apt install xvfb`.

## How FLTK is built (deliberately minimal)

`scripts/setup.sh` configures FLTK 1.4.5 with:

- **X11 backend only** (`FLTK_BACKEND_WAYLAND=OFF`): flcmd's drag-out shim
  (`flcmd/dnd/x11.py`) talks XDND directly, so the X11 backend is required
  anyway; Wayland would only add libwayland/libdecor/etc. bloat.
- **No OpenGL** (`FLTK_BUILD_GL=OFF`): flcmd never uses GL; enabling it
  drags in a GLU dev dependency.
- **Bundled jpeg/png/zlib** (`FLTK_USE_SYSTEM_*=OFF`): pyfltk's setup.py
  only understands plain `-lfoo` flags from fltk-config; system libs show
  up as absolute `.so` paths and are silently dropped, which produces a
  pyfltk extension with undefined `jpeg_*`/`png_*` symbols at import time.
- **Static libs with PIC**: FLTK is linked *into* the pyfltk extension, so
  the venv is self-contained -- no LD_LIBRARY_PATH, no shared FLTK libs to
  ship. Runtime deps are only X11/Xft/fontconfig, present on any desktop.
- No fluid, no tests, no examples.

After installing, the script patches one line of the installed
`fltk-config`: upstream fltk-config advertises `-lfltk_gl` under
`--use-gl` even when FLTK was built without GL, which fools pyfltk's GL
autodetection into linking a library that does not exist. The patch makes
`--use-gl` a no-op, matching reality.

## Why pyfltk is vendored (vendor/pyfltk-1.4.5.0-patched.tar.gz)

`pyproject.toml` points uv at a patched pyfltk sdist for Linux only
(`[tool.uv.sources]` with a `sys_platform == 'linux'` marker); Windows and
macOS keep using PyPI wheels. The pristine PyPI sdist cannot build against
a GL-less FLTK 1.4.5 because its no-GL support has bitrotted upstream.
Three fixes, all recorded in `scripts/patches/pyfltk-1.4.5.0-gl-stubs.patch`
(plus one pyproject.toml line):

1. `src/Fl_Gl_Stubs.cxx` defines `Fl_Gl_Window::make_overlay()`, which
   FLTK 1.4.5 removed -- compile error. Stub deleted.
2. The same file is missing stubs FLTK 1.4.5 *does* need
   (`Fl_Gl_Window::draw/handle/pixels_per_unit/swap_interval`,
   `gl_texture_*`) -- undefined symbols at import. Stubs added.
3. Its `glBegin`/`glClear`/... stubs have C++ linkage, but the swig
   wrapper references them via `<GL/gl.h>` prototypes with C linkage --
   undefined symbols at import. Wrapped in `extern "C"`, `glDrawPixels`
   added.
4. (pyproject.toml) pyfltk's build silently requires a system `swig`
   binary; the vendored copy adds the pip-installable `swig` to
   `build-system.requires`, so uv provisions it in the isolated build env.

To regenerate the vendored tarball (e.g. for a new pyfltk release):
download the sdist from PyPI, apply `scripts/patches/`, re-add the swig
build requirement, repack, then `uv lock --refresh-package pyfltk`.
Re-check whether upstream fixed the no-GL path first -- these are honest
upstream bugs worth reporting.

## Troubleshooting

- **"fltk-config not found" during uv sync**: you ran `uv sync` without
  running `scripts/setup.sh` first (or `~/.local/bin` is not on PATH).
- **pyfltk imports fail with undefined symbols after changing FLTK**:
  a wheel built against the old FLTK is cached. `uv cache clean pyfltk &&
  uv sync --reinstall-package pyfltk` (setup.sh does this automatically
  whenever it rebuilds FLTK).
- **Hash mismatch on vendor/pyfltk...tar.gz**: the vendored tarball
  changed but the lockfile still pins the old hash. Run
  `uv lock --refresh-package pyfltk`.
- **GUI tests all skip**: install `xvfb` (they use their own display,
  never yours).
