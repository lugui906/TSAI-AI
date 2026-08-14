#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""APS AI — LibreOffice 伴侣的 AI 操作层（客户端侧）

职责：
  1. 提取 LO 当前文档内容（Writer 全文 / Calc 单元格 / Impress 文本，经 UNO socket）
  2. 调用 aim CLI（AIM 中间件，复用共享 AimBridge）
  3. 从 AIM 输出提取/执行 AI 脚本（复用 aps_doc 原语，安全操作文档）

被 LOBridge 与 aps.lo.cli 共同使用。
"""
import os

from aps.ai.aim import AimBridge, strip_ansi  # noqa: F401

SYSTEM_CORE_READ = (
    "你是 APS 的 AI 文档工程师。基于提供的文档内容回答：结论先行，简洁中文。"
    "文档含图片时图片本身无法读取，基于文字回答即可。"
    "严禁修改、删除、覆盖任何文件或本程序自身代码（含提示词脚本）。"
)

SYSTEM_CORE_EXEC = (
    "你是 APS 的 AI 文档工程师。你要修改用户当前打开的 LibreOffice 文档。\n"
    "\n"
    "【文档对象】脚本的全局变量 document = 用户当前打开的 LibreOffice 文档（UNO 对象）。\n"
    "\n"
   
    "【保存前置要求（强制）】\n"
    "1. 在动手修改之前，必须先检查文档是否已保存到磁盘。\n"
    "2. 若用户尚未保存（document_path 为空或文件不存在），你必须拒绝操作+**先明确告知用户**：请先保存文档"
    "3.aps_docx库在'你的工作目录的上层目录的/aps/lo/aps_docx下'"
    
    "3. 只有确认文档已保存到磁盘后，才允许继续执行修改操作。\n"
    "\n"
    "【操作流程：优先磁盘操作】\n"
    "1. 确认文档已保存后，优先使用 python-docx / openpyxl / python-pptx / odfpy 等第三方库"
    "直接读取并修改磁盘上的文件。进行精准修改：不要整篇覆盖、不要丢失图片。\n"
    "2. 修改完成后，用 aps_doc.reload(document) 刷新用户当前打开的文档，让改动即时显示。\n"
    "3. 仅在第三方库无法满足需求（如特殊格式、复杂排版）时，才回退用内置的 aps_doc 原语"
    "直接操作 document 对象。\n"
    "\n"
    "【文件位置】\n"
    "document_path = 文件路径；步骤：确认已保存 → 用 python-pptx/docx/openpyxl 改文件 → aps_doc.reload(document)。\n"
    "\n"
    "【操作规则】\n"
    "1. 操作方式：优先磁盘文件操作（确认已保存 → 第三方库精准修改 → 重载刷新）。\n"
    ""
    "3. 执行完成后在代码块外用一两句中文说明改了什么。\n"
    "4. 【硬性禁令】严禁修改、覆盖、删除、新建任何与本程序运行相关的文件，"
    "包括：提示词脚本（aps_ai.py / aps_doc.py / bridge.py / main.py 等）、"
    "/opt/aps 或项目目录下的任何 .py/.sh 文件、配置文件与启动脚本。"
    "你只能操作 document 指向的当前文档（或经 document_path 作文件兜底时该文档文件）。\n"
)

def extract_python_script(out: str) -> str:
    """从 AIM 输出中提取第一个 ```python 代码块。"""
    import re
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", out, re.S)
    return m.group(1).strip() if m else ""


def _protected_dirs() -> set:
    """本程序自身目录（禁止 AI 脚本修改）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))  # aps/lo → 项目根
    return {os.path.realpath(root), os.path.realpath("/opt/aps")}


def _is_protected(path, protected) -> bool:
    try:
        rp = os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))
    except Exception:
        return False
    return any(rp == base or rp.startswith(base + os.sep) for base in protected)


def run_script_in_doc(document, script: str, extra_env=None) -> str:
    """在当前 LO 文档上下文中执行 AI 生成的脚本（注入 aps_doc 原语 + 自保护）。

    extra_env 可注入 XSCRIPTCONTEXT / uno 等（APS.py 菜单入口使用）。
    """
    import builtins
    import contextlib
    import io
    import traceback

    import sys
    import os as _os

    from aps.lo import aps_doc
    # 让 AI 脚本里的 `import aps_doc` 也能解析到注入模块（不依赖包路径）
    sys.modules.setdefault("aps_doc", aps_doc)
    env = {"document": document, "aps_doc": aps_doc,
           "document_path": aps_doc.document_path(document)}
    if extra_env:
        env.update(extra_env)

    # ---- 禁令加固：保护本程序自身文件，AI 脚本无法改写 ----
    protected = _protected_dirs()
    real_open = builtins.open

    def _guarded_open(file, mode="r", *a, **k):
        if isinstance(file, str) and set(mode) & set("wax+"):
            if _is_protected(file, protected):
                raise PermissionError(f"[禁令] 禁止修改受保护文件：{file}")
        return real_open(file, mode, *a, **k)

    env["__builtins__"] = dict(vars(builtins))
    env["__builtins__"]["open"] = _guarded_open

    # 临时保护 os 破坏性操作（remove/unlink/rename/replace/rmdir）
    _os_saved = {}
    for _fn in ("remove", "unlink", "rename", "replace", "rmdir"):
        if hasattr(_os, _fn):
            _orig = getattr(_os, _fn)

            def _make(_fn=_fn, _orig=_orig):
                def _g(path, *a, **k):
                    if _is_protected(path, protected):
                        raise PermissionError(f"[禁令] 禁止修改受保护文件：{path}")
                    return _orig(path, *a, **k)
                return _g

            _os_saved[_fn] = _orig
            setattr(_os, _fn, _make())

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            try:
                exec(compile(script, "<aps_ai_script>", "exec"), env)  # noqa: S102
                return buf.getvalue()
            except Exception as e:  # noqa: BLE001
                return f"执行出错：{e}\n{traceback.format_exc()[-600:]}"
    finally:
        for _fn, _orig in _os_saved.items():
            setattr(_os, _fn, _orig)


DOC_TYPE_CONTEXT = {
    "writer": "LibreOffice Writer 文字文档",
    "calc": "LibreOffice Calc 电子表格",
    "impress": "LibreOffice Impress 演示文稿",
}


def doc_type_context(doc_type: str) -> str:
    return DOC_TYPE_CONTEXT.get(doc_type, "LibreOffice 文档")


def build_action_prompt(action: str, document, instruction: str = "") -> str:
    """构建某个 AI 动作的完整提示词。

    execute 直接修改当前打开的文档（UNO document 对象，即时生效）；
    document_path 仅作复杂排版/特殊库能力的文件兜底。
    """
    from aps.lo import aps_doc

    if action == "summarize":
        content = extract_document(document)[:6000]
        return SYSTEM_CORE_READ + (
            "\n\n--- 文档内容 ---\n" + content + "\n--- 结束 ---\n\n"
            "请总结当前文档的核心内容，分点列出，并给出关键信息。")
    if action == "ask":
        content = extract_document(document)[:6000]
        return SYSTEM_CORE_READ + (
            "\n\n--- 文档内容 ---\n" + content + "\n--- 结束 ---\n\n"
            f"请基于当前文档内容回答问题：{instruction}")
    # execute：直接修改当前打开的文档（UNO document 对象，即时生效）
    path = aps_doc.document_path(document)
    file_hint = (
        f"\n文档文件路径：{path}（复杂排版需文件兜底时才保存后改文件再重载）"
        if path else
        "\n（当前文档尚未保存到磁盘，只能内存内操作 document 对象，无法使用文件兜底）")
    return SYSTEM_CORE_EXEC + f"\n\n帮我修改当前文档，修改：{instruction}" + file_hint


def run_action(action: str, document, instruction: str = "",
               extra_env=None) -> str:
    """统一 AI 动作：同步执行，返回结果文本。

    action: summarize（总结）| ask（问答）| execute（自由操作）
    """
    if action not in ("summarize", "ask", "execute"):
        return f"未知操作：{action}"

    prompt = build_action_prompt(action, document, instruction)
    out = AimBridge().send_sync(prompt)
    if action == "execute":
        script = extract_python_script(out)
        if script:
            # 直接改运行中的文档对象（即时生效），不走文件轮转
            return run_script_in_doc(document, script, extra_env=extra_env)
    return out


def apply_file_script(document, script: str, extra_env=None) -> str:
    """执行 AI 的"命令行操作文件"脚本：先保存→跑脚本→重新载入。"""
    from aps.lo import aps_doc
    save_msg = aps_doc.save(document)
    result = run_script_in_doc(document, script, extra_env=extra_env)
    reload_msg = aps_doc.reload(document)
    return (f"{save_msg}\n{result}\n{reload_msg}" if result else
            f"{save_msg}\n（脚本无输出）\n{reload_msg}")


# ---------------------------------------------------------------------------
# UNO 文档提取/应用（在 LO Python 环境内运行）
# ---------------------------------------------------------------------------
def extract_document(document) -> str:
    """从 UNO document 提取文本内容（对图片/复杂形状容错）。"""
    try:
        if hasattr(document, "getText"):          # Writer
            txt = document.getText().getString() or ""
            imgs = 0
            try:
                from com.sun.star.text import XTextGraphicObjectsSupplier
                sup = document.queryInterface(XTextGraphicObjectsSupplier)
                if sup:
                    imgs = sup.getGraphicObjects().getCount()
            except Exception:
                pass
            if imgs and not txt.strip():
                return f"（文档含 {imgs} 张图片，无文字内容）"
            return txt
        if hasattr(document, "Sheets"):           # Calc
            lines = []
            sheets = document.Sheets
            for i in range(sheets.getCount()):
                sheet = sheets.getByIndex(i)
                lines.append(f"## 工作表：{sheet.Name}")
                used = sheet.getCellRangeByPosition(0, 0, 30, 100)
                try:
                    data = used.getDataArray()
                    for row in data:
                        vals = [str(v) for v in row if v is not None]
                        if any(v.strip() for v in vals):
                            lines.append(" | ".join(vals))
                except Exception:
                    pass
            return "\n".join(lines)
        if hasattr(document, "getDrawPages"):     # Impress/Draw
            lines = []
            pages = document.getDrawPages()
            for i in range(pages.getCount()):
                page = pages.getByIndex(i)
                lines.append(f"## 第 {i + 1} 页")
                imgs = 0
                for shape in page:
                    try:
                        if shape.supportsService("com.sun.star.drawing.Text"):
                            t = shape.getString()
                            if t:
                                lines.append(t)
                        elif shape.supportsService(
                                "com.sun.star.drawing.GraphicObjectShape"):
                            imgs += 1
                    except Exception:
                        pass
                if imgs:
                    lines.append(f"（本页含 {imgs} 张图片）")
            return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return f"（提取失败：{e}）"
    return ""


def insert_text(document, text: str, append: bool = True):
    """向 Writer 文档插入/追加文本。"""
    doc_text = document.getText()
    if append:
        cursor = doc_text.getEnd()
    else:
        cursor = doc_text.getStart()
    doc_text.insertString(cursor, text, False)
