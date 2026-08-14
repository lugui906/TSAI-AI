#!/usr/bin/env python3
"""GTK3 front-end for the TSAI-OS meeting summarizer.

Runs the existing pipeline (PipeWire capture -> single full wav -> AIM
newrun/run -> Markdown minutes) behind a desktop interface. Capture and AIM
calls run on a worker thread; UI updates are marshalled to the GTK main loop
via GLib.idle_add.

Recording is continuous (NO VAD segmentation — the whole meeting is one wav
so the AIM summarizer sees full context) and only stops when the user
explicitly presses「停止并生成纪要」or closes the window.
"""

from __future__ import annotations

import argparse
import gi
import logging
import os
import struct
import sys
import threading

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from aim_client.client import AIMClient, AIMError  # noqa: E402
from meeting.notify import notify  # noqa: E402
from meeting.persistence import MeetingStore  # noqa: E402
from meeting.recorder import (  # noqa: E402
    PipeWireRecorder,
    detect_default_mic_source,
    detect_system_monitor_source,
)
from meeting.scheduler import Scheduler  # noqa: E402
from meeting.transcribe import Transcriber  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("meeting.gui")

class WavSink:
    RATE = 16000
    CHANNELS = 1
    SAMPWIDTH = 2          # bytes per sample

    def __init__(self, path: str, rate: int = RATE):
        self.path = path
        self.rate = rate
        self._data_size = 0
        self._f = open(path, "wb")
        block = rate * self.CHANNELS * self.SAMPWIDTH
        bits = self.SAMPWIDTH * 8          # ← 16-bit!
        self._f.write(b"RIFF" + struct.pack("<I", 0) + b"WAVE"
                      + b"fmt " + struct.pack("<IHHIIHH", 16, 1, self.CHANNELS,
                                              rate, block,
                                              self.CHANNELS * self.SAMPWIDTH,
                                              bits)   # ← 传 16 而不是 2
                      + b"data" + struct.pack("<I", 0))

    def write(self, data: bytes):
        self._f.write(data)
        self._data_size += len(data)

    @property
    def seconds(self) -> float:
        return self._data_size / (self.rate * self.CHANNELS * self.SAMPWIDTH)

    def close(self):
        if not self._f.closed:
            self._f.seek(4)
            self._f.write(struct.pack("<I", 36 + self._data_size))
            self._f.seek(40)
            self._f.write(struct.pack("<I", self._data_size))
            self._f.close()

class MeetingApp:
    def __init__(self, args):
        self.args = args
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._store = None
        self._aim_submitted = False
        self._build_ui()
        self.window.connect("destroy", self._on_destroy)

    # ------------------------------------------------------------------
    def _build_ui(self):
        self.window = Gtk.Window(title="TSAI-OS 会议概括")
        self.window.set_default_size(740, 540)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.set_margin_top(10)
        vbox.set_margin_bottom(10)
        vbox.set_margin_start(10)
        vbox.set_margin_end(10)
        self.window.add(vbox)

        # toolbar
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        vbox.pack_start(toolbar, False, False, 0)

        self.start_internal_btn = Gtk.Button(label="开始录制会议（系统内录）")
        self.start_internal_btn.connect("clicked",
                                        lambda _: self._on_start("internal"))
        toolbar.pack_start(self.start_internal_btn, False, False, 0)

        self.start_mic_btn = Gtk.Button(label="开始录制会议（麦克风）")
        self.start_mic_btn.connect("clicked", lambda _: self._on_start("mic"))
        toolbar.pack_start(self.start_mic_btn, False, False, 0)

        self.stop_btn = Gtk.Button(label="停止并生成纪要")
        self.stop_btn.set_sensitive(False)
        self.stop_btn.connect("clicked", self._on_stop)
        toolbar.pack_start(self.stop_btn, False, False, 0)

        self.out_entry = Gtk.Entry()
        self.out_entry.set_text(self.args.out)
        self.out_entry.set_placeholder_text("纪要输出目录")
        toolbar.pack_start(self.out_entry, True, True, 0)

        # status + stats
        self.status = Gtk.Label(label="就绪。选择「系统内录」或「麦克风」开始。")
        self.status.set_xalign(0)
        vbox.pack_start(self.status, False, False, 0)

        stats = Gtk.Box(spacing=12)
        self.stat_duration = Gtk.Label(label="录音时长: 00:00")
        self.stat_aim = Gtk.Label(label="AIM: 未调用")
        self.stat_path = Gtk.Label(label="")
        self.stat_path.set_xalign(0)
        stats.pack_start(self.stat_duration, False, False, 0)
        stats.pack_start(self.stat_aim, False, False, 0)
        stats.pack_start(self.stat_path, True, True, 0)
        vbox.pack_start(stats, False, False, 0)

        # minutes view
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.textview = Gtk.TextView()
        self.textview.set_editable(False)
        self.textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scroller.add(self.textview)
        vbox.pack_start(scroller, True, True, 0)
        self.textbuf = self.textview.get_buffer()

    # ------------------------------------------------------------------
    def _on_start(self, source: str = "internal", _node=None):
        # prevent starting while a previous session is still running
        if self._thread is not None and self._thread.is_alive():
            self.set_status("上一个会话仍在运行，请先停止。")
            return

        out_dir = self.out_entry.get_text().strip() or self.args.out
        seg_dir = self.args.seg
        os.makedirs(seg_dir, exist_ok=True)
        os.makedirs(out_dir, exist_ok=True)

        self._stop.clear()
        self.start_internal_btn.set_sensitive(False)
        self.start_mic_btn.set_sensitive(False)
        self.stop_btn.set_sensitive(True)
        self.textbuf.set_text("")
        self.stat_duration.set_text("录音时长: 00:00")
        self.stat_aim.set_text("AIM: 未调用")
        self.set_status("正在初始化采集...")

        self._store = MeetingStore(out_dir)
        self._thread = threading.Thread(
            target=self._capture_loop,
            args=(out_dir, seg_dir, source), daemon=True)
        self._thread.start()

    def _on_stop(self, _node=None):
        """User manually stops: just set the event; never block the main loop.

        The worker thread notices the event, submits the full recording to
        AIM and restores the UI via GLib.idle_add.
        """
        if self._thread is None or not self._thread.is_alive():
            return
        self.set_status("正在停止并生成最终纪要...")
        self.stop_btn.set_sensitive(False)
        self._stop.set()

    def _on_destroy(self, _widget=None):
        """Window closed: if still recording, trigger stop and wait briefly."""
        if self._thread is not None and self._thread.is_alive():
            self._stop.set()
            self._thread.join(timeout=30)
        Gtk.main_quit()

    # ------------------------------------------------------------------
    def _capture_loop(self, out_dir, seg_dir, source):
        recorder = None
        store = self._store
        full_path = os.path.join(seg_dir, f"full_{source}.wav")
        try:
            self._clean_previous(seg_dir)
            scheduler = Scheduler(
                AIMClient(timeout=self.args.timeout), seg_dir,
                on_result=lambda md, first: self._handle_result(md, first),
                on_error=lambda exc: self._handle_aim_error(exc),
                async_mode=True, transcriber=Transcriber())
            assert store is not None

            sink = WavSink(full_path)

            def on_pcm(data: bytes):
                sink.write(data)
                GLib.idle_add(self._update_duration, sink.seconds)

            recorder = self._make_recorder(source, on_pcm)
            tip = ("建议将系统音量静音或用耳机，可避免扬声器声被麦克风拾回。"
                   "内录取的是纯数字输出，不受静音影响。") if source == "internal" else ""
            GLib.idle_add(self.set_status,
                          f"正在录制「{'系统内录' if source == 'internal' else '麦克风'}」"
                          f"（整段不分段）... 点击「停止并生成纪要」结束。{tip}")
            recorder.start()

            # record indefinitely until the user presses Stop
            while not self._stop.wait(1.0):
                pass

            recorder.stop()
            sink.close()
            GLib.idle_add(self.set_status, "正在将整段录音提交至 AIM...")
            GLib.idle_add(self.mark_aim_calling)
            try:
                scheduler.submit([full_path])
            except AIMError as exc:
                logger.error("AIM 调用失败: %s", exc)
                GLib.idle_add(self.mark_aim_error)
                GLib.idle_add(self.set_status, f"AIM 调用失败: {exc}")
            except Exception as exc:  # noqa: BLE001
                logger.exception("scheduler error: %s", exc)
            scheduler.close()
        except Exception as exc:  # noqa: BLE001
            logger.exception("capture loop error: %s", exc)
            GLib.idle_add(self.set_status, f"错误: {exc}")
        finally:
            if recorder is not None:
                recorder.stop()
            GLib.idle_add(notify, "会议纪要已生成", store.path)
            GLib.idle_add(self.stat_path.set_text, store.path)
            GLib.idle_add(self.set_status, f"已保存: {store.path}")
            GLib.idle_add(self._restore_buttons)

    def _update_duration(self, seconds: float):
        """Run on the GTK thread: refresh the recorded-duration label."""
        m, s = divmod(int(seconds), 60)
        self.stat_duration.set_text(f"录音时长: {m:02d}:{s:02d}")

    def _make_recorder(self, source: str, on_pcm):
        """Build a recorder for the chosen source.

        - "internal": the system output monitor (records what the speakers
          play, e.g. a remote meeting/video).
        - "mic": the default microphone input.
        """
        if source == "mic":
            mic = detect_default_mic_source()
            if mic:
                logger.info("recording from microphone %s", mic)
                return PipeWireRecorder(on_pcm=on_pcm, target=mic,
                                        system_internal=False)
            logger.warning("no mic source found; using default source")
            return PipeWireRecorder(on_pcm=on_pcm, system_internal=False)
        monitor = detect_system_monitor_source()
        if monitor:
            logger.info("recording system internal audio from %s", monitor)
            return PipeWireRecorder(on_pcm=on_pcm, target=monitor,
                                    system_internal=True)
        logger.warning("no monitor source found; using default source")
        return PipeWireRecorder(on_pcm=on_pcm, system_internal=True)

    def _handle_result(self, md: str, first: bool):
        GLib.idle_add(self._persist_and_append, md, first)

    def _handle_aim_error(self, exc: Exception):
        GLib.idle_add(self.mark_aim_error)
        GLib.idle_add(self.set_status, f"AIM 调用失败: {exc}")

    def _persist_and_append(self, md: str, first: bool):
        if self._store is not None:
            self._store.save(md, first=first)
            self.stat_path.set_text(self._store.path)
        self.append_minutes_ui(md, first)

    @staticmethod
    def _clean_previous(seg_dir):
        """Delete stale recordings and transcripts before a fresh capture."""
        for name in os.listdir(seg_dir):
            p = os.path.join(seg_dir, name)
            if os.path.isfile(p) and name.lower().endswith(".wav"):
                os.remove(p)
        txt_dir = os.path.join(seg_dir, "transcripts")
        if os.path.isdir(txt_dir):
            for name in os.listdir(txt_dir):
                p = os.path.join(txt_dir, name)
                if os.path.isfile(p) and name.lower().endswith(".txt"):
                    os.remove(p)

    # -- UI callbacks (run on the GTK thread) ---------------------------
    def set_status(self, text):
        self.status.set_text(text)

    def mark_aim_calling(self):
        self._aim_submitted = True
        self.stat_aim.set_text("AIM: 调用中")

    def mark_aim_error(self):
        self.stat_aim.set_text("AIM: 失败")

    def append_minutes_ui(self, text: str, first: bool):
        if first:
            self.textbuf.set_text(text)
        else:
            self.textbuf.insert(self.textbuf.get_end_iter(), "\n\n" + text)
        self.stat_aim.set_text("AIM: 已更新")

    def _restore_buttons(self):
        self.start_internal_btn.set_sensitive(True)
        self.start_mic_btn.set_sensitive(True)
        self.stop_btn.set_sensitive(False)

def main(argv=None):
    parser = argparse.ArgumentParser(description="TSAI-OS 会议概括 GTK3 界面")
    parser.add_argument("--out", default="meeting_out", help="纪要输出目录")
    parser.add_argument("--seg", default="meeting_segments", help="录音文件目录")
    parser.add_argument("--target", default=None,
                        help="PipeWire 节点名称/id（覆盖麦克风源选择）")
    parser.add_argument("--timeout", type=float, default=1800, help="AIM 超时(秒)")
    args = parser.parse_args(argv)

    MeetingApp(args).window.show_all()
    Gtk.main()
    return 0

if __name__ == "__main__":
    sys.exit(main())
