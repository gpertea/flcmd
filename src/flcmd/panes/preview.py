"""Quick-view panel (TC Ctrl+Q): this pane displays the image under the
cursor of the OTHER pane. Zoom lock: fit / fitw (fit width) / 100,
persisted in flcmd.ini [preview] and re-applied on any pane resize."""

import fltk

from .. import config, paths
from ..ui import theme
from .. import images

ZOOMS = ("fit", "fitw", "100")


class PreviewView(fltk.Fl_Group):
    def __init__(self, x, y, w, h, pane):
        super().__init__(x, y, w, h)
        self.pane = pane
        self.zoom = str(config.load().get("preview", {}).get("zoom", "fit"))
        self.scroll = fltk.Fl_Scroll(x, y, w, h)
        self.scroll.color(theme.ROW_BG)
        self.scroll.type(fltk.Fl_Scroll.BOTH)
        self.box = fltk.Fl_Box(x, y, w, h)
        self.box.labelsize(12)
        self.scroll.end()
        self.end()
        self.resizable(self.scroll)
        self._img = None
        self._path = None
        self._msg = "no file"

    def set_zoom(self, zoom: str):
        self.zoom = zoom
        config.update("preview", {"zoom": zoom})
        self._apply()

    def show_file(self, local_path: str | None, entry=None):
        """local_path None -> nothing to preview (message only)."""
        if self._img is not None:
            images.release_full(self._img)
            self._img = None
        self._path = local_path
        name = entry.name if entry else (paths.basename(local_path)
                                         if local_path else "")
        if local_path and images.is_image(local_path):
            self._img = images.load_full(local_path)
            self._msg = "" if self._img else f"cannot decode {name}"
        elif entry and entry.is_dir:
            self._msg = f"[{name}]"
        else:
            self._msg = name or "no file"
        self.pane.header.copy_label(f" Preview: {name}" if name else " Preview")
        self._apply()

    def _zoom_scale(self, iw: int, ih: int, aw: int, ah: int) -> float:
        if self.zoom == "100":
            return 1.0
        if self.zoom == "fitw":
            return aw / iw
        return min(aw / iw, ah / ih)  # fit

    def _apply(self):
        sb = fltk.Fl.scrollbar_size()
        aw, ah = self.scroll.w() - sb, self.scroll.h() - sb
        if self._img is None:
            self.box.image(None)
            self.box.copy_label(self._msg)
            self.box.resize(self.scroll.x(), self.scroll.y(),
                            self.scroll.w(), self.scroll.h())
            self.pane.footer.copy_label(f" {self._msg}")
        else:
            iw, ih = self._img.data_w(), self._img.data_h()
            s = self._zoom_scale(iw, ih, max(1, aw), max(1, ah))
            sw, sh = max(1, int(iw * s)), max(1, int(ih * s))
            self._img.scale(sw, sh, 0, 1)
            self.box.copy_label("")
            self.box.image(self._img)
            bw = max(sw, self.scroll.w() - (sb if sh > self.scroll.h() else 0))
            bh = max(sh, self.scroll.h() - (sb if sw > self.scroll.w() else 0))
            self.box.resize(self.scroll.x(), self.scroll.y(), bw, bh)
            self.scroll.scroll_to(0, 0)
            self.pane.footer.copy_label(
                f" {iw} x {ih}   zoom: {self.zoom} ({100 * s:.0f}%)")
        self.scroll.redraw()
        self.redraw()

    def resize(self, x, y, w, h):
        super().resize(x, y, w, h)
        self._apply()

    def close(self):
        if self._img is not None:
            images.release_full(self._img)
            self._img = None
