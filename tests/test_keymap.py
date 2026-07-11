import fltk

from flcmd.keymap import DEFAULTS, Keymap, parse


def test_parse_basic():
    assert parse("F3") == (fltk.FL_F + 3, 0)
    assert parse("Ctrl+F3") == (fltk.FL_F + 3, fltk.FL_CTRL)
    assert parse("Alt+F4") == (fltk.FL_F + 4, fltk.FL_ALT)
    assert parse("Tab") == (fltk.FL_Tab, 0)
    assert parse("Ctrl+A") == (ord("a"), fltk.FL_CTRL)
    assert parse("KP+") == (fltk.FL_KP + ord("+"), 0)
    assert parse("Ctrl+Shift+A") == (ord("a"), fltk.FL_CTRL | fltk.FL_SHIFT)


def test_lookup_defaults():
    km = Keymap()
    assert km.lookup(fltk.FL_F + 5, 0) == "file.copy"
    assert km.lookup(fltk.FL_Tab, 0) == "pane.switch"
    assert km.lookup(ord("u"), fltk.FL_CTRL) == "pane.swap"
    assert km.lookup(fltk.FL_F + 3, fltk.FL_CTRL) == "sort.name"
    assert km.lookup(fltk.FL_Delete, 0) == "file.delete"
    assert km.lookup(ord("z"), 0) is None
    # numlock/capslock style extra state bits are ignored
    assert km.lookup(fltk.FL_F + 5, fltk.FL_NUM_LOCK) == "file.copy"


def test_overrides():
    km = Keymap({"file.view": "Ctrl+Q"})
    assert km.lookup(ord("q"), fltk.FL_CTRL) == "file.view"
    assert km.lookup(fltk.FL_F + 3, 0) is None


def test_all_defaults_parse():
    for action, specs in DEFAULTS.items():
        for spec in specs:
            parse(spec)
