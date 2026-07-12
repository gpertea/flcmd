def esc(s: str) -> str:
    """Escape FLTK label text: '@' starts a symbol sequence in labels."""
    return s.replace("@", "@@")
