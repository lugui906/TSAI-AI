import sys
import os
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gio, GLib, Gdk

Gtk.Window.set_default_icon_name("applications-utilities")
GLib.set_prgname("com.example.AIAssistant")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui import MainWindow

try:
    import chindows_theme.style as chstyle
except ImportError:
    import os as _os, sys as _sys
    _d = _os.path.dirname(_os.path.abspath(__file__))
    while _d and not _os.path.isdir(_os.path.join(_d, "chindows_theme")):
        _p = _os.path.dirname(_d)
        if _p == _d:
            break
        _d = _p
    if _d:
        _sys.path.insert(0, _d)
    try:
        import chindows_theme.style as chstyle
    except Exception:
        chstyle = None



class AIAssistantApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="com.example.AIAssistant",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = MainWindow(self)
        self.window.present()


def main():
    if chstyle:
        chstyle.apply_gtk4()
    app = AIAssistantApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
