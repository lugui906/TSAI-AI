"""Task scheduling for the meeting summarization module.

Assembles AIM payloads and drives the session:
  - first segments  -> aim newrun  (create the meeting minutes session)
  - appended chunks -> aim run     (continue the session, incremental update)

In async_mode, submit() only enqueues and returns immediately; AIM calls run
on a dedicated worker thread so slow / queued AIM responses never block the
audio capture pipeline. This is the only module that talks to the AIM client.
"""

from __future__ import annotations

import logging
import os
import queue
import threading

from aim_client.client import AIMClient, AIMError

logger = logging.getLogger("meeting.scheduler")

_SENTINEL = object()

MINUTES_HEADER = """
你是会议纪要助手。下面会逐步收到本次会议的音频片段转写文本文件路径。
请使用"工具/文件读取"能力读取这些 txt 文本，进行要点归纳、说话人区分（
若文本中可推断）、会议纪要整理与行动点提取。首次调用先建立整体会议纪要
（Markdown）。

格式要求（严格遵守）：
- 输出 Markdown
- 包含：标题、日期、参会人（若可推理）、会议纪要正文、## 行动点
- 每个文本片段以文件路径给出，读取每个片段后将其与时俱进合并进纪要
- 除了纪要本身，不要输出其它无关内容

转写文本文件路径目录：{dir}
"""


class Scheduler:
    """Reads segment paths, calls AIM, and reports incremental Markdown."""

    def __init__(self, client: AIMClient, session_dir: str,
                 on_result=None, on_error=None, instruction: str | None = None,
                 async_mode: bool = False, transcriber=None,
                 txt_dir: str | None = None):
        self.client = client
        self.session_dir = session_dir
        self.instruction = instruction or MINUTES_HEADER.format(dir=session_dir)
        self.on_result = on_result
        self.on_error = on_error
        self.async_mode = async_mode
        self.transcriber = transcriber
        self.txt_dir = txt_dir or os.path.join(session_dir, "transcripts")

        self._lead_seen = False
        self._sent_index = 0
        self._worker: threading.Thread | None = None
        self._calls: queue.Queue | None = None

        if self.async_mode:
            self._calls = queue.Queue()
            self._worker = threading.Thread(
                target=self._worker_loop, name="aim-scheduler", daemon=True)
            self._worker.start()

    # --- asynchronous worker ------------------------------------------------
    def _worker_loop(self):
        while True:
            task = self._calls.get()
            if task is _SENTINEL:
                break
            paths, first = task
            try:
                reply = self._call_aim(paths, first)
                if reply and self.on_result:
                    self.on_result(reply, first=first)
            except AIMError as exc:
                logger.error("AIM call failed: %s", exc)
                if self.on_error:
                    self.on_error(exc)
            except Exception as exc:  # noqa: BLE001
                logger.exception("AIM worker error")
                if self.on_error:
                    self.on_error(exc)

    def _call_aim(self, paths: list[str], first: bool) -> str:
        text_paths = self._to_text(paths)
        if first:
            logger.info("calling aim newrun with %d text files", len(text_paths))
            reply = self.client.newrun(self._first_payload(text_paths))
        else:
            logger.info("calling aim run with %d text files", len(text_paths))
            reply = self.client.run(self._continue_payload(text_paths))
        self._sent_index += len(text_paths)
        return reply

    def _to_text(self, paths: list[str]) -> list[str]:
        """Lift each segment wav to a transcript txt path (ASR if needed)."""
        if self.transcriber is None:
            return list(paths)
        return [self.transcriber.transcribe_to(p, self.txt_dir) for p in paths]

    # -- public API ----------------------------------------------------------
    def submit(self, segment_paths: list[str]):
        """Feed newly produced segment files to AIM (newrun then run)."""
        if not segment_paths:
            return
        paths = list(segment_paths)
        if self.async_mode:
            first = not self._lead_seen
            self._lead_seen = True
            self._calls.put((paths, first))
            return

        first = not self._lead_seen
        self._lead_seen = True
        reply = self._call_aim(paths, first)
        if reply and self.on_result:
            self.on_result(reply, first=first)
        return reply

    def close(self):
        """Signal the async worker to stop."""
        if self.async_mode and self._calls is not None:
            self._calls.put(_SENTINEL)

    # -- payloads ------------------------------------------------------------
    def _first_payload(self, paths: list[str]) -> str:
        segs = "\n".join(f"- {p}" for p in paths)
        return (
            f"{self.instruction}\n\n首次转写文本片段：\n{segs}\n\n"
            "请先输出一整份完整 Markdown 会议纪要。"
        )

    def _continue_payload(self, paths: list[str]) -> str:
        segs = "\n".join(f"- {p}" for p in paths)
        return (
            "接续上一会话。新增转写文本片段：\n"
            f"{segs}\n\n"
            "请读取这些新片段并更新会议纪要，只输出增量/更新后的 Markdown，"
            "若任务结束请输出最终完整纪要。"
        )