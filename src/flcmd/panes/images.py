"""Image loading for the preview panel and thumbnail view. Uses FLTK's
built-in decoders (libjpeg/libpng: fast C, no extra deps) with an optional
Pillow fallback for webp and anything else FLTK can't read.

Deliberately avoids Fl_Shared_Image: its cache refcounting fights SWIG
proxy ownership (double frees). Direct loader objects are plainly owned
by Python and freed once by GC; thumbnails are cached by the views."""

import fltk

IMG_EXT = {"jpg", "jpeg", "png", "gif", "bmp", "webp"}
_LOADERS = {
    "jpg": fltk.Fl_JPEG_Image, "jpeg": fltk.Fl_JPEG_Image,
    "png": fltk.Fl_PNG_Image, "gif": fltk.Fl_GIF_Image,
    "bmp": fltk.Fl_BMP_Image,
}


def is_image(name: str) -> bool:
    i = name.rfind(".")
    return i > 0 and name[i + 1:].lower() in IMG_EXT


def _pillow_load(path: str):
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        pi = Image.open(path)
        pi = pi.convert("RGBA" if "A" in pi.getbands() else "RGB")
        data = pi.tobytes()
        img = fltk.Fl_RGB_Image(data, pi.width, pi.height, len(pi.getbands()))
        img._keep = data  # pyfltk references the buffer; keep it alive
        return img
    except Exception:
        return None


def load_full(path: str):
    """Full-size image or None."""
    cls = _LOADERS.get(path.rsplit(".", 1)[-1].lower())
    if cls:
        try:
            img = cls(path)
            if img.w() > 0 and img.h() > 0 and img.fail() >= 0:
                return img
        except Exception:
            pass
    return _pillow_load(path)


def release_full(img):
    """Kept for call-site symmetry; plain images are freed by GC."""


def load_thumb(path: str, box: int):
    """Small copy fitting in box x box (aspect kept), or None."""
    img = load_full(path)
    if img is None:
        return None
    w, h = img.w(), img.h()
    scale = min(box / w, box / h, 1.0)
    tw, th = max(1, int(w * scale)), max(1, int(h * scale))
    return img.copy(tw, th)
