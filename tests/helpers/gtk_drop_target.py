"""Standalone GTK3 window that accepts file drops (text/uri-list) and writes
the received URIs to the file given as argv[1], then exits. Run with the
SYSTEM python3 (pygobject); proves XDND interop with GTK apps."""

import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")  # else Gdk may resolve to 4.0 first
from gi.repository import Gdk, Gtk  # noqa: E402

out = sys.argv[1]


def on_received(w, ctx, x, y, data, info, time_):
    with open(out, "w") as f:
        f.write("\n".join(data.get_uris()))
    ctx.finish(True, False, time_)
    Gtk.main_quit()


win = Gtk.Window(title="drop-target")
win.set_default_size(250, 300)
win.move(1000, 100)  # clear of the flcmd window (which sits at 0,0)
target = Gtk.TargetEntry.new("text/uri-list", 0, 0)
win.drag_dest_set(Gtk.DestDefaults.ALL, [target], Gdk.DragAction.COPY)
win.connect("drag-data-received", on_received)
win.connect("destroy", Gtk.main_quit)
win.show_all()
print("READY", flush=True)
Gtk.main()
