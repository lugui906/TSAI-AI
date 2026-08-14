#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一文档模型：文字 / 表格 / 演示 / PDF 的打开-提取-保存抽象。"""
import os

from aps.core import writer, sheet, slides, pdfview

KINDS = {
    ".docx": "文字文档",
    ".xlsx": "电子表格",
    ".pptx": "演示文稿",
    ".pdf": "PDF 文档",
    ".txt": "纯文本",
    ".md": "Markdown",
}


class Document:
    """一个已打开的文档，按扩展名路由到对应引擎。"""

    def __init__(self, path: str = None, kind: str = "docx"):
        self.path = path
        self.ext = os.path.splitext(path)[1].lower() if path else "." + kind
        self.kind_name = KINDS.get(self.ext, "未知")
        # 引擎对象：writer / sheet / slides / pdf / text
        self.engine = None
        if path:
            self._open(path)
        else:
            self._new(kind)

    # ---------------- 打开 ----------------
    def _open(self, path: str):
        if self.ext == ".docx":
            self.engine = writer.WriterEngine(path)
        elif self.ext == ".xlsx":
            self.engine = sheet.SheetEngine(path)
        elif self.ext == ".pptx":
            self.engine = slides.SlidesEngine(path)
        elif self.ext == ".pdf":
            self.engine = pdfview.PdfEngine(path)
        elif self.ext in (".txt", ".md"):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                self.engine = writer.WriterEngine(path, text=f.read())

    def _new(self, kind: str):
        if kind == "docx":
            self.engine = writer.WriterEngine(None)
        elif kind == "xlsx":
            self.engine = sheet.SheetEngine(None)
        elif kind == "pptx":
            self.engine = slides.SlidesEngine(None)
        elif kind == "pdf":
            self.engine = pdfview.PdfEngine(None)
        elif kind == "txt":
            self.engine = writer.WriterEngine(None, text="")

    # ---------------- 统一接口 ----------------
    @property
    def kind(self) -> str:
        return self.kind_name

    def save(self, path: str = None):
        target = path or self.path
        if target is None:
            raise ValueError("未指定保存路径")
        self.engine.save(target)
        self.path = target
        self.ext = os.path.splitext(target)[1].lower()
        self.kind_name = KINDS.get(self.ext, "未知")

    def to_text(self, limit: int = 6000) -> str:
        """全文提取（视图展示 + AI 上下文）。"""
        txt = self.engine.to_text()
        return txt[:limit]

    def context_snippet(self, limit: int = 4000) -> str:
        """注入给 AI 的文档上下文。"""
        head = self.to_text(limit)
        return (
            f"当前文档路径：{self.path or '（新建未保存）'}\n"
            f"文档类型：{self.kind_name}（{self.ext}）\n"
            f"--- 文档内容摘录（前 {len(head)} 字符）---\n{head}\n"
            f"--- 摘录结束 ---\n"
        )

    def describe(self) -> str:
        return f"{self.kind_name} · {os.path.basename(self.path) if self.path else '新建文档'}"

    def dirty(self) -> bool:
        return self.engine.dirty if hasattr(self.engine, "dirty") else False


def quick_info(path: str) -> dict:
    ext = os.path.splitext(path)[1].lower()
    return {
        "name": os.path.basename(path),
        "path": path,
        "kind": KINDS.get(ext, "未知"),
        "size": os.path.getsize(path),
        "mtime": os.path.getmtime(path),
    }
