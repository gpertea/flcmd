"""Keyboard action table. Every shortcut resolves to an action name here;
widgets never hardcode keys. Bindings are remappable via config
([keys] section: action = "Ctrl+X" or list of specs)."""

import fltk

_MODS = {
    "ctrl": fltk.FL_CTRL,
    "alt": fltk.FL_ALT,
    "shift": fltk.FL_SHIFT,
    "meta": fltk.FL_META,
}
_KEYS = {
    "tab": fltk.FL_Tab,
    "enter": fltk.FL_Enter,
    "kpenter": fltk.FL_KP_Enter,
    "backspace": fltk.FL_BackSpace,
    "insert": fltk.FL_Insert,
    "delete": fltk.FL_Delete,
    "escape": fltk.FL_Escape,
    "space": ord(" "),
    "home": fltk.FL_Home,
    "end": fltk.FL_End,
    "pgup": fltk.FL_Page_Up,
    "pgdn": fltk.FL_Page_Down,
    "up": fltk.FL_Up,
    "down": fltk.FL_Down,
    "left": fltk.FL_Left,
    "right": fltk.FL_Right,
    "kp+": fltk.FL_KP + ord("+"),
    "kp-": fltk.FL_KP + ord("-"),
    "kp*": fltk.FL_KP + ord("*"),
}

# Total Commander defaults (docs/KEYBINDINGS.md). Stage 2+ actions are bound
# now so the keys are reserved; unimplemented ones report in the status bar.
DEFAULTS = {
    "pane.switch": ["Tab"],
    "pane.swap": ["Ctrl+U"],
    "pane.refresh": ["Ctrl+R"],
    "nav.open": ["Enter", "KPEnter"],
    "nav.up": ["BackSpace", "Ctrl+PgUp"],
    "nav.cursor_to_left": ["Ctrl+Left"],
    "nav.cursor_to_right": ["Ctrl+Right"],
    "sel.toggle": ["Insert"],
    "sel.toggle_space": ["Space"],
    "sel.all": ["Ctrl+A"],
    "sel.none": ["Ctrl+Shift+A"],
    "sel.glob_add": ["KP+"],
    "sel.glob_sub": ["KP-"],
    "sel.invert": ["KP*"],
    "sort.name": ["Ctrl+F3"],
    "sort.ext": ["Ctrl+F4"],
    "sort.date": ["Ctrl+F5"],
    "sort.size": ["Ctrl+F6"],
    "file.view": ["F3"],
    "file.edit": ["F4"],
    "file.edit_new": ["Shift+F4"],
    "file.copy": ["F5"],
    "file.move": ["F6"],
    "file.rename": ["F2", "Shift+F6"],
    "file.mkdir": ["F7"],
    "file.delete": ["F8", "Delete"],
    "file.props": ["Alt+Enter"],
    "pane.dirsize": ["Ctrl+L"],
    "app.quit": ["Alt+F4"],
}


def parse(spec: str) -> tuple[int, int]:
    """'Ctrl+F3' -> (keycode, modifier mask)."""
    parts = spec.split("+")
    # 'KP+' style specs: a trailing empty part means a literal '+'
    if parts[-1] == "" and len(parts) >= 2:
        parts = parts[:-2] + [parts[-2] + "+"]
    mods = 0
    for m in parts[:-1]:
        mods |= _MODS[m.lower()]
    k = parts[-1].lower()
    if k in _KEYS:
        key = _KEYS[k]
    elif len(k) == 1:
        key = ord(k)
    elif k.startswith("f") and k[1:].isdigit():
        key = fltk.FL_F + int(k[1:])
    else:
        raise ValueError(f"unknown key spec: {spec}")
    return key, mods


class Keymap:
    def __init__(self, overrides: dict | None = None):
        self._map: dict[tuple[int, int], str] = {}
        table = dict(DEFAULTS)
        for action, specs in (overrides or {}).items():
            if isinstance(specs, str):  # ini form: "F3" or "F3, Ctrl+Q"
                specs = [s.strip() for s in specs.split(",") if s.strip()]
            table[action] = specs
        for action, specs in table.items():
            for spec in specs:
                self._map[parse(spec)] = action

    def lookup(self, key: int, state: int) -> str | None:
        mods = state & (fltk.FL_CTRL | fltk.FL_ALT | fltk.FL_SHIFT | fltk.FL_META)
        act = self._map.get((key, mods))
        if act is None and mods & fltk.FL_SHIFT:
            # Shift+letter produces uppercase event text; retry without shift
            act = self._map.get((key, mods & ~fltk.FL_SHIFT))
        return act

    def action_for_event(self) -> str | None:
        return self.lookup(fltk.Fl.event_key(), fltk.Fl.event_state())
