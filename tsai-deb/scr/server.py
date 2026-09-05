import os
import sys

sys.path.insert(0, "/usr/chindows")

from flask import Flask, jsonify, render_template, request

from chindshell import chat as chatmod
from chindshell import flask as csf

app = Flask(__name__)
csf.register(app)

AIM_BIN = "/usr/bin/aim"
SESSION_FILE = os.path.expanduser("/tmp/doubao-gtk-session.txt")
HISTORY_PATH = os.path.join(os.path.expanduser("~"), ".scr", "history.json")

session = chatmod.StreamSession()
state = {"first": True, "conv_rank": None}
tracker = chatmod.ConversationTracker(HISTORY_PATH)

SYSTEM_PROMPT = """【最高优先级强制铁律（高于所有操作规则）】
0. 对于任何浏览器操作（如填表），请执行“browseros-cli”来了解浏览器的操作方案，因为浏览器不支持常规键鼠操控；
1. 用户下发完整任务，严禁仅执行一步tine工具调用就截断输出，必须持续规划后续操作直到任务全部完成；
2. 所有操作执行完毕、任务受阻、会话结束前，强制输出独立【任务总结】，禁止直接停止生成文本；
3. 仅文字推演操作流程不算完成任务，规划交互动作后必须紧跟对应合法tine工具调用，不能只空谈操作；
4. 收到系统探测消息优先接续任务或输出完整总结，禁止静默停滞、原地等待指令。
你是运行在GNOME Wayland(Linux)上的桌面控制AI，依靠aim调用工具操控桌面。
【执行层级铁律，从上至下强制执行】
1. 解析窗口、按钮、输入框等界面控件，优先使用 tine tree；仅当tine tree无法定位目标文本时，才使用 tine screenshot --ocr。禁止无脑优先截图。
2. 任何界面点击、交互操作执行前，必须先调用界面查询工具(tine tree优先)获取控件ID。严禁凭空猜测位置、坐标、图标进行操作。
3. ❗重要约束：只口头描述想要点击某处，但不调用工具查询界面、不生成合法`tine click`指令，属于严重违规行为，禁止只说话不执行工具调用。
4. 启动图形应用流程：使用系统搜索找到应用 → 点击搜索结果启动应用。
5. tine 不支持直接输入。输入固定流程：wl-copy "文本" → tine key ctrl+v，禁止尝试其它方案。
6. 界面点击只能使用 tine click <ID>；ID必须来自上一轮 tine tree 控件ID 或 screenshot --ocr 的ref_tXXX，严禁编造ID。
7. 页面滚动只能使用 tine key Page_Up / Page_Down。
8. 连续2次界面查询（tree/screenshot）没有界面变化，向用户汇报现状。
## 可用工具清单
1. tine tree
2. tine screenshot --ocr
3. tine click <id>
4. tine key <combo>
5. timeout 1 wl-copy "内容"
## 输出硬性规范
1. 准备调用工具前，可以简短说明意图，但想要操控界面就必须发出对应的工具调用。
2. 禁止无工具调用的纯文字空想操作。
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
"""


def load_session():
    try:
        with open(SESSION_FILE) as f:
            return f.read().strip()
    except OSError:
        return None


def clear_session():
    try:
        os.unlink(SESSION_FILE)
    except OSError:
        pass


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/send", methods=["POST"])
def api_send():
    data = request.get_json(force=True) or {}
    msg = (data.get("message") or "").strip()
    if not msg:
        return jsonify({"ok": False, "error": "空消息"})
    if session.running:
        return jsonify({"ok": False, "error": "AI 正在生成中"})
    rank = state.pop("conv_rank", None)
    if rank:
        tracker.add_user(msg)
        session.start([AIM_BIN, "run", "--conv", str(rank), msg], start_new_session=True)
        state["first"] = False
        return jsonify({"ok": True, "mode": "run"})
    first = state["first"]
    if first:
        full_msg = f"{SYSTEM_PROMPT}\n\n用户指令: {msg}"
        mode = "newrun"
    else:
        full_msg = msg
        mode = "run"
    state["first"] = False
    tracker.add_user(msg)
    session.start([AIM_BIN, mode, full_msg], start_new_session=True)
    return jsonify({"ok": True, "mode": mode})


@app.route("/api/stream")
def api_stream():
    since = int(request.args.get("since", 0) or 0)
    new, done, error, total = session.poll(since)
    if done:
        tracker.record_reply(session.full_text())
    return jsonify({"chunks": new, "done": done, "error": error, "total": total})


@app.route("/api/new", methods=["POST"])
def api_new():
    tracker.save()
    state["first"] = True
    clear_session()
    return jsonify({"ok": True})


@app.route("/api/stop")
def api_stop():
    session.stop()
    return jsonify({"ok": True})


@app.route("/api/state")
def api_state():
    return jsonify({"first": state["first"], "busy": session.running})


@app.route("/api/history")
def api_history():
    return jsonify(tracker.load())


@app.route("/api/history/switch", methods=["POST"])
def api_history_switch():
    d = request.get_json(force=True) or {}
    session = d.get("session")
    msgs = d.get("messages") or []
    if session:
        rank = chatmod.aim_session_to_rank(session)
        state["conv_rank"] = rank if rank else None
        state["first"] = False  # 后续 aim run --conv <rank> 继续该会话
    tracker.messages = [{"role": m.get("role", "user"), "content": m.get("content", "")}
                        for m in msgs if (m.get("content") or "").strip()]
    tracker._assistant_pending = False
    tracker._live_index = -1
    return jsonify({"ok": True})


@app.route("/api/history/clear", methods=["POST"])
def api_history_clear():
    tracker.clear()
    return jsonify({"ok": True})
