#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""APS AI — LibreOffice 伴侣桥（UNO socket 连接）

方案：LibreOffice 启动时带 --accept=socket,host=localhost,port=2002
（由 soffice 包装脚本自动注入），APS 伴侣窗口通过该端口直连，
复用 aps.lo.aps_ai / aps.lo.aps_doc 查看/修改当前文档。
"""
import threading
import time

from aps.lo import aps_ai, aps_doc

DEFAULT_PORT = 2002


class LOBridge:
    """连接本机 LibreOffice，操作当前活动文档。"""

    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self._ctx = None
        self._desktop = None
        self._lock = threading.Lock()

    # ---------------- 连接 ----------------
    @property
    def connected(self) -> bool:
        return self._desktop is not None

    def connect(self, timeout: float = 20.0) -> bool:
        """连接 UNO socket；失败则按 timeout 秒重试。"""
        import uno
        try:
            lc = uno.getComponentContext()
            resolver = lc.ServiceManager.createInstanceWithContext(
                "com.sun.star.bridge.UnoUrlResolver", lc)
        except Exception:
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with self._lock:
                    self._ctx = resolver.resolve(
                        f"uno:socket,host=localhost,port={self.port};"
                        "urp;StarOffice.ComponentContext")
                    self._desktop = self._ctx.ServiceManager.createInstanceWithContext(
                        "com.sun.star.frame.Desktop", self._ctx)
                return True
            except Exception:
                time.sleep(0.5)
        return False

    def disconnect(self):
        with self._lock:
            self._desktop = None
            self._ctx = None

    # ---------------- 文档访问 ----------------
    def current_document(self):
        """返回当前打开的 Writer/Calc/Impress 文档，无则返回 None。"""
        if not self._desktop:
            return None
        try:
            docs = self._desktop.getComponents()
            enum = docs.createEnumeration()
            while enum.hasMoreElements():
                d = enum.nextElement()
                if aps_doc.get_doc_type(d) != "unknown":
                    return d
            return None
        except Exception:
            return None

    def doc_type(self) -> str:
        d = self.current_document()
        return aps_doc.get_doc_type(d) if d else "unknown"

    def extract_text(self) -> str:
        """查看：提取当前文档全文。"""
        d = self.current_document()
        if d is None:
            return "（未连接，或 LibreOffice 中没有打开的文档）"
        return aps_ai.extract_document(d)

    def run_action(self, action: str, instruction: str = "") -> str:
        """AI 操作（同步）：summarize / ask / execute。"""
        d = self.current_document()
        if d is None:
            return "未找到打开的文档（请先在 LibreOffice 打开 Writer / Calc / Impress 文档）。"
        return aps_ai.run_action(action, d, instruction)

    def stream_action(self, action: str, instruction: str = "",
                      run: bool = False,
                      on_delta=None, on_done=None, on_error=None):
        """AI 操作（流式）：后台线程调用 aim，结果实时回调。

        run=False → 新对话（aim newrun）；run=True → 继续当前对话（aim run）。
        回调运行在后台线程；UI 侧请用 GLib.idle_add 切回主线程。
        on_delta(line)：每行输出；on_done(result)：完成后；
        on_error(msg)：出错时。
        """
        d = self.current_document()
        if d is None:
            if on_error:
                on_error("未找到打开的文档（请先在 LibreOffice 打开 Writer / Calc / Impress 文档）。")
            return
        prompt = aps_ai.build_action_prompt(action, d, instruction)
        bridge = aps_ai.AimBridge()

        def done(out):
            if action == "execute":
                script = aps_ai.extract_python_script(out)
                if script:
                    # 直接改运行中的文档对象（即时生效）
                    result = aps_ai.run_script_in_doc(d, script)
                    on_done(result if result else "（脚本已执行，无输出）")
                    return
            on_done(out)

        bridge.send(prompt, run=run,
                    on_delta=on_delta, on_done=done, on_error=on_error)

    def ping(self) -> bool:
        """轻量连通性检测（供实时刷新）。"""
        try:
            self.current_document()
            return True
        except Exception:
            return False

    # ---------------- 文档修改原语 ----------------
    def set_writer_text(self, text: str) -> bool:
        """整文替换（仅 Writer）。"""
        d = self.current_document()
        if d is None or aps_doc.get_doc_type(d) != "writer":
            return False
        d.getText().setString(text)
        return True

    def append_writer_text(self, text: str) -> bool:
        d = self.current_document()
        if d is None or aps_doc.get_doc_type(d) != "writer":
            return False
        aps_doc.append_text(d, text)
        return True

    def save(self) -> str:
        """保存当前文档。"""
        d = self.current_document()
        if d is None:
            return "无文档可保存"
        return aps_doc.save(d)
