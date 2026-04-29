#!/usr/bin/env python3
"""
Entry point for the GNOME Local AI Chatbot.
Initialises and runs the GTK4/Libadwaita application.
"""

import sys
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, Gio
from app.window import MainWindow


class ChatApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="com.example.LocalAIChatbot",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.connect("activate", self.on_activate)

    def on_activate(self, app):
        win = MainWindow(application=app)
        win.present()


def main():
    app = ChatApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())