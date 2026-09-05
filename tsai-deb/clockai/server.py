import os
import sys
import threading
import time

sys.path.insert(0, "/usr/chindows")
sys.path.insert(0, "/usr/chindows/clockai")

from datetime import datetime

from flask import Flask, jsonify, render_template, request

from chindshell import flask as csf

from clockai import storage, systemd as sysd
from clockai.models import Task
from clockai.scheduler import execute_task

app = Flask(__name__)
csf.register(app)

_sched = {"running": False, "stop": threading.Event()}
_sched_lock = threading.Lock()


def _to_dict(t):
    return {
        "id": t.id, "prompt": t.prompt, "time": t.time, "period": t.period,
        "enabled": t.enabled, "last_run": t.last_run or "-",
        "last_result": t.last_result or "",
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/tasks")
def api_tasks():
    return jsonify([_to_dict(t) for t in storage.load_tasks()])


@app.route("/api/tasks", methods=["POST"])
def api_add():
    d = request.get_json(force=True) or {}
    prompt = (d.get("prompt") or "").strip()
    time_val = (d.get("time") or "").strip()
    period = d.get("period") or "daily"
    if not prompt or not time_val:
        return jsonify({"ok": False, "error": "提示词与时间必填"})
    task = Task.create(prompt=prompt, time=time_val, period=period)
    storage.add_task(task)
    if not sysd.install_task(task):
        storage.delete_task(task.id)
        return jsonify({"ok": False, "error": "无法写入系统计划单元（sudo 不可用？）"})
    return jsonify({"ok": True})


@app.route("/api/tasks/<task_id>", methods=["POST"])
def api_update(task_id):
    d = request.get_json(force=True) or {}
    task = storage.find_task(task_id)
    if not task:
        return jsonify({"ok": False, "error": "任务不存在"})
    old = task.to_dict()
    task.prompt = (d.get("prompt") or "").strip() or task.prompt
    task.time = (d.get("time") or "").strip() or task.time
    task.period = d.get("period") or task.period
    if not sysd.update_task(task):
        task.__dict__.update(old)
        return jsonify({"ok": False, "error": "无法更新系统计划单元（sudo 不可用？）"})
    storage.update_task(task)
    return jsonify({"ok": True})


@app.route("/api/tasks/<task_id>/delete", methods=["POST"])
def api_delete(task_id):
    if not sysd.remove_task(task_id):
        return jsonify({"ok": False, "error": "无法移除系统计划单元"})
    storage.delete_task(task_id)
    return jsonify({"ok": True})


@app.route("/api/tasks/<task_id>/toggle", methods=["POST"])
def api_toggle(task_id):
    task = storage.find_task(task_id)
    if not task:
        return jsonify({"ok": False, "error": "任务不存在"})
    task.enabled = not task.enabled
    if not sysd.update_task(task):
        task.enabled = not task.enabled
        return jsonify({"ok": False, "error": "无法更新系统计划单元（sudo 不可用？）"})
    storage.update_task(task)
    return jsonify({"ok": True, "enabled": task.enabled})


@app.route("/api/tasks/<task_id>/run", methods=["POST"])
def api_run(task_id):
    task = storage.find_task(task_id)
    if not task:
        return jsonify({"ok": False, "error": "任务不存在"})

    def _work():
        result = execute_task(task)
        task.last_result = result
        task.last_run = datetime.now().isoformat()
        storage.update_task(task)

    threading.Thread(target=_work, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/status")
def api_status():
    return jsonify({"running": _sched["running"]})


@app.route("/api/scheduler", methods=["POST"])
def api_scheduler():
    if _sched["running"]:
        _sched["stop"].set()
        _sched["running"] = False
        return jsonify({"ok": True, "running": False})
    _sched["stop"].clear()
    _sched["running"] = True
    threading.Thread(target=_sched_loop, daemon=True).start()
    return jsonify({"ok": True, "running": True})


def _sched_loop():
    while not _sched["stop"].is_set():
        now = datetime.now().replace(second=0, microsecond=0)
        for task in storage.load_tasks():
            if task.should_run(now):
                task.last_run = now.isoformat()
                storage.update_task(task)
                threading.Thread(target=_run_sched_task, args=(task,), daemon=True).start()
        _sched["stop"].wait(30)


def _run_sched_task(task):
    result = execute_task(task)
    task.last_result = result
    storage.update_task(task)
