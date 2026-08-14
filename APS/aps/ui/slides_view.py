#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""演示编辑视图：左侧缩略图 + 中间画布编辑 + 播放。"""
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Pango

from aps.core.slides import SlidesEngine


class SlidesView(Gtk.Box):
    def __init__(self, engine: SlidesEngine = None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.engine = engine or SlidesEngine(None)

        # 左侧缩略图
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        left.set_size_request(180, -1)
        self.thumb_list = Gtk.ListBox()
        self.thumb_list.connect("row-activated", self._on_thumb)
        sw = Gtk.ScrolledWindow()
        sw.set_child(self.thumb_list)
        sw.set_vexpand(True)
        left.append(sw)
        self.append(left)

        # 右侧画布
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        right.set_hexpand(True)

        self.title_entry = Gtk.Entry()
        self.title_entry.set_placeholder_text("幻灯片标题")
        self.title_entry.set_hexpand(True)
        self.title_entry.connect("changed", self._on_title_changed)
        right.append(self.title_entry)

        self.body_view = Gtk.TextView()
        self.body_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.body_buf = self.body_view.get_buffer()
        self.body_buf.connect("changed", self._on_body_changed)
        bsw = Gtk.ScrolledWindow()
        bsw.set_child(self.body_view)
        bsw.set_vexpand(True)
        right.append(bsw)

        page_lbl = Gtk.Label()
        self.page_label = page_lbl
        self.page_label.add_css_class("dim-label")
        right.append(page_lbl)

        # 播放窗口（全屏）
        self.play_win = None
        self.append(right)

        self._render_thumbs()
        self._load_active()

    # ------------------------------------------------------------------
    def _render_thumbs(self):
        while (row := self.thumb_list.get_first_child()) is not None:
            self.thumb_list.remove(row)
        for i, s in enumerate(self.engine.slides):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            lbl = Gtk.Label(label=f"第 {i + 1} 页", xalign=0)
            lbl.add_css_class("dim-label")
            t = Gtk.Label(label=s.get("title", "") or "（无标题）", xalign=0)
            t.set_ellipsize(Pango.EllipsizeMode.END)
            box.append(lbl)
            box.append(t)
            row = Gtk.ListBoxRow()
            row.set_child(box)
            row.idx = i
            self.thumb_list.append(row)

    def _on_thumb(self, lst, row):
        self.engine.active = row.idx
        self._load_active()

    def _load_active(self):
        s = self.engine.slides[self.engine.active]
        self.title_entry.set_text(s.get("title", ""))
        self.body_buf.set_text("\n".join(s.get("body", [])))
        self.page_label.set_text(f"{self.engine.active + 1} / {len(self.engine.slides)}")
        self._select_thumb()

    def _select_thumb(self):
        row = self.thumb_list.get_row_at_index(self.engine.active)
        if row:
            self.thumb_list.select_row(row)

    def _on_title_changed(self, *_):
        self.engine.slides[self.engine.active]["title"] = self.title_entry.get_text()
        self.engine.dirty = True

    def _on_body_changed(self, *_):
        text = self.body_buf.get_text(self.body_buf.get_start_iter(),
                                      self.body_buf.get_end_iter(), False)
        self.engine.slides[self.engine.active]["body"] = [l for l in text.splitlines() if l.strip()]
        self.engine.dirty = True

    # ------------------------------------------------------------------
    def action(self, action: str):
        if action == "add-slide":
            self.engine.add_slide()
            self._render_thumbs()
            self._load_active()
        elif action == "del-slide":
            self.engine.remove_slide(self.engine.active)
            self._render_thumbs()
            self._load_active()
        elif action == "layout-title":
            self.engine.slides[self.engine.active]["layout"] = "title"
            self.engine.dirty = True
        elif action == "layout-content":
            self.engine.slides[self.engine.active]["layout"] = "content"
            self.engine.dirty = True
        elif action == "move-up":
            idx = self.engine.active
            if idx > 0:
                self.engine.slides[idx - 1], self.engine.slides[idx] = self.engine.slides[idx], self.engine.slides[idx - 1]
                self.engine.active = idx - 1
                self._render_thumbs()
                self._load_active()
        elif action == "move-down":
            idx = self.engine.active
            if idx < len(self.engine.slides) - 1:
                self.engine.slides[idx + 1], self.engine.slides[idx] = self.engine.slides[idx], self.engine.slides[idx + 1]
                self.engine.active = idx + 1
                self._render_thumbs()
                self._load_active()
        elif action == "play":
            self._play()

    def _play(self):
        if self.play_win is not None:
            return
        win = Gtk.Window(title="播放")
        win.set_default_size(960, 540)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(30)
        box.set_margin_bottom(30)
        box.set_margin_start(50)
        box.set_margin_end(50)

        self.play_label = Gtk.Label()
        self.play_label.set_wrap(True)
        self.play_label.set_justify(Gtk.Justification.CENTER)
        self.play_label.add_css_class("title-1")
        box.append(self.play_label)
        self.play_body = Gtk.Label()
        self.play_body.set_wrap(True)
        self.play_body.add_css_class("title-3")
        box.append(self.play_body)
        win.set_child(box)

        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        prev = Gtk.Button(label="◀ 上一页")
        prev.connect("clicked", lambda *_: self._play_nav(-1))
        nav.append(prev)
        nxt = Gtk.Button(label="下一页 ▶")
        nxt.connect("clicked", lambda *_: self._play_nav(1))
        nav.append(nxt)
        close = Gtk.Button(label="退出")
        close.connect("clicked", lambda *_: self._close_play())
        nav.append(close)
        box.append(nav)

        self.play_idx = self.engine.active
        self._play_show()
        win.connect("close-request", self._on_play_close)
        win.present()
        self.play_win = win

    def _play_show(self):
        s = self.engine.slides[self.play_idx]
        self.play_label.set_text(s.get("title", ""))
        self.play_body.set_text("\n".join(s.get("body", [])))

    def _play_nav(self, delta):
        self.play_idx = (self.play_idx + delta) % len(self.engine.slides)
        self._play_show()

    def _close_play(self):
        if self.play_win:
            self.play_win.close()

    def _on_play_close(self, *args):
        self.play_win = None
        return False
