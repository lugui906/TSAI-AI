import sys
import os
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui import MainWindow


class AIAssistantApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="com.example.AIAssistant",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )

    def do_activate(self):
        window = MainWindow(self)
        window.show_all()


def main():
    app = AIAssistantApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
