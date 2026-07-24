#!/usr/bin/env bash
# One-shot setup after cloning: ensures FLTK 1.4 is available (building it
# from source if needed), then runs `uv sync`.
#
# Only Linux needs this: PyPI has no Linux wheels for pyfltk, so uv builds
# the pyfltk sdist, which requires `fltk-config` from an FLTK 1.4.x dev
# install. On Windows/macOS plain `uv sync` works (binary wheels).
#
# Usage: scripts/setup.sh [--prefix DIR] [--force-fltk] [--jobs N]
#   --prefix DIR   where to install FLTK (default: $HOME/.local; use
#                  /usr/local only if you run the script with sudo access)
#   --force-fltk   rebuild/reinstall FLTK even if fltk-config is found
#   --jobs N       parallel build jobs (default: nproc)

set -euo pipefail

FLTK_VERSION=1.4.5
FLTK_URL="https://github.com/fltk/fltk/releases/download/release-${FLTK_VERSION}/fltk-${FLTK_VERSION}-source.tar.gz"

PREFIX="${HOME}/.local"
FORCE_FLTK=0
JOBS="$(nproc 2>/dev/null || echo 4)"

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="$2"; shift 2 ;;
        --force-fltk) FORCE_FLTK=1; shift ;;
        --jobs) JOBS="$2"; shift 2 ;;
        -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "error: unknown option: $1 (see --help)"; exit 2 ;;
    esac
done

die() { echo "error: $*" >&2; exit 1; }
info() { echo "== $*"; }

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

command -v uv >/dev/null 2>&1 || die "uv not found. Install it first:
  curl -LsSf https://astral.sh/uv/install.sh | sh
then re-run this script."

OS="$(uname -s)"
if [ "$OS" != "Linux" ]; then
    info "$OS detected: pyfltk installs from binary wheels, no FLTK build needed"
    info "running: uv sync"
    exec uv sync
fi

have_fltk14() {
    local v
    v="$("$1" --version 2>/dev/null)" || return 1
    case "$v" in 1.4*) return 0 ;; *) return 1 ;; esac
}

FLTK_CONFIG=""
SYNC_ARGS=""
if [ "$FORCE_FLTK" -eq 0 ]; then
    # PATH first, then the chosen prefix (covers a prior run of this script
    # when $PREFIX/bin is not yet on PATH)
    if command -v fltk-config >/dev/null 2>&1 && have_fltk14 "$(command -v fltk-config)"; then
        FLTK_CONFIG="$(command -v fltk-config)"
    elif [ -x "$PREFIX/bin/fltk-config" ] && have_fltk14 "$PREFIX/bin/fltk-config"; then
        FLTK_CONFIG="$PREFIX/bin/fltk-config"
    fi
fi

if [ -n "$FLTK_CONFIG" ]; then
    info "found FLTK $("$FLTK_CONFIG" --version) at $FLTK_CONFIG"
else
    if [ "$FORCE_FLTK" -eq 1 ]; then
        info "building FLTK ${FLTK_VERSION} from source into $PREFIX (--force-fltk)"
    else
        info "FLTK 1.4 not found: building ${FLTK_VERSION} from source into $PREFIX"
    fi

    # -- preflight: toolchain ------------------------------------------------
    MISSING_TOOLS=""
    for t in cmake make g++ tar; do
        command -v "$t" >/dev/null 2>&1 || MISSING_TOOLS="$MISSING_TOOLS $t"
    done
    command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1 \
        || MISSING_TOOLS="$MISSING_TOOLS curl"
    [ -z "$MISSING_TOOLS" ] || die "missing build tools:$MISSING_TOOLS
On Debian/Ubuntu: sudo apt install build-essential cmake curl"

    # -- preflight: X11 dev headers -----------------------------------------
    MISSING_PKGS=""
    check_hdr() { [ -e "$2" ] || MISSING_PKGS="$MISSING_PKGS $1"; }
    check_hdr libx11-dev       /usr/include/X11/Xlib.h
    check_hdr libxft-dev       /usr/include/X11/Xft/Xft.h
    check_hdr libxext-dev      /usr/include/X11/extensions/shape.h
    check_hdr libxinerama-dev  /usr/include/X11/extensions/Xinerama.h
    check_hdr libxcursor-dev   /usr/include/X11/Xcursor/Xcursor.h
    check_hdr libxrender-dev   /usr/include/X11/extensions/Xrender.h
    check_hdr libxfixes-dev    /usr/include/X11/extensions/Xfixes.h
    [ -z "$MISSING_PKGS" ] || die "missing X11 development headers.
On Debian/Ubuntu: sudo apt install$MISSING_PKGS
On Fedora: sudo dnf install libX11-devel libXft-devel libXext-devel \\
  libXinerama-devel libXcursor-devel libXrender-devel libXfixes-devel"

    # -- download + build ----------------------------------------------------
    BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/fltk-build.XXXXXX")"
    trap 'rm -rf "$BUILD_DIR"' EXIT
    TARBALL="$BUILD_DIR/fltk.tar.gz"

    info "downloading $FLTK_URL"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --retry 3 -o "$TARBALL" "$FLTK_URL" \
            || die "download failed (check network / proxy): $FLTK_URL"
    else
        wget -O "$TARBALL" "$FLTK_URL" \
            || die "download failed (check network / proxy): $FLTK_URL"
    fi

    tar -xzf "$TARBALL" -C "$BUILD_DIR"
    SRC_DIR="$BUILD_DIR/fltk-${FLTK_VERSION}"
    [ -d "$SRC_DIR" ] || die "unexpected tarball layout under $BUILD_DIR"

    # X11-only, no GL: flcmd's drag-out shim needs the X11 backend, and GL
    # would drag in a GLU dev dependency the app never uses. Bundled
    # jpeg/png/zlib because pyfltk's setup.py only understands plain -l
    # flags from fltk-config (system libs appear as absolute .so paths and
    # get silently dropped -> undefined symbols at import). Static libs
    # with PIC so the pyfltk extension embeds FLTK (no LD_LIBRARY_PATH).
    info "configuring (X11 backend, no OpenGL, bundled image libs, static PIC)"
    cmake -S "$SRC_DIR" -B "$SRC_DIR/build" \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX="$PREFIX" \
        -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
        -DFLTK_BACKEND_WAYLAND=OFF \
        -DFLTK_BUILD_GL=OFF \
        -DFLTK_USE_SYSTEM_LIBJPEG=OFF \
        -DFLTK_USE_SYSTEM_LIBPNG=OFF \
        -DFLTK_USE_SYSTEM_ZLIB=OFF \
        -DFLTK_BUILD_TEST=OFF \
        -DFLTK_BUILD_EXAMPLES=OFF \
        -DFLTK_BUILD_FLUID=OFF \
        > "$BUILD_DIR/cmake-configure.log" 2>&1 \
        || { tail -30 "$BUILD_DIR/cmake-configure.log"; die "cmake configure failed (full log above)"; }

    info "building with $JOBS jobs (takes a few minutes)"
    cmake --build "$SRC_DIR/build" -j "$JOBS" \
        > "$BUILD_DIR/cmake-build.log" 2>&1 \
        || { tail -30 "$BUILD_DIR/cmake-build.log"; die "FLTK build failed (full log above)"; }

    info "installing to $PREFIX"
    cmake --install "$SRC_DIR/build" \
        > "$BUILD_DIR/cmake-install.log" 2>&1 \
        || { tail -30 "$BUILD_DIR/cmake-install.log"; die "install failed -- if $PREFIX needs root, re-run with sudo or pick a writable --prefix"; }

    FLTK_CONFIG="$PREFIX/bin/fltk-config"
    have_fltk14 "$FLTK_CONFIG" || die "installed fltk-config not working: $FLTK_CONFIG"

    # fltk-config advertises -lfltk_gl under --use-gl even in a GL-less
    # build, which fools pyfltk into linking a library that doesn't exist.
    # Make --use-gl a no-op to match reality.
    sed -i 's/^\([[:space:]]*\)use_gl=yes$/\1use_gl=no/' "$FLTK_CONFIG"
    rm -f "$PREFIX"/lib/libfltk_gl.*   # stale lib from any earlier GL build

    # FLTK changed: drop any pyfltk wheel built against the old install
    # and force a rebuild during sync
    uv cache clean pyfltk >/dev/null 2>&1 || true
    SYNC_ARGS="--reinstall-package pyfltk"

    info "FLTK $("$FLTK_CONFIG" --version) installed"
fi

# pyfltk's setup.py finds FLTK via fltk-config on PATH
FLTK_BIN_DIR="$(dirname "$FLTK_CONFIG")"
case ":$PATH:" in
    *":$FLTK_BIN_DIR:"*) ;;
    *) export PATH="$FLTK_BIN_DIR:$PATH"
       info "note: $FLTK_BIN_DIR is not on your PATH; added for this build."
       info "      uv caches the built pyfltk wheel, so future uv syncs are fine,"
       info "      but consider adding it to PATH permanently." ;;
esac

info "running: uv sync $SYNC_ARGS"
# shellcheck disable=SC2086
uv sync $SYNC_ARGS

info "verifying pyfltk import"
uv run python -c "import fltk; print('pyfltk OK, FLTK', fltk.Fl.version())" \
    || die "pyfltk installed but failed to import"

info "done. Launch with: uv run flcmd"
