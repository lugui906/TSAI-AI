#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""APS 文档操作原语 — AI 安全操作 LibreOffice 文档的受限接口

AI 生成的脚本只能调用这里的函数（不要直接写复杂 UNO 代码）。
每个函数都有边界检查，确保"安全地完成目标"。
"""

# ---------------- Writer 文字 ----------------
def get_text(document) -> str:
    return document.getText().getString()


def append_text(document, text: str):
    doc_text = document.getText()
    doc_text.insertString(doc_text.getEnd(), text, False)


def _hex_to_long(color) -> int:
    if isinstance(color, int):
        return color
    s = str(color).lstrip("#")
    try:
        return int(s, 16)
    except ValueError:
        return 0


def set_paragraph_style(document, index: int, text=None, bold=None, italic=None,
                        size=None, color=None, align=None) -> bool:
    """就地编辑第 index 段（从 0 开始）：改文本 + 格式（加粗/斜体/字号/颜色/对齐）。

    只改目标段落，不动其他内容与图片。color 为 "#RRGGBB" 或 0xRRGGBB。
    """
    import uno
    paras = document.getText().createEnumeration()
    i = 0
    while paras.hasMoreElements():
        p = paras.nextElement()
        if i == index:
            if text is not None:
                p.setString(str(text))
            props = p.queryInterface(
                uno.getTypeByName("com.sun.star.beans.XPropertySet"))
            if props is None:
                return False
            if bold is not None:
                props.setPropertyValue("CharWeight", 150 if bold else 100)
            if italic is not None:
                props.setPropertyValue("CharPosture", 2 if italic else 0)
            if size is not None:
                props.setPropertyValue("CharHeight", float(size))
            if color is not None:
                props.setPropertyValue("CharColor", _hex_to_long(color))
            if align is not None:
                props.setPropertyValue(
                    "ParaAdjust",
                    {"left": 0, "center": 1, "right": 2, "justify": 3}.get(align, 0))
            return True
        i += 1
    return False


def insert_at_cursor(document, text: str):
    cur = document.getCurrentController().getViewCursor()
    document.getText().insertString(cur, text, False)


def replace_text(document, old: str, new: str, all_occ: bool = True):
    """安全替换：找不到时不报错，返回替换次数。"""
    count = 0
    doc_text = document.getText()
    try:
        searcher = document.createSearchDescriptor()
        searcher.SearchString = old
        searcher.SearchAll = all_occ
        found = document.findAll(searcher)
        for i in range(found.getCount()):
            found.getByIndex(i).setString(new)
            count += 1
        return count
    except Exception:
        # 兜底：字符串整体替换（保留段落结构）
        whole = doc_text.getString()
        if old not in whole:
            return 0
        doc_text.setString(whole.replace(old, new) if all_occ else whole.replace(old, new, 1))
        return whole.count(old)


def set_paragraph_text(document, index: int, text: str):
    """按段落序号替换整段文本（index 从 0 开始）。"""
    paras = document.getText().createEnumeration()
    i = 0
    while paras.hasMoreElements():
        p = paras.nextElement()
        if i == index:
            p.setString(text)
            return True
        i += 1
    return False


def get_font_size(document, index: int = 0) -> float:
    """读取某段落（默认第 1 段）当前字号（磅），失败返回 0。"""
    paras = document.getText().createEnumeration()
    i = 0
    while paras.hasMoreElements():
        p = paras.nextElement()
        if i == index:
            try:
                return p.CharHeight
            except Exception:
                return 0
        i += 1
    return 0


def set_font_size(document, size: float, index: int = None):
    """设置全部（index 为 None）或某个段落（index 从 0 起）的字号（磅）。"""
    paras = document.getText().createEnumeration()
    i = 0
    count = 0
    while paras.hasMoreElements():
        p = paras.nextElement()
        if index is not None and i != index:
            i += 1
            continue
        try:
            p.CharHeight = size
            count += 1
        except Exception:
            pass
        i += 1
        if index is not None:
            break
    return count


# ---------------- Calc 表格 ----------------
def get_cell(document, row: int, col: int, sheet: int = 0):
    return document.Sheets.getByIndex(sheet).getCellByPosition(col, row).getString()


def set_cell(document, row: int, col: int, value, sheet: int = 0):
    cell = document.Sheets.getByIndex(sheet).getCellByPosition(col, row)
    if isinstance(value, (int, float)):
        cell.setValue(value)
    else:
        cell.setString(str(value))


def set_cell_formula(document, row: int, col: int, formula: str, sheet: int = 0):
    cell = document.Sheets.getByIndex(sheet).getCellByPosition(col, row)
    cell.setFormula(formula)


def set_cell_style(document, row: int, col: int, text=None, bold=None, size=None,
                   color=None, align=None, sheet: int = 0) -> bool:
    """就地编辑单元格：改值 + 格式（加粗/字号/颜色/对齐）。"""
    import uno
    cell = document.Sheets.getByIndex(sheet).getCellByPosition(col, row)
    if text is not None:
        if isinstance(text, (int, float)):
            cell.setValue(text)
        else:
            cell.setString(str(text))
    props = cell.queryInterface(uno.getTypeByName("com.sun.star.beans.XPropertySet"))
    if props is None:
        return False
    if bold is not None:
        props.setPropertyValue("CharWeight", 150 if bold else 100)
    if size is not None:
        props.setPropertyValue("CharHeight", float(size))
    if color is not None:
        props.setPropertyValue("CharColor", _hex_to_long(color))
    if align is not None:
        props.setPropertyValue(
            "HoriJustify",
            {"left": 0, "center": 1, "right": 2, "justify": 3}.get(align, 0))
    return True


def sheet_names(document) -> list:
    sheets = document.Sheets
    return [sheets.getByIndex(i).Name for i in range(sheets.getCount())]


# ---------------- Impress 演示 ----------------
def get_slides(document):
    pages = document.getDrawPages()
    result = []
    for i in range(pages.getCount()):
        texts = []
        for shape in pages.getByIndex(i):
            try:
                if shape.supportsService("com.sun.star.drawing.Text"):
                    texts.append(shape.getString())
            except Exception:
                pass
        result.append((i, "\n".join(texts)))
    return result


def set_slide_title(document, slide_idx: int, title: str):
    page = document.getDrawPages().getByIndex(slide_idx)
    for shape in page:
        try:
            if shape.supportsService("com.sun.star.presentation.TitleTextShape"):
                shape.getText().setString(title)
                return True
        except Exception:
            pass
    return False


def add_slide_text(document, slide_idx: int, text: str,
                   x: int = 0, y: int = 0, w: int = 20000, h: int = 10000) -> bool:
    """新增一个文字形状到指定页并写入文本。

    注意：必须先 add 到页面再设置文本（shape.setString 在 add 前会丢失）。
    """
    import uno
    page = document.getDrawPages().getByIndex(slide_idx)
    shape = document.createInstance("com.sun.star.drawing.TextShape")
    shape.setSize(uno.createUnoStruct("com.sun.star.awt.Size", int(w), int(h)))
    if x or y:
        shape.setPosition(uno.createUnoStruct("com.sun.star.awt.Point", int(x), int(y)))
    page.add(shape)
    shape.getText().setString(str(text))
    return True


def set_slide_text_style(document, slide_idx: int, shape_idx: int = None,
                         text=None, bold=None, size=None, color=None,
                         align=None) -> bool:
    """就地编辑某页的一个文字形状：改文本 + 格式。

    shape_idx 缺省时取第一个文字形状。
    """
    import uno
    page = document.getDrawPages().getByIndex(slide_idx)
    shapes = list(page)
    target = None
    if shape_idx is None:
        for shape in shapes:
            try:
                if shape.supportsService("com.sun.star.drawing.Text"):
                    target = shape
                    break
            except Exception:
                pass
    elif shape_idx < len(shapes):
        target = shapes[shape_idx]
    if target is None:
        return False
    if text is not None:
        target.getText().setString(str(text))
    props = target.queryInterface(uno.getTypeByName("com.sun.star.beans.XPropertySet"))
    if props is not None:
        if bold is not None:
            props.setPropertyValue("CharWeight", 150 if bold else 100)
        if size is not None:
            props.setPropertyValue("CharHeight", float(size))
        if color is not None:
            props.setPropertyValue("CharColor", _hex_to_long(color))
        if align is not None:
            props.setPropertyValue(
                "ParaAdjust",
                {"left": 0, "center": 1, "right": 2, "justify": 3}.get(align, 0))
    return True


# ---------------- 通用 ----------------
def save(document, path: str = None):
    """保存；path 为空则就地保存（失败时静默，文档在内存中不受影响）。"""
    try:
        if path:
            document.storeToURL(path, ())
        else:
            document.store()
        return "已保存"
    except Exception:
        return "（就地保存不可用，请手动保存；修改已在内存中生效）"


def document_path(document):
    """当前文档的系统文件路径（供外部库如 python-pptx 直接修改），未保存则返回 None。"""
    try:
        url = document.getURL()
    except Exception:
        return None
    if not url:
        return None
    if url.startswith("file://"):
        import urllib.parse
        return urllib.parse.unquote(url[7:])
    return url


def reload(document):
    """从磁盘重新载入当前文档（外部库改完文件后调用，让 LibreOffice 显示最新内容）。"""
    import uno
    try:
        frame = document.getCurrentController().getFrame()
        ctx = uno.getComponentContext()
        helper = ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.DispatchHelper", ctx)
        helper.executeDispatch(frame, ".uno:Reload", "", 0, ())
        return "已重新载入文件"
    except Exception as e:
        return f"重新载入失败：{e}"


def get_doc_type(document) -> str:
    if document.supportsService("com.sun.star.text.TextDocument"):
        return "writer"
    if document.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
        return "calc"
    if document.supportsService("com.sun.star.presentation.PresentationDocument"):
        return "impress"
    return "unknown"
