import os
import sys

sys.path.insert(0, "/usr/chindows")

from flask import Flask, jsonify, render_template, request

from chindshell import chat as chatmod
from chindshell import flask as csf

app = Flask(__name__)
csf.register(app)


def _home():
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_dir
    except Exception:
        return os.path.expanduser("~")


KB_DIR = os.path.join(_home(), "AI知识库")
KB_PROMPT = (
    "AI知识库位于 {kb_dir} 目录，回答问题时请先查阅该目录下的文件"
    "（可用读取/搜索工具浏览），再基于其中的内容作答。\n\n用户问题："
)
HISTORY_PATH = os.path.join(_home(), ".z", "history.json")

session = chatmod.StreamSession()
_mode = {"name": "newrun"}
state = {"conv_rank": None}
tracker = chatmod.ConversationTracker(HISTORY_PATH)

os.makedirs(KB_DIR, exist_ok=True)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/files")
def api_files():
    names = []
    try:
        for n in sorted(os.listdir(KB_DIR)):
            full = os.path.join(KB_DIR, n)
            if os.path.isfile(full) or os.path.isdir(full):
                names.append(n)
    except OSError:
        pass
    return jsonify({"dir": KB_DIR, "files": names})


@app.route("/api/send", methods=["POST"])
def api_send():
    data = request.get_json(force=True) or {}
    msg = (data.get("message") or "").strip()
    if not msg:
        return jsonify({"ok": False, "error": "空消息"})
    if session.running:
        return jsonify({"ok": False, "error": "AI 正在生成中"})
    prompt = KB_PROMPT.format(kb_dir=KB_DIR) + msg
    rank = state.pop("conv_rank", None)
    if rank:
        tracker.add_user(msg)
        session.start(["aim", "run", "--conv", str(rank), prompt])
        return jsonify({"ok": True, "mode": "run"})
    m = _mode["name"]
    if m == "newrun":
        _mode["name"] = "run"
    tracker.add_user(msg)
    session.start(["aim", m, prompt])
    return jsonify({"ok": True, "mode": m})


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
    _mode["name"] = "newrun"
    return jsonify({"ok": True})


@app.route("/api/stop")
def api_stop():
    session.stop()
    return jsonify({"ok": True})


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
        _mode["name"] = "run"  # 后续 aim run --conv <rank> 继续该会话
    tracker.messages = [{"role": m.get("role", "user"), "content": m.get("content", "")}
                        for m in msgs if (m.get("content") or "").strip()]
    tracker._assistant_pending = False
    tracker._live_index = -1
    return jsonify({"ok": True})


@app.route("/api/history/clear", methods=["POST"])
def api_history_clear():
    tracker.clear()
    return jsonify({"ok": True})
