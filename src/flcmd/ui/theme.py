"""Palette sampled from the reference Total Commander screenshot
(totalcmd.png): pale-blue cursor bar with normal text (never inverted),
red selection font, subtly alternating row backgrounds."""

import fltk


def _c(r, g, b):
    return fltk.fl_rgb_color(r, g, b)


ROW_BG = _c(249, 252, 255)        # even rows
ROW_BG_ALT = _c(235, 242, 254)    # odd rows
CURSOR_BG = _c(199, 230, 255)     # cursor bar (focused pane)
CURSOR_EDGE = _c(153, 180, 209)   # cursor outline (unfocused pane)
TEXT = fltk.FL_BLACK
SEL_TEXT = _c(204, 0, 0)          # selected entries: red font
HEADER_BG = fltk.FL_WHITE
HEADER_EDGE = _c(208, 214, 222)
PATH_ACTIVE = _c(153, 180, 209)
PATH_IDLE = _c(191, 205, 219)
FOOTER_BG = _c(240, 240, 240)
HOVER_BG = _c(229, 241, 251)      # pointer-over tint for buttons
CLOSE_HOVER = _c(232, 17, 35)     # close caption button hover (red)
TITLE_IDLE = _c(128, 128, 128)    # title text when the window is inactive


def apply_scheme():
    """Classic flat look on all platforms: the base scheme with the
    standard box types remapped to their 1px thin variants (the gtk+
    scheme's gradient 'pillow' bevels waste rows and match no platform)."""
    fltk.Fl.scheme("none")
    fltk.Fl.background(240, 240, 240)  # match FOOTER_BG / Win button face
    fltk.Fl.scrollbar_size(12)         # compact scrollbars (default 16)
    for full, thin in ((fltk.FL_UP_BOX, fltk.FL_THIN_UP_BOX),
                       (fltk.FL_DOWN_BOX, fltk.FL_THIN_DOWN_BOX),
                       (fltk.FL_UP_FRAME, fltk.FL_THIN_UP_FRAME),
                       (fltk.FL_DOWN_FRAME, fltk.FL_THIN_DOWN_FRAME)):
        fltk.Fl.set_boxtype(full, thin)
