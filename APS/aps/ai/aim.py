#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIM 桥 — 子进程调用 aim CLI（同步 / 异步、流式、可取消）

单一实现，供 GTK 桌面套件与 LibreOffice 扩展共用：
  - 桌面套件：`from aps.ai.aim import AimBridge`
  - LO 扩展：build_oxt.sh 会把本文件复制进 scripts/pythonpath/aim.py

本模块只依赖标准库，不依赖 GTK / UNO，可在任何 Python 环境运行。
"""
import re
import subprocess
import threading

AIM_BIN = "/usr/bin/aim"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


class AimBridge:
    """封装 aim CLI。send() 在后台线程运行，通过回调回传输出。"""

    def __init__(self, aim_bin: str = AIM_BIN):
        self.aim_bin = aim_bin
        self._proc = None
        self._lock = threading.Lock()

    @property
    def busy(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ---------------- 同步 ----------------
    def send_sync(self, prompt: str, run: bool = False, timeout: int = 240) -> str:
        """同步调用（供 UI 线程之外的场景使用）。返回 AIM 文本输出。

        run=False → aim newrun（新对话第一问）；run=True → aim run（继续当前对话）。
        """
        cmd = [self.aim_bin, "run" if run else "newrun", prompt]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
        self._proc = proc
        out = []
        try:
            for line in proc.stdout:
                out.append(strip_ansi(line.rstrip("\n")))
            proc.wait(timeout=timeout)
        except Exception:  # noqa: BLE001
            proc.kill()
        finally:
            self._proc = None
        return "\n".join(out)

    # ---------------- 异步 ----------------
    def send(self, prompt: str, run: bool = False,
             on_delta=None, on_done=None, on_error=None) -> threading.Thread:
        """异步发送完整提示词。回调在调用线程（建议 GTK 主线程）通过 idle_add 触发。

        run=False → aim newrun（新对话第一问）；run=True → aim run（继续当前对话）。
        """
        cmd = [self.aim_bin, "run" if run else "newrun", prompt]

        def worker():
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, bufsize=1)
                self._proc = proc
                buf = []
                for line in proc.stdout:
                    line = strip_ansi(line.rstrip("\n"))
                    if not line.strip():
                        continue
                    buf.append(line)
                    if on_delta:
                        on_delta(line)
                proc.wait()
                if on_done:
                    on_done("\n".join(buf))
            except Exception as e:  # noqa: BLE001
                if on_error:
                    on_error(str(e))
            finally:
                self._proc = None

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        return t

    def cancel(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
            except Exception:  # noqa: BLE001
                pass
