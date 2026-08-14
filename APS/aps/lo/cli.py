#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""APS AI 外部 CLI — 命令行操作 LibreOffice 当前文档（UNO socket）

用法：
  python -m aps.lo.cli summarize   # 总结当前 LO 文档
  python -m aps.lo.cli ask <问题>
  python -m aps.lo.cli execute <指令>   # AI 通过 aps_doc 原语直接操作文档

文档通过 UNO socket 连接本机 LibreOffice（soffice 包装脚本自动带 --accept 端口 2002）。
"""
import sys

from aps.lo import aps_ai, aps_doc

LO_PORT = 2002


def connect():
    import uno
    localContext = uno.getComponentContext()
    resolver = localContext.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", localContext)
    ctx = resolver.resolve(
        f"uno:socket,host=localhost,port={LO_PORT};urp;StarOffice.ComponentContext")
    smgr = ctx.ServiceManager
    desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
    return desktop


def get_doc(desktop):
    docs = desktop.getComponents()
    enum = docs.createEnumeration()
    while enum.hasMoreElements():
        d = enum.nextElement()
        if (d.supportsService("com.sun.star.text.TextDocument")
                or d.supportsService("com.sun.star.sheet.SpreadsheetDocument")
                or d.supportsService("com.sun.star.presentation.PresentationDocument")):
            return d
    return None


def main():
    if len(sys.argv) < 2:
        print("用法: aps_cli.py <summarize|ask|execute> [内容]")
        sys.exit(1)
    action = sys.argv[1]
    prompt = " ".join(sys.argv[2:]).strip()

    try:
        desktop = connect()
    except Exception as e:
        print(f"无法连接 LibreOffice（{LO_PORT} 端口）：{e}\n"
              "请确认用 APS 启动器打开 LibreOffice（自动带 --accept）。")
        sys.exit(1)

    doc = get_doc(desktop)
    if doc is None:
        print("未找到打开的文档。")
        sys.exit(1)

    if action == "summarize":
        print(aps_ai.run_action("summarize", doc))

    elif action == "ask":
        if not prompt:
            print("请输入问题。")
            sys.exit(1)
        print(aps_ai.run_action("ask", doc, prompt))

    elif action == "execute":
        if not prompt:
            print("请输入操作指令。")
            sys.exit(1)
        print(aps_ai.run_action("execute", doc, prompt))

    else:
        print(f"未知操作: {action}")


if __name__ == "__main__":
    main()
