#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文字编辑视图：GTK4 富文本（加粗/斜体/字号/颜色/对齐）+ 查找替换。"""
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Pango

from aps.core.writer import WriterEngine


class WriterView(Gtk.Box):
    def __init__(self, engine: WriterEngine = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.engine = engine or WriterEngine(None)

        # 查找栏（默认隐藏）
        self.find_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.find_bar.set_margin_top(2)
        self.find_entry = Gtk.Entry()
        self.find_entry.set_placeholder_text("查找…")
        self.find_entry.set_hexpand(True)
        self.find_entry.connect("activate", lambda *_: self._find_next())
        self.find_bar.append(self.find_entry)
        for label, fn in [("上一个", self._find_prev), ("下一个", self._find_next)]:
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda *_, f=fn: f())
            self.find_bar.append(b)
        self.replace_entry = Gtk.Entry()
        self.replace_entry.set_placeholder_text("替换为…")
        self.replace_entry.set_hexpand(True)
        self.find_bar.append(self.replace_entry)
        for label, fn in [("替换", self._replace_one), ("全部", self._replace_all)]:
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda *_, f=fn: f())
            self.find_bar.append(b)
        close_btn = Gtk.Button(label="✕")
        close_btn.connect("clicked", lambda *_: self.find_bar.set_visible(False))
        self.find_bar.append(close_btn)
        self.find_bar.set_visible(False)
        self.append(self.find_bar)

        # 编辑区
        self.view = Gtk.TextView()
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(24)
        self.view.set_right_margin(24)
        self.view.set_top_margin(12)
        self.view.set_bottom_margin(12)
        self.buffer = self.view.get_buffer()

        # 格式 tag 表
        self.tags = {}
        self._make_tags()

        sw = Gtk.ScrolledWindow()
        sw.set_child(self.view)
        sw.set_vexpand(True)
        self.append(sw)

        self._load_engine()

    # ------------------------------------------------------------------
    def _make_tags(self):
        b = self.buffer
        self.tags["bold"] = b.create_tag("bold", weight=Pango.Weight.BOLD)
        self.tags["italic"] = b.create_tag("italic", style=Pango.Style.ITALIC)
        self.tags["size-18"] = b.create_tag("size-18", size_points=18)
        self.tags["size-24"] = b.create_tag("size-24", size_points=24)
        self.tags["size-32"] = b.create_tag("size-32", size_points=32)
        self.tags["color-red"] = b.create_tag("color-red", foreground="#e53935")
        self.tags["color-blue"] = b.create_tag("color-blue", foreground="#1e88e5")
        self.tags["color-green"] = b.create_tag("color-green", foreground="#43a047")
        self.tags["align-center"] = b.create_tag("align-center", justification=Gtk.Justification.CENTER)
        self.tags["align-right"] = b.create_tag("align-right", justification=Gtk.Justification.RIGHT)

    def _load_engine(self):
        self.buffer.set_text("")
        for p in self.engine.paragraphs:
            end = self.buffer.get_end_iter()
            start = end.copy()
            self.buffer.insert(end, (p.get("text", "") or "") + "\n")
            end = self.buffer.get_end_iter()
            if p.get("bold"):
                self.buffer.apply_tag(self.tags["bold"], start, end)
            if p.get("italic"):
                self.buffer.apply_tag(self.tags["italic"], start, end)
            size = p.get("size")
            if size:
                key = "size-%d" % int(size)
                if key in self.tags:
                    self.buffer.apply_tag(self.tags[key], start, end)
            color = p.get("color")
            if color and color.startswith("#"):
                key = "color-" + color[1:]
                if key in self.tags:
                    self.buffer.apply_tag(self.tags[key], start, end)
            align = p.get("align")
            if align and align != "left" and "align-" + align in self.tags:
                self.buffer.apply_tag(self.tags["align-" + align], start, end)

    # ------------------------------------------------------------------
    def sync_to_engine(self):
        """把 buffer 内容（含格式）同步回 WriterEngine。"""
        self.engine.paragraphs = []
        buf = self.buffer
        end = buf.get_end_iter()
        line = 0
        while True:
            ok, ls = buf.get_iter_at_line(line)
            if not ok:
                break
            if ls.get_offset() >= end.get_offset():
                break
            le = ls.copy()
            if not le.ends_line():
                le.forward_to_line_end()
            text = buf.get_text(ls, le, False)
            p = {"text": text, "style": None, "bold": None, "italic": None,
                 "size": None, "color": None, "align": None}
            probe = ls.copy()
            if probe.has_tag(self.tags["bold"]):
                p["bold"] = True
            if probe.has_tag(self.tags["italic"]):
                p["italic"] = True
            for key, tag in self.tags.items():
                if key.startswith("size-") and probe.has_tag(tag):
                    p["size"] = int(key.split("-")[1])
                elif key.startswith("color-") and probe.has_tag(tag):
                    p["color"] = "#" + key.split("-")[1]
                elif key.startswith("align-") and probe.has_tag(tag):
                    p["align"] = key.split("-")[1]
            self.engine.paragraphs.append(p)
            if le.get_offset() >= end.get_offset():
                break
            line += 1
        self.engine.dirty = True

    # ------------------------------------------------------------------
    # 工具栏动作
    # ------------------------------------------------------------------
    def apply_to_selection(self, tag_key: str):
        tag = self.tags.get(tag_key)
        if tag is None:
            return
        bounds = self.buffer.get_selection_bounds()
        if not bounds:
            return
        start, end = bounds
        if self.buffer.iter_has_tag(start, tag):
            self.buffer.remove_tag(tag, start, end)
        else:
            self.buffer.apply_tag(tag, start, end)

    def action(self, action: str):
        if action in ("bold", "italic"):
            self.apply_to_selection(action)
        elif action == "align-left":
            self._set_alignment("left")
        elif action == "align-center":
            self._set_alignment("center")
        elif action == "align-right":
            self._set_alignment("right")
        elif action == "style-title":
            self._style_current("title")
        elif action == "style-body":
            self._style_current("body")
        elif action == "find":
            self.find_bar.set_visible(True)
            self.find_entry.grab_focus()
        elif action == "replace":
            self.find_bar.set_visible(True)
            self.replace_entry.grab_focus()
        self.sync_to_engine()

    def _set_alignment(self, align):
        key = "align-" + align
        tag = self.tags.get(key)
        if not tag:
            return
        bounds = self.buffer.get_selection_bounds()
        if bounds:
            self.buffer.apply_tag(tag, bounds[0], bounds[1])
        else:
            # 整段应用
            line = self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_line()
            _, s = self.buffer.get_iter_at_line(line)
            e = s.copy()
            e.forward_to_line_end()
            self.buffer.apply_tag(tag, s, e)

    def _style_current(self, style):
        it = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        line = it.get_line()
        _, s = self.buffer.get_iter_at_line(line)
        e = s.copy()
        e.forward_to_line_end()
        if style == "title":
            self.buffer.apply_tag(self.tags["size-32"], s, e)
        else:
            for key in ("size-32", "size-24", "size-18"):
                self.buffer.remove_tag(self.tags[key], s, e)

    # ------------------------------------------------------------------
    # 查找替换
    # ------------------------------------------------------------------
    def _find(self, backward=False):
        needle = self.find_entry.get_text()
        if not needle:
            return
        start = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        if backward:
            match = start.backward_search(needle, Gtk.TextSearchFlags.TEXT_LOOKAHEAD, None)
            if match:
                start_iter, end_iter = match
                self.buffer.select_range(end_iter, start_iter)
        else:
            match = start.forward_search(needle, Gtk.TextSearchFlags.TEXT_LOOKAHEAD, None)
            if match:
                start_iter, end_iter = match
                self.buffer.select_range(start_iter, end_iter)
        self.view.scroll_to_mark(self.buffer.get_insert(), 0.2, False, 0, 0)

    def _find_next(self, *_):
        self._find(backward=False)

    def _find_prev(self, *_):
        self._find(backward=True)

    def _replace_one(self, *_):
        needle = self.find_entry.get_text()
        repl = self.replace_entry.get_text()
        bounds = self.buffer.get_selection_bounds()
        if bounds and self.buffer.get_text(bounds[0], bounds[1], False) == needle:
            self.buffer.delete(bounds[0], bounds[1])
            self.buffer.insert_at_cursor(repl)
        self._find_next()

    def _replace_all(self, *_):
        needle = self.find_entry.get_text()
        repl = self.replace_entry.get_text()
        if not needle:
            return
        text = self.buffer.get_text(self.buffer.get_start_iter(),
                                    self.buffer.get_end_iter(), False)
        count = text.count(needle)
        self.buffer.set_text(text.replace(needle, repl))
        self.sync_to_engine()
        self.find_bar.set_visible(True)
