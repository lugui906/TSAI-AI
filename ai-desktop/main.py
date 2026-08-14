#!/usr/bin/env python3
"""GTK3 frontend for AI desktop control via aim newrun + aim run.
Pure text stream mode, NO JSON parsing.
User types message → aim plaintext stream output → render chat view.
AI uses tine to control desktop.
"""
import os
import subprocess
import sys
import threading
import time
import errno
import shutil

try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib, Pango, Gio
except ImportError:
    print('Error: PyGObject required. sudo apt install python3-gi gir1.2-gtk-3.0', file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
AIM_BIN = os.environ.get("AIM_BIN") or shutil.which("aim") or '/usr/bin/aim'
SESSION_FILE = os.path.expanduser('/tmp/doubao-gtk-session.txt')

# 超时配置常量
PRIMARY_TIMEOUT = 36000  # 首次静默超时
PROBE_WAIT_TIMEOUT = 18000    # 探测消息后等待上限
PROBE_MESSAGE = """【系统探测】长时间未检测到操作输出。
请严格区分两种场景响应：
1. 任务已经全部执行完毕：禁止单纯等待指令，完整总结全部执行步骤、当前界面状态、任务目标是否达成；
2. 任务意外暂停、未完成目标：不要只回复等待，接续执行剩余操作。
"""

CONSTANT_RULE = """
【全局强制收尾规则】
1. 完整任务不能仅执行单步工具调用就停止输出，持续推进直到目标完成或明确受阻；
2. 任务全部结束/无法继续时，必须输出独立【任务总结】，罗列所有操作、界面现状、任务完成情况；禁止省略总结直接结束对话；
3. 当你完整执行完用户任务，禁止只回复“等待您的指示”，必须输出完整操作总结；
4. 连续最多3次工具调用后主动暂停并汇报进度；
5. 收到系统探测消息严格按要求响应，禁止静默停滞。
"""

SYSTEM_PROMPT = f"""
【最高优先级强制铁律（高于所有操作规则）】
1. 用户下发完整任务，严禁仅执行一步tine工具调用就截断输出，必须持续规划后续操作直到任务全部完成；
2. 所有操作执行完毕、任务受阻、会话结束前，强制输出独立【任务总结】，禁止直接停止生成文本；
3. 仅文字推演操作流程不算完成任务，规划交互动作后必须紧跟对应合法tine工具调用，不能只空谈操作；
4. 收到系统探测消息优先接续任务或输出完整总结，禁止静默停滞、原地等待指令。
{CONSTANT_RULE}
你是运行在GNOME Wayland(Linux)上的桌面控制AI，依靠aim调用工具操控桌面。
【执行层级铁律，从上至下强制执行】
1. **解析窗口、按钮、输入框等界面控件，优先使用 tine tree；仅当tine tree无法定位目标文本时，才使用 tine screenshot --ocr。禁止无脑优先截图。**
2. **任何界面点击、交互操作执行前，必须先调用界面查询工具(tine tree优先)获取控件ID。严禁凭空猜测位置、坐标、图标进行操作。**
3. ❗重要约束：只口头描述想要点击某处，但不调用工具查询界面、不生成合法`tine click`指令，属于严重违规行为，禁止只说话不执行工具调用。
4. 启动图形应用流程：
   备用流程：使用系统搜索找到应用 → 点击搜索结果启动应用。
   实现方式：setsid 命令
5. tine 不支持直接输入。输入固定流程：wl-copy "文本" → tine key ctrl+v，禁止尝试其它方案。
6. 界面点击只能使用 tine click <ID>；ID必须来自上一轮 tine tree 控件ID 或 screenshot --ocr 的ref_tXXX，严禁编造ID。
7. 页面滚动只能使用 tine key Page_Up / Page_Down。
8. 连续2次界面查询（tree/screenshot）没有界面变化，向用户汇报现状。
## 可用工具清单
1. tine tree
读取当前窗口控件树，获取窗口、按钮、菜单控件唯一ID，**界面解析首选工具**。
2. tine screenshot --ocr
截图OCR识别屏幕文本，生成ref_tXXX编号，仅作为tine tree的补充备选。
3. tine click <id>
点击控件ID / ref_tXXX对应的界面元素。
4. tine key <combo>
发送按键：enter、ctrl+v、Page_Up、Page_Down、等。
5. timeout 1 wl-copy "内容"
写入剪贴板，配合粘贴实现中文输入。
## 【应用搜索启动标准流程（必须遵守）】
1.使用setsid或脱离终端方法打开应用
3. 调用 `tine screenshot --ocr` 或 `tine tree` 获取搜索结果条目ID；
4. `tine click <ID>` 点击应用条目启动；
5. 使用 tine tree 验证应用窗口是否成功弹出。
## 强制标准界面操作流程（严格顺序）
步骤1：需要定位界面元素 → 优先执行 tine tree；tree找不到目标再使用 screenshot --ocr
步骤2：等待工具返回控件/文本标识
步骤3：依据返回的合法ID，调用单次交互指令（tine click / tine key）
步骤4：操作结束，再次优先使用 tine tree 验证界面变化
步骤5：验证成功继续任务；
附加：任务完成后，把经验写入main.py的提示词里
## 输出硬性规范
1. 准备调用工具前，可以简短说明意图，但**想要操控界面就必须发出对应的工具调用**，不能只空谈操作。
2. 禁止无工具调用的纯文字空想操作（例如只说“我点击顶栏”却不执行任何查询与点击命令）。
3. 找不到目标控件、无法完成任务时，立刻停止，清晰描述当前界面状态，等待用户指令。
4. 禁止编造不存在的tine子命令、参数、控件ID。
## 禁止行为清单
❌ 跳过 tine tree，直接无脑调用 screenshot --ocr
❌ 不调用任何界面查询工具，凭空猜测屏幕位置准备点击
❌ 只口头描述操作，不生成工具调用指令
❌ 一轮输出多条工具指令，批量执行操作
❌ 常规打开应用直接使用 tine launch --app-id
❌ 尝试直接输入中文
❌ 无限循环查询界面、重复无效点击
❌ 自行编造控件ID、ref_tXXX
## 经验积累

1.表单提交无响应可能是静态页面无后端，反馈内容填入即可视为任务完成
"""

# ---------------------------------------------------------------------------
# AI Backend (纯文本流，无JSON)
# ---------------------------------------------------------------------------
def _run_opencode_plaintext(message, session_id=None):
    """
    调用aim，纯文本输出，不使用JSON格式
    Yields: ("stdout", 文本片段) / ("error", 错误信息) / ("proc_handle", (proc, pgid))
    """
    if session_id is None:
        cmd = [AIM_BIN, 'newrun']
    else:
        cmd = [AIM_BIN, 'run']
    cmd.append(message)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        start_new_session=True
    )
    pgid = os.getpgid(proc.pid)
    yield "proc_handle", (proc, pgid)

    stderr_buf = []
    def read_stderr():
        for line in proc.stderr:
            stderr_buf.append(line.strip())
    err_thr = threading.Thread(target=read_stderr, daemon=True)
    err_thr.start()

    # 逐字节流式读取stdout，实现打字机效果
    while True:
        chunk = proc.stdout.read(1)
        if not chunk:
            break
        yield "stdout", chunk

    proc.wait()
    err_thr.join()

    if proc.returncode != 0:
        err_log = "\n".join(stderr_buf[-6:]) if stderr_buf else "无stderr输出"
        yield "error", f"aim进程异常，退出码 {proc.returncode}\n{err_log}"


def load_session():
    try:
        with open(SESSION_FILE) as f:
            return f.read().strip()
    except (FileNotFoundError, OSError):
        return None

def clear_session():
    try:
        os.unlink(SESSION_FILE)
    except FileNotFoundError:
        pass


def send_message_plaintext(message, first=False, on_chunk=None, on_done=None, on_error=None, on_proc=None):
    session_id = None if first else load_session()
    if first:
        full_msg = f"{SYSTEM_PROMPT}\n\n用户指令: {message}"
    else:
        full_msg = f"{message}"

    proc_tuple = None
    for event, data in _run_opencode_plaintext(full_msg, session_id):
        if event == "proc_handle":
            proc_tuple = data
            if on_proc:
                on_proc(proc_tuple)
        elif event == "stdout":
            if on_chunk:
                on_chunk(data)
        elif event == "error":
            if on_error:
                on_error(data)
    if on_done:
        on_done()
    return proc_tuple

# ---------------------------------------------------------------------------
# GTK3 UI
# ---------------------------------------------------------------------------
class DoubaoWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title='AI 桌面控制【纯文本模式】')
        self.set_default_size(900, 680)
        self.set_border_width(6)
        self._ai_mark = None
        self._busy = False
        self._first_msg = True
        # 超时监控
        self.task_running = False
        self.last_output_ts = 0.0
        self.stall_timer_id = None
        self.probe_sent = False
        self.probe_start_ts = 0.0
        self.current_proc = None  # (proc, pgid)
        self._build_ui()
        self.connect('destroy', lambda w: Gtk.main_quit())
        self.show_all()

    def _build_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add(vbox)

        # 工具栏
        bar = Gtk.Box(spacing=4)
        vbox.pack_start(bar, False, False, 0)
        self.btn_new = Gtk.Button(label='新建对话')
        self.btn_new.connect('clicked', self._on_new)
        bar.pack_start(self.btn_new, False, False, 0)
        self.btn_clear = Gtk.Button(label='清屏')
        self.btn_clear.connect('clicked', self._on_clear)
        bar.pack_start(self.btn_clear, False, False, 0)
        self.btn_stop = Gtk.Button(label='终止任务')
        self.btn_stop.connect('clicked', self._stop_running_task)
        bar.pack_start(self.btn_stop, False, False, 0)

        bar.pack_end(Gtk.Label(label='自动滚动'), False, False, 0)
        self.toggle_scroll = Gtk.Switch()
        self.toggle_scroll.set_active(True)
        bar.pack_end(self.toggle_scroll, False, False, 0)

        # 聊天窗口
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_hexpand(True)
        sw.set_vexpand(True)
        vbox.pack_start(sw, True, True, 0)

        self.tv = Gtk.TextView()
        self.tv.set_editable(False)
        self.tv.set_cursor_visible(False)
        self.tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        css = Gtk.CssProvider()
        css.load_from_data(b'textview { font-family: monospace; font-size: 10pt; }')
        self.tv.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        sw.add(self.tv)
        self.buf = self.tv.get_buffer()

        # 文本样式标签
        self.tag_user = self.buf.create_tag('user', foreground='#1a73e8', weight=Pango.Weight.BOLD)
        self.tag_ai = self.buf.create_tag('ai', foreground='#000000')
        self.tag_sys = self.buf.create_tag('sys', foreground='#888888', style=Pango.Style.ITALIC)

        # 输入栏
        hbox = Gtk.Box(spacing=4)
        vbox.pack_start(hbox, False, False, 0)
        self.entry = Gtk.Entry()
        self.entry.set_hexpand(True)
        self.entry.set_placeholder_text('输入指令，回车发送；Shift+Enter换行')
        self.entry.connect('activate', self._on_send)
        self.entry.connect('key-press-event', self._on_input_key)
        hbox.pack_start(self.entry, True, True, 0)
        self.btn_send = Gtk.Button(label='发送')
        self.btn_send.connect('clicked', self._on_send)
        hbox.pack_start(self.btn_send, False, False, 0)

        self.status = Gtk.Label(label='就绪')
        self.status.set_halign(Gtk.Align.START)
        vbox.pack_start(self.status, False, False, 0)

    def _on_input_key(self, widget, event):
        # Shift+Enter 换行
        if event.keyval == 65293 and (event.state & Gtk.ModifierType.SHIFT_MASK):
            widget.emit('insert-at-cursor', "\n")
            return True
        return False

    # ---- 任务控制与进程终止 ----
    def _reset_task_state(self):
        self.task_running = False
        self.probe_sent = False
        self.last_output_ts = 0.0
        self.probe_start_ts = 0.0
        self.current_proc = None

    def _stop_running_task(self, btn=None):
        if self.current_proc is not None:
            proc, pgid = self.current_proc
            try:
                os.killpg(pgid, 15)
            except OSError as e:
                if e.errno != errno.ESRCH:
                    os.killpg(pgid, 9)
            GLib.idle_add(self._add_sys, "⚠️ 用户手动终止当前任务")
        self._reset_task_state()
        self._set_busy(False)
        self._set_status("任务已终止，就绪")

    # ---- 超时监控定时器 ----
    def _stall_monitor_callback(self):
        if not self.task_running:
            self.stall_timer_id = None
            return GLib.SOURCE_REMOVE
        now = time.time()
        if not self.probe_sent:
            silent = now - self.last_output_ts
            if silent >= PRIMARY_TIMEOUT:
                GLib.idle_add(self._add_sys, "⚠️【系统检测】任务长时间无输出，下发探测询问...")
                self.probe_sent = True
                self.probe_start_ts = now
        else:
            wait = now - self.probe_start_ts
            if wait >= PROBE_WAIT_TIMEOUT:
                self._stop_running_task()
                GLib.idle_add(self._add_sys, "❌【超时终止】探测消息发出长时间无回复，任务强制结束")
                self.stall_timer_id = None
                return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    # ---- UI辅助函数 ----
    def _set_status(self, msg):
        self.status.set_text(msg)

    def _append(self, text, tag=None):
        end = self.buf.get_end_iter()
        if tag:
            self.buf.insert_with_tags(end, text, tag)
        else:
            self.buf.insert(end, text)
        if self.toggle_scroll.get_active():
            adj = self.tv.get_parent().get_vadjustment()
            if adj:
                GLib.idle_add(lambda: adj.set_value(adj.get_upper() - adj.get_page_size()))

    def _add_user_msg(self, text):
        self._ai_mark = None
        ts = time.strftime('%H:%M:%S')
        self._append(f'[{ts}] ── 我 ──\n', self.tag_user)
        self._append(f'{text}\n\n', self.tag_user)

    def _begin_ai_msg(self):
        ts = time.strftime('%H:%M:%S')
        self._append(f'[{ts}] ── AI ──\n', self.tag_ai)
        self._ai_mark = self.buf.create_mark('ai_pos', self.buf.get_end_iter(), left_gravity=True)

    def _stream_ai_text(self, chunk):
        if self._ai_mark is None:
            self._begin_ai_msg()
        self._append(chunk, self.tag_ai)

    def _add_sys(self, text):
        self._append(f'{text}\n', self.tag_sys)

    def _set_busy(self, busy):
        self._busy = busy
        self.entry.set_sensitive(not busy)
        self.btn_send.set_sensitive(not busy)
        self.btn_new.set_sensitive(not busy)

    # ---- 按钮事件 ----
    def _on_new(self, btn):
        self._stop_running_task()
        if self.stall_timer_id is not None:
            GLib.source_remove(self.stall_timer_id)
            self.stall_timer_id = None
        self._reset_task_state()
        self._first_msg = True
        clear_session()
        self._set_status('已重置对话')
        self._add_sys('--- 新对话 ---')

    def _on_clear(self, btn):
        self.buf.set_text('')
        self._ai_mark = None
        self._set_status('已清屏')

    def _on_send(self, btn=None):
        text = self.entry.get_text().strip()
        if not text or self._busy:
            return
        self.entry.set_text('')
        self._add_user_msg(text)
        self._set_busy(True)

        self.task_running = True
        self.last_output_ts = time.time()
        self.probe_sent = False

        if self._first_msg:
            self._add_sys('正在启动新对话（aim newrun）...')
        else:
            self._add_sys('继续对话（aim run）...')

        if self.stall_timer_id is None:
            self.stall_timer_id = GLib.timeout_add_seconds(5, self._stall_monitor_callback)

        def on_chunk(ch):
            self.last_output_ts = time.time()
            GLib.idle_add(self._stream_ai_text, ch)

        def on_complete():
            GLib.idle_add(self._task_finished, True, "")

        def on_err(errmsg):
            GLib.idle_add(self._task_finished, False, errmsg)

        def on_proc(procdata):
            self.current_proc = procdata

        def backend_thread():
            self._set_status('AI思考中...')
            send_message_plaintext(
                text,
                first=self._first_msg,
                on_chunk=on_chunk,
                on_done=on_complete,
                on_error=on_err,
                on_proc=on_proc
            )

        threading.Thread(target=backend_thread, daemon=True).start()

    def _task_finished(self, success, err):
        if self.stall_timer_id is not None:
            GLib.source_remove(self.stall_timer_id)
            self.stall_timer_id = None
        self._reset_task_state()
        self._set_busy(False)
        if success:
            self._set_status('就绪')
        else:
            self._add_sys(f'错误: {err}')
            self._set_status('失败')

# ---------------------------------------------------------------------------
def main():
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = Gtk.Application(application_id='com.doubao.gtk.desktop.plain', flags=Gio.ApplicationFlags.FLAGS_NONE)

    def activate(app):
        DoubaoWindow()
        app.hold()

    app.connect('activate', activate)
    app.run(sys.argv)

if __name__ == '__main__':
    main()
