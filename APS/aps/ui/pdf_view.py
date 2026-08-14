#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 阅读视图：分页文本 + 页码导航。"""
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from aps.core.pdfview import PdfEngine


class PdfView(Gtk.Box):
    def __init__(self, engine: PdfEngine = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.engine = engine or PdfEngine(None)
        self.page = 0

        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        prev = Gtk.Button(label="◀")
        prev.connect("clicked", lambda *_: self._nav(-1))
        nav.append(prev)
        self.page_label = Gtk.Label(label="0 / 0")
        nav.append(self.page_label)
        nxt = Gtk.Button(label="▶")
        nxt.connect("clicked", lambda *_: self._nav(1))
        nav.append(nxt)
        self.append(nav)

        self.view = Gtk.TextView()
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.view.set_editable(False)
        self.buffer = self.view.get_buffer()
        sw = Gtk.ScrolledWindow()
        sw.set_child(self.view)
        sw.set_vexpand(True)
        self.append(sw)

        self._show_page()

    def _nav(self, delta):
        if not self.engine.pages:
            return
        self.page = max(0, min(len(self.engine.pages) - 1, self.page + delta))
        self._show_page()

    def _show_page(self):
        if not self.engine.pages:
            self.page_label.set_text("0 / 0")
            self.buffer.set_text("（PDF 无文本内容）")
            return
        self.page_label.set_text(f"{self.page + 1} / {len(self.engine.pages)}")
        self.buffer.set_text(self.engine.pages[self.page] or "（本页无文本）")
