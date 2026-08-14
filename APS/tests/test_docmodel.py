"""APS 统一文档模型核心测试：创建→写入→保存→重开→提取。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aps.core import docmodel
from aps.core.docmodel import Document


def _roundtrip(kind, ext):
    """创建、写入、保存、重开一个指定类型的文档。"""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, f"doc.{ext}")
        doc = Document(None, kind=kind)
        assert doc.kind == docmodel.KINDS[f".{ext}"]

        txt = doc.engine.to_text()
        assert isinstance(txt, str)

        doc.save(path)
        assert os.path.exists(path)

        reopened = Document(path)
        assert reopened.ext == f".{ext}"
        assert reopened.path == path
        return reopened


def test_docx_roundtrip():
    doc = _roundtrip("docx", "docx")
    assert "文字" in doc.kind


def test_xlsx_roundtrip():
    doc = _roundtrip("xlsx", "xlsx")
    assert "表格" in doc.kind


def test_pptx_roundtrip():
    doc = _roundtrip("pptx", "pptx")
    assert "演示" in doc.kind


def test_pdf_roundtrip():
    doc = _roundtrip("pdf", "pdf")
    assert "PDF" in doc.kind


def test_txt_roundtrip_and_text():
    doc = _roundtrip("txt", "txt")
    txt = doc.to_text()
    assert isinstance(txt, str)


def test_unknown_extension_kind():
    with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
        f.write(b"hello")
        name = f.name
    try:
        doc = Document(name)
        assert doc.kind == "未知"
    finally:
        os.unlink(name)


def test_context_snippet_contains_path():
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write("内容".encode("utf-8"))
        name = f.name
    try:
        doc = Document(name)
        snippet = doc.context_snippet()
        assert name in snippet
        assert "文档类型" in snippet
    finally:
        os.unlink(name)
