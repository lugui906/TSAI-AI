import numpy as np
import os
import re
import signal
import subprocess
import threading
import queue
import contextlib
import tempfile
import time
import json
import webrtcvad
from faster_whisper import WhisperModel

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gtk, Gdk, GLib

try:
    import chindows_theme.style as chstyle
except ImportError:
    import os as _os, sys as _sys
    _d = _os.path.dirname(_os.path.abspath(__file__))
    while _d and not _os.path.isdir(_os.path.join(_d, "chindows_theme")):
        _p = _os.path.dirname(_d)
        if _p == _d:
            break
        _d = _p
    if _d:
        _sys.path.insert(0, _d)
    try:
        import chindows_theme.style as chstyle
    except Exception:
        chstyle = None

Gtk.Window.set_default_icon_name("audio-input-microphone")
GLib.set_prgname("org.chindows.ai-voice")

HISTORY_DIR = os.path.expanduser("~/.aai")
HISTORY_FILE = os.path.join(HISTORY_DIR, "history.json")
MAX_HISTORY = 200



# ==========模型路径选择逻辑==========
MODEL_ROOT = "/usr/chindows/aai/share/models"
candidate_models = [
    os.path.join(MODEL_ROOT, "small"),
    os.path.join(MODEL_ROOT, "faster-small"),
    os.path.join(MODEL_ROOT, "base")
]

MODEL_DIR = None
for path in candidate_models:
    if os.path.exists(os.path.join(path, "model.bin")):
        MODEL_DIR = path
        break

if MODEL_DIR is None:
    raise FileNotFoundError("未找到可用faster-whisper模型，请检查 /usr/chindows/aai/share/models")

# 初始化模型
model = WhisperModel(
    MODEL_DIR,
    device="cpu",
    compute_type="int8",
    local_files_only=True
)

SAMPLE_RATE = 16000
CHUNK = 960
VAD_FRAME_SIZE = 480
CHANNELS = 1
VAD_MODE = 3
VAD_SPEECH_FRAMES = 6
VAD_SILENCE_FRAMES = 10
VAD_END_RMS_FRAMES = 5
MIN_AUDIO_LEN = 0.8
MAX_RECORD_SEC = 30.0
TTS_COOLDOWN = 2.0
BLOCKED_PHRASES = ["字幕製作", "字幕制作", "字幕", "貝爾", "贝尔"]

model = WhisperModel(MODEL_DIR, device="cpu", compute_type="int8")
speaking_event = threading.Event()
last_speak_time = 0
last_tts_text = ""
stop_listen_event = threading.Event()
aim_proc_holder = [None]
aim_proc_lock = threading.Lock()


class MicrophoneManager:
    def __init__(self):
        self.sample_rate = SAMPLE_RATE
        self.chunk = CHUNK
        self.vad_frame_size = VAD_FRAME_SIZE
        self.vad_mode = VAD_MODE
        self.vad_speech_frames = VAD_SPEECH_FRAMES
        self.vad_silence_frames = VAD_SILENCE_FRAMES
        self.min_audio_len = MIN_AUDIO_LEN
        
        self.vad = webrtcvad.Vad(self.vad_mode)
        self.sample_width = 2
        self.bytes_per_chunk = self.chunk * self.sample_width
        self.vad_frame_bytes = self.vad_frame_size * self.sample_width
        
        self.devices = []
        self._detect_devices()
        
        self._proc = None
        self.device = self.devices[0] if self.devices else "default"
        print(f"麦克风设备: {self.device}", flush=True)
    
    def _detect_devices(self):
        self.devices = ["plughw:0,0"]
        print(f"设备: {self.devices}", flush=True)
    
    def test_mic(self, test_seconds=2.0):
        print("\n=== 麦克风测试 ===", flush=True)
        for device in self.devices:
            try:
                proc = subprocess.Popen(
                    ["arecord", "-D", device, "-f", "S16_LE", "-r", str(self.sample_rate),
                     "-c", str(CHANNELS), "-t", "raw"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    bufsize=self.bytes_per_chunk
                )
            except:
                continue
            
            try:
                total_data = b''
                deadline = time.time() + test_seconds
                while time.time() < deadline:
                    try:
                        chunk = proc.stdout.read(self.bytes_per_chunk)
                        if chunk:
                            total_data += chunk
                    except:
                        break
                
                proc.terminate()
                proc.wait(timeout=2)
            except:
                proc.kill()
            
            if len(total_data) > 0:
                audio_int = np.frombuffer(total_data, dtype=np.int16)
                rms = np.sqrt(np.mean(audio_int.astype(float)**2))
                status = "✓ 正常" if rms > 50 else "⚠ 音量极低"
                print(f"  [{device}] {status} (RMS={rms:.0f})", flush=True)
                if rms > 50:
                    print(f"  → 使用设备: {device}\n", flush=True)
                    self.device = device
                    return True
            else:
                print(f"  [{device}] ✗ 无数据", flush=True)
        
        print("  ✗ 所有麦克风设备均无法使用", flush=True)
        if self.devices:
            self.device = self.devices[0]
            print(f"  → 强制使用: {self.device}\n", flush=True)
            return True
        return False
    
    def _is_speech(self, data):
        return any(
            self.vad.is_speech(data[i:i+self.vad_frame_bytes], self.sample_rate)
            for i in range(0, len(data), self.vad_frame_bytes)
        )
    
    def record(self):
        if self._proc is not None:
            self._cleanup()
        
        for idx, device in enumerate(self.devices):
            print(f"尝试打开麦克风设备 [{idx+1}/{len(self.devices)}]: {device}", flush=True)
            
            try:
                self._proc = subprocess.Popen(
                    ["arecord", "-D", device, "-f", "S16_LE", "-r", str(self.sample_rate),
                     "-c", str(CHANNELS), "-t", "raw"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    bufsize=self.bytes_per_chunk
                )
            except Exception as e:
                print(f"arecord 启动失败: {e}", flush=True)
                self._cleanup()
                continue
            
            print("麦克风已打开, 等待语音...", flush=True)
            
            frames = []
            speech_count = 0
            silence_count = 0
            started = False
            device_worked = False
            rms_history = []
            
            try:
                record_start = time.time()
                while True:
                    if self._proc is None or speaking_event.is_set() or stop_listen_event.is_set():
                        break
                    
                    if started and time.time() - record_start > MAX_RECORD_SEC:
                        print(f"录音超时({MAX_RECORD_SEC}秒), 强制结束", flush=True)
                        break
                    
                    try:
                        data = self._proc.stdout.read(self.bytes_per_chunk)
                    except Exception as e:
                        print(f"读取音频数据失败: {e}", flush=True)
                        break
                    
                    if len(data) < self.bytes_per_chunk:
                        if self._proc:
                            stderr = self._proc.communicate()[1].decode('utf-8', errors='ignore')
                            if stderr:
                                print(f"arecord 错误输出: {stderr}", flush=True)
                        break
                    
                    if self._is_speech(data):
                        speech_count += 1
                        silence_count = 0
                        if speech_count >= self.vad_speech_frames and not started:
                            audio_int = np.frombuffer(data, dtype=np.int16)
                            rms = np.sqrt(np.mean(audio_int.astype(float)**2))
                            if rms < 200:
                                print(f"忽略低音量语音(RMS={rms:.0f})", flush=True)
                                speech_count = 0
                                continue
                            started = True
                            record_start = time.time()
                            device_worked = True
                            print("检测到语音, 开始录音...", flush=True)
                        if started:
                            audio_int = np.frombuffer(data, dtype=np.int16)
                            rms = np.sqrt(np.mean(audio_int.astype(float)**2))
                            rms_history.append(rms)
                            if len(rms_history) > VAD_END_RMS_FRAMES:
                                rms_history.pop(0)
                            frames.append(data)
                    elif started:
                        frames.append(data)
                        silence_count += 1
                        need_silence = self.vad_silence_frames
                        if len(rms_history) >= VAD_END_RMS_FRAMES:
                            trend = rms_history[-1] - rms_history[0]
                            if trend < -20:
                                need_silence = max(3, need_silence // 2)
                                print(f"  句尾下降(trend={trend:.0f}), 静音阈值={need_silence}", flush=True)
                        if silence_count >= need_silence:
                            print("语音结束", flush=True)
                            break
            finally:
                self._cleanup()
            
            min_frames = int(self.sample_rate / self.chunk * self.min_audio_len + 0.5)
            if len(frames) >= min_frames:
                audio_int = np.frombuffer(b''.join(frames), dtype=np.int16)
                audio = audio_int.astype(np.float32) / 32768.0
                print(f"录音完成, 时长: {len(audio) / self.sample_rate:.2f}秒", flush=True)
                self.device = device
                return audio
            
            if device_worked:
                self.device = device
            
            print(f"设备 {device} 未检测到有效语音, 尝试下一个设备", flush=True)
        
        print("所有设备均无法正常工作", flush=True)
        return None
    
    def _cleanup(self):
        if self._proc is not None:
            try:
                self._proc.stdout.close()
            except:
                pass
            try:
                self._proc.stderr.close()
            except:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=2)
                except Exception:
                    pass
            self._proc = None
    
    def __del__(self):
        self._cleanup()


@contextlib.contextmanager
def silence_alsa():
    old_fd = os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)
    os.close(devnull)
    try:
        yield
    finally:
        os.dup2(old_fd, 2)
        os.close(old_fd)


PW_CAPTURE_ID = None

def _find_pw_capture_id():
    global PW_CAPTURE_ID
    if PW_CAPTURE_ID is not None:
        return PW_CAPTURE_ID
    try:
        r = subprocess.run(["pw-cli", "list-objects", "Node"], capture_output=True, text=True, timeout=5)
        lines = r.stdout.splitlines()
        current_id = None
        has_alsa = False
        for line in lines:
            m = re.match(r'id (\d+),', line.strip())
            if m:
                current_id = m.group(1)
                has_alsa = False
            if 'alsa_input' in line:
                has_alsa = True
            if current_id and 'Audio/Source' in line and has_alsa:
                PW_CAPTURE_ID = current_id
                return PW_CAPTURE_ID
    except:
        pass
    return None

def mute_mic(mute=True):
    sid = _find_pw_capture_id()
    if sid:
        vol = "0.0" if mute else "1.0"
        subprocess.run(["wpctl", "set-volume", sid, vol], capture_output=True, timeout=5)
    else:
        vol = "0%" if mute else "100%"
        subprocess.run(["amixer", "sset", "Capture", vol], capture_output=True, timeout=5)

TTS_VOICE = "zh-CN-XiaoxiaoNeural"
TTS_RATE = "-8%"


def _tts_generate_edge(text, tmp_mp3):
    import asyncio
    import edge_tts
    async def _run():
        communicate = edge_tts.Communicate(text, TTS_VOICE, rate=TTS_RATE)
        await communicate.save(tmp_mp3)
    asyncio.run(_run())


def speak(text):
    global last_tts_text
    last_tts_text = text
    def _speak():
        global last_speak_time
        is_first = True
        tmp_mp3 = ""
        tmp_wav = ""
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            tmp_mp3 = f.name
        tmp_wav = tmp_mp3.replace('.mp3', '.wav')
        try:
            speaking_event.set()
            try:
                _tts_generate_edge(text, tmp_mp3)
                subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-i", tmp_mp3, tmp_wav],
                    capture_output=True, timeout=60
                )
                player = ["aplay", tmp_wav]
            except Exception as e:
                print(f"edge-tts 失败, 回退到 espeak-ng: {e}")
                tmp_wav = tmp_mp3.replace('.mp3', '.wav')
                subprocess.run(
                    ["espeak-ng", "-v", "cmn", "-s", "150", text, "-w", tmp_wav],
                    capture_output=True, timeout=30
                )
                player = ["aplay", tmp_wav]
            mute_mic(True)
            subprocess.run(player, capture_output=True, timeout=60)
        except Exception as e:
            print(f"TTS error: {e}")
        finally:
            print("TTS播放完毕, 静默2秒...", flush=True)
            time.sleep(2.0)
            mute_mic(False)
            last_speak_time = time.time()
            speaking_event.clear()
            print("解锁麦克风", flush=True)
            for p in (tmp_mp3, tmp_wav):
                try:
                    os.unlink(p)
                except:
                    pass
    threading.Thread(target=_speak, daemon=True).start()


def load_history():
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def save_history(records):
    os.makedirs(HISTORY_DIR, exist_ok=True)
    tmp = HISTORY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    os.replace(tmp, HISTORY_FILE)


def add_history(record):
    records = load_history()
    records.insert(0, record)
    save_history(records[:MAX_HISTORY])


class AimWindow:
    def __init__(self, application):
        self.window = Gtk.ApplicationWindow(application=application, title="语音助手")
        self.window.set_default_size(500, 350)

        hb = Gtk.HeaderBar()
        hb.set_show_title_buttons(True)
        hb.set_title_widget(Gtk.Label(label="语音助手"))
        self.window.set_titlebar(hb)

        self.stop_btn = Gtk.Button(label="停止")
        self.stop_btn.connect("clicked", self._on_stop)
        hb.pack_start(self.stop_btn)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        root.set_margin_top(4)
        root.set_margin_bottom(4)
        root.set_margin_start(4)
        root.set_margin_end(4)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)

        self.textview = Gtk.TextView()
        self.textview.set_editable(False)
        self.textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.textbuffer = self.textview.get_buffer()
        scrolled.set_child(self.textview)
        root.append(scrolled)

        self.history_expander = Gtk.Expander(label="📜 历史记录")
        self.history_expander.connect("activate", self._on_history_toggle)
        history_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        history_box.set_margin_start(4)
        history_box.set_margin_end(4)
        history_box.set_margin_bottom(4)
        self.history_list = Gtk.ListBox()
        self.history_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.history_list.connect("row-activated", self._on_history_activated)
        history_scroll = Gtk.ScrolledWindow()
        history_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        history_scroll.set_min_content_height(100)
        history_scroll.set_max_content_height(220)
        history_scroll.set_child(self.history_list)
        history_box.append(history_scroll)
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        clear_btn = Gtk.Button(label="清空历史")
        clear_btn.connect("clicked", self._on_history_clear)
        btn_row.append(clear_btn)
        new_btn = Gtk.Button(label="新对话")
        new_btn.connect("clicked", self._on_history_new)
        btn_row.append(new_btn)
        history_box.append(btn_row)
        self.history_expander.set_child(history_box)
        root.append(self.history_expander)

        self.window.set_child(root)

        self.output_queue = queue.Queue()
        self.shown = False
        self.history_messages = []
        GLib.timeout_add(100, self.poll_output)
        self._refresh_history_ui()

    def _on_history_toggle(self, expander):
        if expander.get_expanded():
            self._refresh_history_ui()

    def _on_stop(self, _btn):
        global stop_listen_event, speaking_event
        if not stop_listen_event.is_set():
            stop_listen_event.set()
            with aim_proc_lock:
                proc = aim_proc_holder[0]
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass
                with aim_proc_lock:
                    aim_proc_holder[0] = None
            speaking_event.clear()
            self.stop_btn.set_label("继续")
            self.append("\n--- 已停止 ---\n")
            if hasattr(self, "status_label"):
                self.status_label.set_text("已停止监听")
        else:
            stop_listen_event.clear()
            self.stop_btn.set_label("停止")
            self.append("\n--- 已继续监听 ---\n")
            if hasattr(self, "status_label"):
                self.status_label.set_text("正在监听...")
    def _refresh_history_ui(self):
        self.history_list.remove_all()
        records = load_history()
        if not records:
            row = Gtk.ListBoxRow()
            lbl = Gtk.Label(label="暂无历史记录")
            lbl.set_halign(Gtk.Align.START)
            lbl.set_margin_start(8); lbl.set_margin_end(8); lbl.set_margin_top(4); lbl.set_margin_bottom(4)
            lbl.add_css_class("dim-label")
            row.set_child(lbl)
            self.history_list.append(row)
            return
        for rec in records:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_margin_start(8); box.set_margin_end(8); box.set_margin_top(4); box.set_margin_bottom(4)
            ts = rec.get("time", "")
            title = rec.get("title", "对话")
            lbl = Gtk.Label(label=f"{ts}  {title}")
            lbl.set_halign(Gtk.Align.START)
            lbl.set_ellipsize(True)
            lbl.set_hexpand(True)
            box.append(lbl)
            row.set_child(box)
            row.record = rec
            self.history_list.append(row)

    def _on_history_activated(self, _listbox, row):
        rec = getattr(row, "record", None)
        if not rec:
            return
        buf = ""
        for msg in rec.get("messages", []):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                buf += f"你：{content}\n\nAI："
            else:
                buf += content + "\n\n---\n"
        self.textbuffer.set_text(buf)
        self.history_messages = list(rec.get("messages", []))

    def _on_history_clear(self, _btn):
        save_history([])
        self._refresh_history_ui()

    def _on_history_new(self, _btn):
        self.textbuffer.set_text("")
        self.history_messages = []

    def save_current(self):
        if not self.history_messages:
            return
        title = ""
        for msg in self.history_messages:
            if msg.get("role") == "user":
                title = msg["content"][:40]
                break
        if not title:
            title = "对话"
        add_history({
            "title": title,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "messages": self.history_messages,
        })
        self.history_messages = []

    def poll_output(self):
        try:
            while True:
                text = self.output_queue.get_nowait()
                end_iter = self.textbuffer.get_end_iter()
                self.textbuffer.insert(end_iter, text)
                adj = self.textview.get_parent().get_vadjustment()
                if adj:
                    adj.set_value(adj.get_upper() - adj.get_page_size())
        except queue.Empty:
            pass
        return True

    def append(self, text):
        self.output_queue.put(text)

    def show_window(self):
        self.window.present()


def run_aim(prompt_text, window):
    window.append(f"你：{prompt_text}\n\nAI：")
    window.history_messages.append({"role": "user", "content": prompt_text})

    proc = subprocess.Popen(
        ["aim", "run", prompt_text],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    with aim_proc_lock:
        aim_proc_holder[0] = proc

    accumulated = []
    for line in iter(proc.stdout.readline, ""):
        if stop_listen_event.is_set():
            break
        window.append(line)
        accumulated.append(line)

    proc.wait()
    with aim_proc_lock:
        if aim_proc_holder[0] is proc:
            aim_proc_holder[0] = None
    window.append("\n---\n")

    reply = "".join(accumulated).strip()
    if reply and not stop_listen_event.is_set():
        window.history_messages.append({"role": "assistant", "content": reply})
        window.save_current()
        speak(reply)
    else:
        window.append("\n")
        speaking_event.clear()


def audio_loop(window):
    mic = MicrophoneManager()
    print("音频循环已启动", flush=True)
    
    while True:
        if stop_listen_event.is_set():
            with aim_proc_lock:
                proc = aim_proc_holder[0]
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass
                with aim_proc_lock:
                    aim_proc_holder[0] = None
            speaking_event.clear()
            time.sleep(0.3)
            continue

        if speaking_event.is_set():
            time.sleep(0.3)
            continue

        if time.time() - last_speak_time < TTS_COOLDOWN:
            time.sleep(0.3)
            continue

        print("等待语音...", flush=True)
        try:
            audio = mic.record()
        except Exception as e:
            print(f"录音错误: {e}", flush=True)
            time.sleep(1)
            continue
        if audio is None:
            print("录音为空或失败, 重试", flush=True)
            continue

        print("录音结束, 锁定麦克风", flush=True)
        speaking_event.set()

        segments, _ = model.transcribe(audio, language="zh", beam_size=5)
        full_text = "".join(seg.text for seg in segments).strip()

        print(f"识别: {full_text}", flush=True)

        if not full_text:
            print("解锁麦克风: 空文本", flush=True)
            speaking_event.clear()
            continue

        if any(p in full_text for p in BLOCKED_PHRASES):
            print(f"忽略: 过滤掉 '{full_text}'", flush=True)
            speaking_event.clear()
            continue

        if last_tts_text and len(full_text) > 3:
            common = len(set(full_text) & set(last_tts_text))
            if common / max(len(set(full_text)), 1) > 0.7:
                print(f"忽略: TTS回声 '{full_text}'", flush=True)
                speaking_event.clear()
                continue

        print("调用 aim, 锁定麦克风...", flush=True)
        run_aim(full_text, window)
        print("aim 返回, 麦克风仍锁定(等待TTS播放完成)", flush=True)


def main():
    if chstyle:
        chstyle.apply_gtk4()
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    print(f"WebRTC VAD 模式={VAD_MODE}, 开始监听 (faster-whisper small)", flush=True)

    app = Gtk.Application(application_id="org.chindows.ai-voice")
    state = {"window": None}

    def activate(application):
        if state["window"] is None:
            win = AimWindow(application)
            win.show_window()
            state["window"] = win
            t = threading.Thread(target=audio_loop, args=(win,), daemon=True)
            t.start()
        else:
            state["window"].window.present()

    app.connect("activate", activate)
    app.run(None)


if __name__ == "__main__":
    main()
