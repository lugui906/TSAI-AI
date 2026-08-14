#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 文档工程师 — 按文档类型组装提示词 + 快捷命令。"""

# 文档类型 -> 操作约束
TYPE_RULES = {
    "docx": (
        "目标文档是 Word 文字文档（.docx）。涉及修改/创建时用 python-docx；"
        "新建文档默认保存到 ~/Documents。"
    ),
    "xlsx": (
        "目标文档是 Excel 电子表格（.xlsx）。涉及修改/创建时用 openpyxl；"
        "注意保留原有工作表结构与数据。"
    ),
    "pptx": (
        "目标文档是 PowerPoint 演示文稿（.pptx）。涉及修改/创建时用 python-pptx；"
        "生成演示文稿至少 3 页，标题页 + 内容页结构清晰。"
    ),
    "pdf": (
        "目标文档是 PDF。阅读用 pypdf 提取文本；生成/重排用 reportlab。"
    ),
    "txt": "目标文档是纯文本，直接读写即可。",
}

SYSTEM_CORE = (
    "你是 APS（AI 原生办公套件，对标 WPS）内置的 AI 文档工程师，通过 AIM 中间件执行任务。\n"
    "工作方式：\n"
    "1. 需要创建/修改文档时：编写完整 Python 脚本（python-pptx / openpyxl / python-docx / reportlab / pypdf），"
    "写入临时文件后用 `python3 <脚本>` 执行；脚本必须 try/except 包裹并打印执行结果。\n"
    "2. 需要读取/分析文档时：先读文件再回答，结论先行，简洁中文。\n"
    "3. 文件路径中出现 ~ 时先展开；保存路径默认与用户文档同目录，新建文档默认 ~/Documents。\n"
    "4. 执行完成后明确告知：改了什么 / 生成在哪里 / 下一步可以做什么。\n"
)


def build_prompt(user_prompt: str, doc_type: str = "docx",
                 doc_context: str = None, extra: str = None) -> str:
    """组装完整提示词。"""
    parts = [SYSTEM_CORE]
    rule = TYPE_RULES.get(doc_type, TYPE_RULES["txt"])
    parts.append(f"当前文档类型：{doc_type}。{rule}")
    if doc_context:
        parts.append(doc_context)
    if extra:
        parts.append(extra)
    parts.append(f"用户指令：{user_prompt}")
    return "\n\n".join(parts)


# 快捷命令模板
QUICK_CMDS = {
    "生成PPT": "基于当前内容，生成一份专业的演示文稿（python-pptx，至少 3 页），保存到 ~/Documents/，完成后告诉我文件路径。",
    "生成Word": "基于当前内容，生成一份排版规范的 Word 文档（标题 + 正文），保存到 ~/Documents/。",
    "生成Excel": "把当前内容整理成 Excel 表格（多列，带表头），保存到 ~/Documents/。",
    "总结": "请总结当前文档的核心内容，分点列出，并给出关键数据。",
    "改写": "请重写当前文档，使表达更专业流畅，保持原意不变，然后保存修改。",
    "分析": "请深入分析当前文档：结构、优点、问题、改进建议。",
    "问答": "请基于当前文档内容回答我的问题。",
    "翻译": "请把当前文档翻译成英文（中文内容）/中文（英文内容），保持格式。",
}
