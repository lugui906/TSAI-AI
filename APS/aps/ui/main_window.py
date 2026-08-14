#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主窗口：Ribbon + 视图 Stack + AI 面板 + 状态栏。"""

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from aps.core.docmodel import Document, KINDS
from aps.ui.ribbon import Ribbon
from aps.ui.writer_view import WriterView
from aps.ui.sheet_view import SheetView
from aps.ui.slides_view import SlidesView
from aps.ui.pdf_view import PdfView
from aps.ui.ai_panel import AiPanel

# 扩展名 -> 视图键（单一来源，_mount_doc 与 _on_switch_view 共用）
EXT_VIEW = {
    "writer": [".docx", ".txt", ".md"],
    "sheet": [".xlsx"],
    "slides": [".pptx"],
    "pdf": [".pdf"],
}


def view_key_for(ext: str) -> str:
    for key, exts in EXT_VIEW.items():
        if ext in exts:
            return key
    return "writer"


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, application=None):
        super().__init__(application=application, title="APS · AI 原生办公套件")
        self.set_default_size(1440, 860)

        self.doc = None
        self.current_view_key = "writer"

        # ---------------- 顶部 ----------------
        hb = Gtk.HeaderBar()
        self.title_label = Gtk.Label(label="APS — AI 原生办公套件（对标 WPS）")
        self.title_label.add_css_class("title")
        hb.set_title_widget(self.title_label)
        self.set_titlebar(hb)

        self.ribbon = Ribbon()
        self.ribbon.connect("new-doc", self._on_new_doc)
        self.ribbon.connect("open-doc", self._on_open_doc)
        self.ribbon.connect("save-doc", self._on_save_doc)
        self.ribbon.connect("save-as", self._on_save_as)
        self.ribbon.connect("switch-view", self._on_switch_view)
        self.ribbon.connect("tool-action", self._on_tool_action)

        # ---------------- 主体 ----------------
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.append(self.ribbon)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.writer_view = WriterView()
        self.sheet_view = SheetView()
        self.slides_view = SlidesView()
        self.pdf_view = PdfView()
        self.stack.add_named(self.writer_view, "writer")
        self.stack.add_named(self.sheet_view, "sheet")
        self.stack.add_named(self.slides_view, "slides")
        self.stack.add_named(self.pdf_view, "pdf")
        paned.set_start_child(self.stack)

        self.ai_panel = AiPanel()
        paned.set_end_child(self.ai_panel)
        paned.set_position(1000)

        root.append(paned)

        # ---------------- 状态栏 ----------------
        self.status_label = Gtk.Label(label="就绪", xalign=0)
        self.status_label.add_css_class("dim-label")
        root.append(self.status_label)

        self.set_child(root)

        # 默认打开一个新文字文档
        self._new_doc("docx")
        self._set_status("欢迎使用 APS 🥬 打开或新建文档，右侧 AI 可操作一切")

    # ================================================================
    # 文档管理
    # ================================================================
    def _new_doc(self, kind: str):
        if self.doc and self._confirm_unsaved() is False:
            return
        self.doc = Document(None, kind)
        self._mount_doc()

    def _open_path(self, path: str):
        if self.doc and self._confirm_unsaved() is False:
            return
        try:
            self.doc = Document(path)
        except Exception as e:  # noqa: BLE001
            self._set_status(f"打开失败：{e}")
            return
        self._mount_doc()
        self._set_status(f"已打开：{path}")

    def _mount_doc(self):
        """把当前 Document 挂到对应视图。"""
        key = view_key_for(self.doc.ext)
        self.current_view_key = key
        self.stack.set_visible_child_name(key)
        self.ribbon.set_view(key)
        self._set_tools(key)

        if key == "writer":
            self.writer_view.engine = self.doc.engine
            self.writer_view._load_engine()
        elif key == "sheet":
            self.sheet_view.engine = self.doc.engine
            self.sheet_view.cur_r = self.sheet_view.cur_c = 0
            self.sheet_view._render_sheet_bar()
            self.sheet_view._render_grid()
        elif key == "slides":
            self.slides_view.engine = self.doc.engine
            self.slides_view._render_thumbs()
            self.slides_view._load_active()
        elif key == "pdf":
            self.pdf_view.engine = self.doc.engine
            self.pdf_view.page = 0
            self.pdf_view._show_page()

        self.ai_panel.set_document(self.doc)
        self.title_label.set_text(self.doc.describe())

    def _set_tools(self, key: str):
        if key == "writer":
            self.ribbon.set_tools(self.ribbon.build_writer_tools())
        elif key == "sheet":
            self.ribbon.set_tools(self.ribbon.build_sheet_tools())
        elif key == "slides":
            self.ribbon.set_tools(self.ribbon.build_slides_tools())
        else:
            self.ribbon.set_tools(None)

    def _confirm_unsaved(self):
        # 简化：有未保存更改时直接继续（后续可加对话框）
        return True

    # ================================================================
    # 事件
    # ================================================================
    def _on_new_doc(self, ribbon, kind):
        self._new_doc(kind)

    def _on_open_doc(self, *_):
        dlg = Gtk.FileDialog()
        filt = Gtk.FileFilter()
        filt.set_name("文档")
        for ext in KINDS:
            filt.add_pattern(f"*{ext}")
        dlg.set_default_filter(filt)
        dlg.open(self, None, self._on_open_done)

    def _on_open_done(self, dlg, result):
        try:
            file = dlg.open_finish(result)
        except Exception:  # noqa: BLE001
            return
        self._open_path(file.get_path())

    def _on_save_doc(self, *_):
        if self.doc is None:
            return
        if self.doc.path:
            self._sync_views()
            try:
                self.doc.save(self.doc.path)
                self._set_status(f"已保存：{self.doc.path}")
            except Exception as e:  # noqa: BLE001
                self._set_status(f"保存失败：{e}")
        else:
            self._on_save_as()

    def _on_save_as(self, *_):
        if self.doc is None:
            return
        dlg = Gtk.FileDialog()
        dlg.set_initial_name(f"未命名{self.doc.ext}")
        dlg.save(self, None, self._on_save_done)

    def _on_save_done(self, dlg, result):
        try:
            file = dlg.save_finish(result)
        except Exception:  # noqa: BLE001
            return
        self._sync_views()
        try:
            self.doc.save(file.get_path())
            self.title_label.set_text(self.doc.describe())
            self._set_status(f"已保存：{file.get_path()}")
        except Exception as e:  # noqa: BLE001
            self._set_status(f"保存失败：{e}")

    def _sync_views(self):
        if self.current_view_key == "writer":
            self.writer_view.sync_to_engine()
        elif self.current_view_key == "sheet":
            self.sheet_view._save_current_cell()
        elif self.current_view_key == "slides":
            self.slides_view._on_body_changed()

    def _on_switch_view(self, ribbon, key):
        # 仅当当前文档类型匹配时切换；否则提示
        if self.doc is None:
            return
        ext = self.doc.ext
        if ext not in EXT_VIEW.get(key, []):
            self._set_status(f"当前文档（{ext}）不适用 {key} 视图")
            # 恢复
            self.ribbon.set_view(self.current_view_key)
            return
        self.current_view_key = key
        self.stack.set_visible_child_name(key)
        self._set_tools(key)

    def _on_tool_action(self, ribbon, action):
        view = {"writer": self.writer_view, "sheet": self.sheet_view,
                "slides": self.slides_view}.get(self.current_view_key)
        if view and hasattr(view, "action"):
            try:
                view.action(action)
            except Exception as e:  # noqa: BLE001
                self._set_status(f"操作失败：{e}")

    def _set_status(self, text: str):
        self.status_label.set_text(text)
