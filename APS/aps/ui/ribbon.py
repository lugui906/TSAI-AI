#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""顶部 Ribbon 工具条：文件 | 视图切换 | 上下文工具。"""
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GObject


class Ribbon(Gtk.Box):
    """WPS 风格顶部工具条。"""

    __gsignals__ = {
        "new-doc": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "open-doc": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "save-doc": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "save-as": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "switch-view": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "tool-action": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.add_css_class("toolbar")
        self.set_margin_top(2)
        self.set_margin_bottom(2)

        # ---- 文件组 ----
        self._add_group_label("文件")

        new_btn = Gtk.MenuButton(label="新建")
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        for label, kind in [("文字文档", "docx"), ("电子表格", "xlsx"),
                            ("演示文稿", "pptx"), ("PDF 文档", "pdf"),
                            ("纯文本", "txt")]:
            b = Gtk.Button(label=label)
            b.connect("clicked", self._emit_new, kind, pop)
            box.append(b)
        pop.set_child(box)
        new_btn.set_popover(pop)
        self.append(new_btn)

        open_btn = Gtk.Button(label="打开")
        open_btn.connect("clicked", lambda *_: self.emit("open-doc"))
        self.append(open_btn)

        save_btn = Gtk.Button(label="保存")
        save_btn.connect("clicked", lambda *_: self.emit("save-doc"))
        self.append(save_btn)

        saveas_btn = Gtk.Button(label="另存为")
        saveas_btn.connect("clicked", lambda *_: self.emit("save-as"))
        self.append(saveas_btn)

        # ---- 视图组 ----
        self.append(Gtk.Separator())
        self._add_group_label("视图")

        self.view_buttons = {}
        for label, key in [("文字", "writer"), ("表格", "sheet"),
                           ("演示", "slides"), ("PDF", "pdf")]:
            b = Gtk.ToggleButton(label=label)
            b.connect("toggled", self._on_view_toggled, key)
            self.append(b)
            self.view_buttons[key] = b

        # ---- 上下文工具区（动态填充）----
        self.append(Gtk.Separator())
        self._add_group_label("工具")
        self.tool_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.append(self.tool_box)

    # ------------------------------------------------------------------
    def _add_group_label(self, text):
        lbl = Gtk.Label(label=text)
        lbl.add_css_class("dim-label")
        lbl.set_margin_start(6)
        self.append(lbl)

    def _emit_new(self, btn, kind, pop):
        pop.popdown()
        self.emit("new-doc", kind)

    def _on_view_toggled(self, btn, key):
        if btn.get_active():
            for k, b in self.view_buttons.items():
                if k != key:
                    b.set_active(False)
            self.emit("switch-view", key)

    # ------------------------------------------------------------------
    def set_view(self, key: str):
        for k, b in self.view_buttons.items():
            b.set_active(k == key)

    def set_tools(self, widget: Gtk.Widget | None):
        """替换上下文工具区内容。"""
        while (child := self.tool_box.get_first_child()) is not None:
            self.tool_box.remove(child)
        if widget is not None:
            self.tool_box.append(widget)

    def _tool_btn(self, label, action):
        b = Gtk.Button(label=label)
        b.connect("clicked", lambda *_: self.emit("tool-action", action))
        return b

    # 便捷：常见工具栏构造
    def build_writer_tools(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        for label, action in [("加粗", "bold"), ("斜体", "italic"),
                              ("左对齐", "align-left"), ("居中", "align-center"),
                              ("右对齐", "align-right"),
                              ("标题", "style-title"), ("正文", "style-body"),
                              ("查找", "find"), ("替换", "replace")]:
            box.append(self._tool_btn(label, action))
        return box

    def build_sheet_tools(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        for label, action in [("加粗", "bold"), ("合并", "merge"),
                              ("插入行", "ins-row"), ("删除行", "del-row"),
                              ("插入列", "ins-col"), ("删除列", "del-col"),
                              ("求和", "sum"), ("平均", "avg"),
                              ("新建表", "new-sheet"), ("重命名", "rename-sheet")]:
            box.append(self._tool_btn(label, action))
        return box

    def build_slides_tools(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        for label, action in [("新建幻灯片", "add-slide"), ("删除", "del-slide"),
                              ("标题版式", "layout-title"), ("内容版式", "layout-content"),
                              ("上移", "move-up"), ("下移", "move-down"),
                              ("播放", "play")]:
            box.append(self._tool_btn(label, action))
        return box
