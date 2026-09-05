"""会议录制 HTML套壳 服务 —— hm/hy 共用。

后端逻辑从原 GTK app.py 移植（PipeWire 录制 → 整段 wav → AIM → Markdown 纪要）。
前端轮询 /api/status 获取状态/时长/纪要。
"""
import json
import os
import struct
import sys
import threading
import time


def create_app(basedir, with_history=False, history_file=None, max_history=200):
    sys.path.insert(0, "/usr/chindows")
    sys.path.insert(0, basedir)

    from flask import Flask, jsonify, render_template, request

    from chindshell import flask as csf

    from aim_client.client import AIMClient, AIMError
    from meeting.notify import notify
    from meeting.persistence import MeetingStore
    from meeting.recorder import (
        PipeWireRecorder,
        detect_default_mic_source,
        detect_system_monitor_source,
    )
    from meeting.scheduler import Scheduler
    from meeting.transcribe import Transcriber

    class WavSink:
        RATE = 16000
        CHANNELS = 1
        SAMPWIDTH = 2

        def __init__(self, path):
            self.path = path
            self.rate = self.RATE
            self._data_size = 0
            self._f = open(path, "wb")
            block = self.RATE * self.CHANNELS * self.SAMPWIDTH
            bits = self.SAMPWIDTH * 8
            self._f.write(b"RIFF" + struct.pack("<I", 0) + b"WAVE"
                          + b"fmt " + struct.pack("<IHHIIHH", 16, 1, self.CHANNELS,
                                                  self.RATE, block,
                                                  self.CHANNELS * self.SAMPWIDTH, bits)
                          + b"data" + struct.pack("<I", 0))

        def write(self, data):
            self._f.write(data)
            self._data_size += len(data)

        @property
        def seconds(self):
            return self._data_size / (self.RATE * self.CHANNELS * self.SAMPWIDTH)

        def close(self):
            if not self._f.closed:
                self._f.seek(4)
                self._f.write(struct.pack("<I", 36 + self._data_size))
                self._f.seek(40)
                self._f.write(struct.pack("<I", self._data_size))
                self._f.close()

    app = Flask(__name__,
                template_folder=os.path.join(basedir, "templates"),
                static_folder=os.path.join(basedir, "static"))
    csf.register(app)

    state = {
        "recording": False,
        "status": "就绪。选择「系统内录」或「麦克风」开始。",
        "duration": 0.0,
        "aim": "未调用",
        "path": "",
        "minutes": "",
        "_stop": threading.Event(),
        "_thread": None,
        "_store": None,
        "_lock": threading.Lock(),
    }

    def set_status(t):
        with state["_lock"]:
            state["status"] = t

    def set_aim(t):
        with state["_lock"]:
            state["aim"] = t

    def set_minutes(md, first):
        with state["_lock"]:
            if first:
                state["minutes"] = md
            else:
                state["minutes"] = state["minutes"] + "\n\n" + md if state["minutes"] else md
            state["aim"] = "已更新"

    def load_history():
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
        return []

    def save_history(records):
        if not history_file:
            return
        os.makedirs(os.path.dirname(history_file), exist_ok=True)
        tmp = history_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        os.replace(tmp, history_file)

    def add_history(record):
        records = load_history()
        records.insert(0, record)
        save_history(records[:max_history])

    def clean_previous(seg_dir):
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

    def make_recorder(source, on_pcm):
        if source == "mic":
            mic = detect_default_mic_source()
            if mic:
                return PipeWireRecorder(on_pcm=on_pcm, target=mic, system_internal=False)
            return PipeWireRecorder(on_pcm=on_pcm, system_internal=False)
        monitor = detect_system_monitor_source()
        if monitor:
            return PipeWireRecorder(on_pcm=on_pcm, target=monitor, system_internal=True)
        return PipeWireRecorder(on_pcm=on_pcm, system_internal=True)

    def capture_loop(out_dir, seg_dir, source):
        recorder = None
        store = state["_store"]
        full_path = os.path.join(seg_dir, f"full_{source}.wav")
        try:
            clean_previous(seg_dir)
            scheduler = Scheduler(
                AIMClient(timeout=1800), seg_dir,
                on_result=lambda md, first: set_minutes(md, first),
                on_error=lambda exc: (set_aim("失败"), set_status(f"AIM 调用失败: {exc}")),
                async_mode=True, transcriber=Transcriber())

            sink = WavSink(full_path)

            def on_pcm(data):
                sink.write(data)
                with state["_lock"]:
                    state["duration"] = sink.seconds

            recorder = make_recorder(source, on_pcm)
            tip = ("建议将系统音量静音或用耳机，可避免扬声器声被麦克风拾回。"
                   "内录取的是纯数字输出，不受静音影响。") if source == "internal" else ""
            set_status(f"正在录制「{'系统内录' if source == 'internal' else '麦克风'}」"
                       f"（整段不分段）... 点击「停止并生成纪要」结束。{tip}")
            recorder.start()

            while not state["_stop"].wait(1.0):
                pass

            recorder.stop()
            sink.close()
            set_status("正在将整段录音提交至 AIM...")
            set_aim("调用中")
            try:
                scheduler.submit([full_path])
            except AIMError as exc:
                set_aim("失败")
                set_status(f"AIM 调用失败: {exc}")
            except Exception:
                pass
            scheduler.close()
        except Exception as exc:
            set_status(f"错误: {exc}")
        finally:
            if recorder is not None:
                try:
                    recorder.stop()
                except Exception:
                    pass
            notify("会议纪要已生成", store.path)
            with state["_lock"]:
                state["path"] = store.path
            set_status(f"已保存: {store.path}")
            with state["_lock"]:
                state["recording"] = False

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/status")
    def api_status():
        with state["_lock"]:
            return jsonify({
                "recording": state["recording"],
                "status": state["status"],
                "duration": state["duration"],
                "aim": state["aim"],
                "path": state["path"],
                "minutes": state["minutes"],
            })

    @app.route("/api/start", methods=["POST"])
    def api_start():
        d = request.get_json(force=True) or {}
        source = d.get("source", "internal")
        if source not in ("internal", "mic"):
            source = "internal"
        with state["_lock"]:
            if state["recording"]:
                return jsonify({"ok": False, "error": "正在录制中"})
            state["recording"] = True
            state["_stop"].clear()
            state["duration"] = 0.0
            state["aim"] = "未调用"
            state["minutes"] = ""
            state["path"] = ""
            out_dir = os.path.join(os.getcwd(), "meeting_out")
            seg_dir = os.path.join(os.getcwd(), "meeting_segments")
            os.makedirs(out_dir, exist_ok=True)
            os.makedirs(seg_dir, exist_ok=True)
            state["_store"] = MeetingStore(out_dir)
            state["status"] = "正在初始化采集..."
            state["_thread"] = threading.Thread(
                target=capture_loop, args=(out_dir, seg_dir, source), daemon=True)
            state["_thread"].start()
        return jsonify({"ok": True})

    @app.route("/api/stop", methods=["POST"])
    def api_stop():
        with state["_lock"]:
            if not state["recording"]:
                return jsonify({"ok": False, "error": "未在录制"})
            state["_stop"].set()
            state["status"] = "正在停止并生成最终纪要..."
        return jsonify({"ok": True})

    if with_history:
        @app.route("/api/history")
        def api_history():
            return jsonify(load_history())

        @app.route("/api/history/clear", methods=["POST"])
        def api_history_clear():
            save_history([])
            return jsonify({"ok": True})

    # 在 set_minutes 保存后追加历史（hy）
    if with_history:
        _orig_set_minutes = set_minutes

        def set_minutes(md, first):
            _orig_set_minutes(md, first)
            store = state["_store"]
            if store is not None:
                add_history({
                    "title": store.title,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "path": store.path,
                    "text": md,
                })

    return app
