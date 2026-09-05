import os
import re
import sys

sys.path.insert(0, "/usr/chindows")
sys.path.insert(0, "/usr/chindows/bai")

from flask import Flask, jsonify, render_template, request

from chindshell import chat as chatmod
from chindshell import flask as csf

from aim.config import ensure_dirs
from aim.agent import list_agents, get_agent, save_agent, delete_agent

app = Flask(__name__)
csf.register(app)

ensure_dirs()

HISTORY_PATH = os.path.join(os.path.expanduser("~"), ".bai", "history.json")

session = chatmod.StreamSession()
state = {"agent": None, "conv_id": None, "pending_newrun": False, "continue_session": False}
tracker = chatmod.ConversationTracker(HISTORY_PATH)

AGENT_FIELDS = ("role", "description", "prompt", "personality", "background", "rules")


def _build_persona(agent):
    p = []
    if agent.get("prompt"):
        p.append(agent["prompt"])
    if agent.get("role"):
        p.append(f"身份：{agent['role']}")
    if agent.get("description"):
        p.append(f"简介：{agent['description']}")
    if agent.get("personality"):
        p.append(f"性格：{agent['personality']}")
    if agent.get("background"):
        p.append(f"背景：{agent['background']}")
    if agent.get("rules"):
        p.append(f"规则：{agent['rules']}")
    return "。".join(p)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/agents")
def api_agents():
    agents = []
    for name, _desc in list_agents():
        a = get_agent(name) or {}
        agents.append({
            "name": name,
            "description": a.get("description", ""),
            "role": a.get("role", ""),
            "prompt": a.get("prompt", ""),
            "personality": a.get("personality", ""),
            "background": a.get("background", ""),
            "rules": a.get("rules", ""),
        })
    return jsonify(agents)


@app.route("/api/agents", methods=["POST"])
def api_save_agent():
    d = request.get_json(force=True) or {}
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "名称必填"})
    data = {k: d.get(k, "") for k in AGENT_FIELDS}
    save_agent(name, {k: v for k, v in data.items() if v})
    return jsonify({"ok": True})


@app.route("/api/agents/<name>/delete", methods=["POST"])
def api_delete_agent(name):
    delete_agent(name)
    return jsonify({"ok": True})


@app.route("/api/select", methods=["POST"])
def api_select():
    d = request.get_json(force=True) or {}
    tracker.save()
    state["agent"] = d.get("agent")
    state["conv_id"] = None
    return jsonify({"ok": True, "conv_id": None})


@app.route("/api/send", methods=["POST"])
def api_send():
    d = request.get_json(force=True) or {}
    msg = (d.get("message") or "").strip()
    if not msg:
        return jsonify({"ok": False, "error": "空消息"})
    if session.running:
        return jsonify({"ok": False, "error": "AI 正在生成中"})
    name = state["agent"]
    if not name:
        return jsonify({"ok": False, "error": "请先在左侧选择角色"})
    agent = get_agent(name) or {}
    if state["conv_id"] is None:
        if state.get("continue_session"):
            # 已 aim change 切换到指定会话 → 用 run 继续该会话
            state["continue_session"] = False
            session.start(["aim", "run", msg])
        else:
            persona = _build_persona(agent)
            full_msg = f"请扮演以下角色：\n{persona}\n\n用户说：{msg}" if persona else msg
            state["pending_newrun"] = True
            session.start(["aim", "newrun", name], stdin_text=full_msg)
    else:
        session.start(["aim", "run", state["conv_id"]], stdin_text=msg)
    tracker.add_user(msg)
    return jsonify({"ok": True})


@app.route("/api/stream")
def api_stream():
    since = int(request.args.get("since", 0) or 0)
    new, done, error, total = session.poll(since)
    if done:
        tracker.record_reply(session.full_text())
        if state["pending_newrun"]:
            state["pending_newrun"] = False
            m = re.search(r"ID: (\w+)", session.full_text())
            if m:
                state["conv_id"] = m.group(1)
    return jsonify({"chunks": new, "done": done, "error": error,
                    "total": total, "conv_id": state["conv_id"]})


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
        chatmod.aim_change_session(session)
        state["continue_session"] = True
    tracker.messages = [{"role": m.get("role", "user"), "content": m.get("content", "")}
                        for m in msgs if (m.get("content") or "").strip()]
    tracker._assistant_pending = False
    tracker._live_index = -1
    return jsonify({"ok": True})


@app.route("/api/history/clear", methods=["POST"])
def api_history_clear():
    tracker.clear()
    return jsonify({"ok": True})
