import subprocess
import uuid
import sys
import os
import json
import time
import threading
from datetime import datetime
from flask import Flask, request, jsonify, Response, render_template

app = Flask(__name__)
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")
SCHEDULES_FILE = os.path.join(DATA_DIR, "schedules.json")
lock = threading.Lock()

# ---------------------- JSON持久化（修复跨盘替换问题） ----------------------
def load_json(path):
    if not os.path.exists(path):
        return {}
    with lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with lock:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # 优先尝试原子替换，失败则覆盖
        try:
            os.replace(tmp, path)
        except OSError:
            import shutil
            shutil.move(tmp, path)

sessions = load_json(SESSIONS_FILE)
schedules = load_json(SCHEDULES_FILE)

def save_sessions():
    save_json(SESSIONS_FILE, sessions)

def save_schedules():
    save_json(SCHEDULES_FILE, schedules)

# ---------------------- 会话工作目录 ----------------------
def session_workdir(sid):
    d = os.path.join(DATA_DIR, "workdir", sid)
    os.makedirs(d, exist_ok=True)
    return d

def get_workdir(sid):
    s = sessions.get(sid)
    if s and s.get("workdir"):
        return s["workdir"]
    return session_workdir(sid)

# ---------------------- OCR模块 ----------------------
from rapidocr import RapidOCR
ocr_engine = RapidOCR()

@app.route("/api/ocr", methods=["POST"])
def ocr():
    if "image" not in request.files:
        return jsonify({"error": "no image"}), 400
    f = request.files["image"]
    b = f.read()
    if not b:
        return jsonify({"error": "empty image"}), 400
    try:
        r = ocr_engine(b)
        txt_list = getattr(r, "txts", []) or []
        return jsonify({"text": "\n".join(txt_list)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------------------- 执行aim命令（增加超时、进程管控） ----------------------
def run_aim(cmd, sid, for_schedule=False, timeout=300):
    cwd = get_workdir(sid)
    out = ""
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        # 逐行读取输出
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            out += line
            if not for_schedule:
                yield json.dumps({
                    "type": "chunk",
                    "text": line,
                    "session_id": sid,
                    "done": False
                }, ensure_ascii=False) + "\n"
        # 等待进程结束，设置最大超时
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if proc:
            proc.kill()
            proc.wait()
        err_msg = f"进程执行超时{timeout}s，已强制终止"
        if not for_schedule:
            yield json.dumps({
                "type": "error",
                "text": err_msg,
                "session_id": sid,
                "done": True
            }, ensure_ascii=False) + "\n"
        return
    except Exception as e:
        err_msg = str(e)
        if not for_schedule:
            yield json.dumps({
                "type": "error",
                "text": err_msg,
                "session_id": sid,
                "done": True
            }, ensure_ascii=False) + "\n"
        return

    if proc.returncode != 0:
        err_msg = f"进程异常退出，ExitCode:{proc.returncode}"
        if not for_schedule:
            yield json.dumps({
                "type": "error",
                "text": err_msg,
                "session_id": sid,
                "done": True
            }, ensure_ascii=False) + "\n"
        return

    # 保存助手回复历史
    with lock:
        if sid in sessions:
            sessions[sid].setdefault("history", []).append({
                "role": "assistant",
                "content": out
            })
            save_sessions()

    if not for_schedule:
        yield json.dumps({
            "type": "done",
            "session_id": sid,
            "done": True
        }, ensure_ascii=False) + "\n"

# ---------------------- 定时调度循环（全程锁保护） ----------------------
def scheduler_loop():
    while True:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        due_tasks = []
        # 只读阶段
        with lock:
            for task_id, task_data in list(schedules.items()):
                if task_data.get("status") == "pending" and task_data.get("fire_at", "") <= now_str:
                    due_tasks.append((task_id, task_data))

        for task_id, task_data in due_tasks:
            # 修改状态全程上锁
            with lock:
                if task_id not in schedules:
                    continue
                if schedules[task_id]["status"] != "pending":
                    continue
                schedules[task_id]["status"] = "running"
                save_schedules()

            session_id = task_data.get("session_id", "")
            content = task_data.get("content", "")
            is_new = task_data.get("is_new", False)

            try:
                if is_new:
                    session_id = str(uuid.uuid4())
                    with lock:
                        sessions[session_id] = {
                            "title": content[:50],
                            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "history": []
                        }
                        save_sessions()
                    cmd = ["aim", "newrun", content]
                else:
                    with lock:
                        if session_id not in sessions:
                            sessions[session_id] = {
                                "title": content[:50],
                                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "history": []
                            }
                        sessions[session_id].setdefault("history", []).append({
                            "role": "user",
                            "content": content
                        })
                        save_sessions()
                    cmd = ["aim", "run", content]

                # 执行任务，丢弃流式输出
                for _ in run_aim(cmd, session_id, for_schedule=True):
                    pass

                # 任务成功
                with lock:
                    if task_id in schedules and schedules[task_id]["status"] == "running":
                        schedules[task_id]["status"] = "done"
                    schedules[task_id]["session_id"] = session_id
                    save_schedules()

            except Exception as e:
                with lock:
                    if task_id in schedules:
                        schedules[task_id]["status"] = "failed"
                        schedules[task_id]["error"] = str(e)
                        schedules[task_id]["session_id"] = session_id
                        save_schedules()

        time.sleep(5)

threading.Thread(target=scheduler_loop, daemon=True).start()

# ---------------------- HTTP路由接口 ----------------------
@app.route("/")
def index():
    return render_template("chat.html")

@app.route("/api/sessions")
def list_sessions():
    with lock:
        result = sorted([
            {
                "id": sid,
                "title": s.get("title", "新对话"),
                "created_at": s.get("created_at", ""),
                "msg_count": len(s.get("history", [])) // 2,
                "workdir": s.get("workdir", "")
            }
            for sid, s in sessions.items()
        ], key=lambda x: x.get("created_at", ""), reverse=True)
    return jsonify(result)

@app.route("/api/history")
def get_history():
    sid = request.args.get("session_id", "")
    with lock:
        s = sessions.get(sid, {})
    return jsonify({
        "title": s.get("title", "新对话"),
        "workdir": get_workdir(sid),
        "history": s.get("history", [])
    })

@app.route("/api/session", methods=["DELETE"])
def delete_session():
    sid = request.args.get("session_id", "")
    with lock:
        sessions.pop(sid, None)
        save_sessions()
    return jsonify({"ok": True})

@app.route("/api/session/workdir", methods=["PUT"])
def set_session_workdir():
    d = request.get_json() or {}
    sid = d.get("session_id", "")
    wd = d.get("workdir", "").strip()
    with lock:
        if sid not in sessions:
            return jsonify({"error": "not found"}), 404
        if wd and not os.path.isdir(wd):
            return jsonify({"error": "dir not found"}), 400
        if wd:
            sessions[sid]["workdir"] = wd
        else:
            sessions[sid].pop("workdir", None)
        save_sessions()
    return jsonify({"workdir": get_workdir(sid)})

@app.route("/api/schedules")
def list_schedules():
    filter_sid = request.args.get("session_id", "")
    lst = []
    with lock:
        for tid, s in schedules.items():
            if filter_sid and s.get("session_id") != filter_sid:
                continue
            lst.append({
                "id": tid,
                "session_id": s.get("session_id", ""),
                "content": s.get("content", ""),
                "fire_at": s.get("fire_at", ""),
                "status": s.get("status", ""),
                "created_at": s.get("created_at", ""),
                "error": s.get("error", "")
            })
    lst.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return jsonify(lst)

@app.route("/api/schedule", methods=["POST"])
def create_schedule():
    d = request.get_json() or {}
    c = d.get("content", "").strip()
    t = d.get("fire_at", "")
    sid = d.get("session_id", "")
    if not c or not t:
        return jsonify({"error": "content and fire_at required"}), 400
    task_id = str(uuid.uuid4())
    is_new = sid not in sessions
    with lock:
        schedules[task_id] = {
            "session_id": sid if not is_new else "",
            "content": c,
            "fire_at": t,
            "status": "pending",
            "is_new": is_new,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "error": ""
        }
        save_schedules()
    return jsonify({"schedule_id": task_id, "is_new": is_new})

@app.route("/api/schedule", methods=["DELETE"])
def delete_schedule():
    tid = request.args.get("schedule_id", "")
    with lock:
        schedules.pop(tid, None)
        save_schedules()
    return jsonify({"ok": True})

# 创建会话工具函数
def new_session(content=""):
    sid = str(uuid.uuid4())
    with lock:
        sessions[sid] = {
            "title": content[:50] if content else "新对话",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "history": []
        }
        save_sessions()
    return sid

@app.route("/api/chat", methods=["POST"])
def chat():
    d = request.get_json()
    c = d.get("content", "").strip()
    sid = d.get("session_id", "")
    if not c:
        return jsonify({"error": "empty"}), 400

    with lock:
        is_new = sid not in sessions
        if is_new:
            sid = new_session(c)
            cmd = ["aim", "newrun", c]
        else:
            sessions[sid].setdefault("history", []).append({
                "role": "user",
                "content": c
            })
            save_sessions()
            cmd = ["aim", "run", c]
    return Response(run_aim(cmd, sid), mimetype="application/x-ndjson")

@app.route("/api/new", methods=["POST"])
def new_conversation():
    d = request.get_json() or {}
    c = d.get("content", "").strip()
    sid = new_session(c)
    if c:
        return Response(run_aim(["aim", "newrun", c], sid), mimetype="application/x-ndjson")
    return jsonify({"session_id": sid})

# ---------------------- 入口主程序（跨平台自动打开浏览器） ----------------------
if __name__ == "__main__":
    import webbrowser
    host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5001
    addr = f"http://{host}:{port}"
    print(f"AI Chat LAN 服务启动: {addr}")
    # 跨平台浏览器打开，替代xdg-open
    def open_browser():
        time.sleep(1.2)
        try:
            webbrowser.open(addr)
        except Exception:
            pass
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host=host, port=port, debug=False, threaded=True)
