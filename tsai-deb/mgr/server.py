"""AI 电脑管家 — chindshell 套壳后端（Flask，完整复刻 12 面板）。

- 系统信息/进程/磁盘/启动/网络/内存 由 psutil+系统命令实时提供
- AI 功能：aim run 分析 + 修复命令流式执行（可停止）
- AI模型：ollama list/pull/delete；工具箱：启动常用程序
"""
import os
import shutil
import subprocess
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
for p in (BASE_DIR, "/usr/chindows"):
    if p not in sys.path:
        sys.path.insert(0, p)

import psutil  # noqa: E402
from flask import Flask, jsonify, render_template, request  # noqa: E402

from chindshell import flask as csf  # noqa: E402

app = Flask(__name__)
csf.register(app)

# ---------------- 状态 ----------------
_lock = threading.Lock()
_state = {"running": False, "log": [], "stop": False, "status": "就绪",
          "ask": None, "ask_auto": False}
_procs = []
_ai_out = {"text": ""}


def _set(**kw):
    with _lock:
        _state.update(kw)


def _log(text):
    with _lock:
        _state["log"].append(text)
        _ai_out["text"] += text + "\n"


def _status(text):
    _set(status=text)


def _track(p):
    with _lock:
        _procs.append(p)


def _untrack(p):
    with _lock:
        try:
            _procs.remove(p)
        except ValueError:
            pass


# ---------------- SystemInfo (psutil) ----------------
def fmt_bytes(v):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or unit == "TB":
            return f"{v:.2f} {unit}" if unit != "B" else f"{v:.0f} B"
        v /= 1024


def fmt_speed(bps):
    return fmt_bytes(bps) + "/s"


def sysinfo():
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = shutil.disk_usage("/")
    cpu_freq = psutil.cpu_freq()
    uptime_s = time.time() - psutil.boot_time()
    days, rem = divmod(int(uptime_s), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    uptime = f"{days}天 {h}h {m}m" if days else f"{h}h {m}m"
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            u = shutil.disk_usage(part.mountpoint)
            disks.append({"device": part.device, "mountpoint": part.mountpoint,
                          "fstype": part.fstype, "total": u.total, "used": u.used,
                          "free": u.free, "percent": round(u.used / u.total * 100, 1)})
        except Exception:
            pass
    net = {}
    for name, addrs in psutil.net_if_addrs().items():
        if name == "lo":
            continue
        ips = [a.address for a in addrs if a.family.name.startswith("AF_INET")]
        try:
            stats = psutil.net_if_stats()[name]
            net[name] = {"addresses": ips, "status": stats.isup,
                         "speed": stats.speed or None}
        except Exception:
            net[name] = {"addresses": ips, "status": False, "speed": None}
    temp = None
    try:
        t = psutil.sensors_temperatures()
        for k in ("coretemp", "cpu_thermal", "acpitz"):
            if t.get(k):
                temp = t[k][0].current
                break
    except Exception:
        pass
    uname = os.uname()
    return {
        "cpu": {"percent": psutil.cpu_percent(interval=None),
                "cores": psutil.cpu_count(False), "threads": psutil.cpu_count(True),
                "freq": round(cpu_freq.current, 0) if cpu_freq else None,
                "max_freq": round(cpu_freq.max, 0) if cpu_freq and cpu_freq.max else None},
        "memory": {"total": mem.total, "used": mem.used, "available": mem.available,
                   "percent": mem.percent, "buffers": mem.buffers or 0,
                   "cached": mem.cached or 0, "shared": mem.shared or 0},
        "swap": {"total": swap.total, "used": swap.used, "free": swap.free, "percent": swap.percent},
        "disk": {"total": disk.total, "used": disk.used, "free": disk.free,
                 "percent": round(disk.used / disk.total * 100, 1)},
        "disks": disks,
        "net": net,
        "processes": len(psutil.pids()),
        "uptime": uptime,
        "boot_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(psutil.boot_time())),
        "temp": temp,
        "platform": f"{uname.sysname}",
        "platform_release": uname.release,
        "platform_version": uname.version.split()[0] if uname.version else "",
        "architecture": uname.machine,
        "hostname": uname.nodename,
        "processor": os.environ.get("PROCESSOR", "") or _cpu_name(),
        "users": [u.name for u in psutil.users()],
        "load": list(os.getloadavg()),
    }


def _cpu_name():
    try:
        out = subprocess.run(["sh", "-c", "grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "未知"
    except Exception:
        return "未知"


@app.route("/api/sysinfo")
def api_sysinfo():
    try:
        return jsonify(sysinfo())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/processes")
def api_processes():
    rows = []
    for p in psutil.process_iter(["pid", "name", "status", "username", "memory_info", "cpu_percent"]):
        try:
            mem = p.info.get("memory_info")
            rows.append({
                "name": p.info.get("name") or "?",
                "pid": p.info.get("pid"),
                "cpu": round(p.info.get("cpu_percent") or 0, 1),
                "mem_mb": round((mem.rss if mem else 0) / 1048576, 2),
                "status": p.info.get("status") or "",
                "user": p.info.get("username") or "",
            })
        except Exception:
            continue
    rows.sort(key=lambda r: -r["cpu"])
    return jsonify({"processes": rows[:300]})


@app.route("/api/process/kill", methods=["POST"])
def api_process_kill():
    data = request.get_json(silent=True) or {}
    pid = data.get("pid")
    try:
        psutil.Process(int(pid)).terminate()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/highmem")
def api_highmem():
    rows = []
    total = psutil.virtual_memory().total or 1
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            rss = p.info["memory_info"].rss
            rows.append({"name": p.info["name"], "pid": p.info["pid"],
                         "mem_mb": round(rss / 1048576, 2),
                         "percent": round(rss / total * 100, 2)})
        except Exception:
            continue
    rows.sort(key=lambda r: -r["mem_mb"])
    return jsonify({"processes": rows[:10]})


@app.route("/api/startup")
def api_startup():
    # 真实数据：用户 autostart + systemd 用户服务
    items = []
    adir = os.path.expanduser("~/.config/autostart")
    for f in sorted(os.listdir(adir)) if os.path.isdir(adir) else []:
        if f.endswith(".desktop"):
            try:
                name = f[:-8]
                with open(os.path.join(adir, f), "r", encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        if line.startswith("Name="):
                            name = line.split("=", 1)[1].strip()
                            break
                items.append({"name": name, "path": os.path.join(adir, f),
                              "status": "已启用", "source": "用户"})
            except Exception:
                pass
    try:
        out = subprocess.run(["systemctl", "list-unit-files", "--user", "--state=enabled",
                              "--no-pager", "--no-legend"], capture_output=True, text=True, timeout=10)
        for line in out.stdout.splitlines():
            parts = line.split()
            if parts:
                items.append({"name": parts[0], "path": parts[0],
                              "status": "已启用", "source": "用户服务"})
    except Exception:
        pass
    return jsonify({"items": items})


@app.route("/api/network/io")
def api_network_io():
    c = psutil.net_io_counters()
    return jsonify({"recv": c.bytes_recv, "sent": c.bytes_sent})


@app.route("/api/toolbox", methods=["POST"])
def api_toolbox():
    data = request.get_json(silent=True) or {}
    appname = data.get("app")
    cmd = {"terminal": ["gnome-terminal"], "files": ["nautilus"],
           "browser": ["firefox"], "settings": ["gnome-control-center"],
           "monitor": ["gnome-system-monitor"]}.get(appname)
    if not cmd:
        return jsonify({"ok": False, "error": "未知应用"}), 400
    try:
        subprocess.Popen(cmd, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------- AI 功能动作 ----------------
AI_ACTIONS = {
    "optimize": {
        "name": "AI系统优化",
        "prompt": "你是一个智能系统优化助手。请分析当前系统并告诉你将执行哪些优化操作，包括清理垃圾、释放内存、优化启动项、修复配置问题。请先输出分析结果。",
        "cmds": [
            ("sudo apt-get clean -y 2>/dev/null", "清理 apt 缓存"),
            ("sudo apt-get autoremove -y 2>/dev/null", "清理孤立依赖"),
            ("sudo journalctl --vacuum-time=7d 2>/dev/null", "清理 7 天前日志"),
            ("rm -rf ~/.cache/thumbnails/* ~/.local/share/Trash/* 2>/dev/null", "清理缩略图与回收站"),
            ("sync && echo 3 | sudo tee /proc/sys/vm/drop_caches > /dev/null 2>&1", "释放内存缓存"),
            ("sudo systemctl mask apt-daily.service --now 2>/dev/null", "禁用 apt-daily 慢启动"),
            ("sudo systemctl mask NetworkManager-wait-online.service --now 2>/dev/null", "禁用网络等待"),
            ("echo '=== 系统优化完成 ==='", ""),
        ],
    },
    "diag": {
        "name": "AI故障诊断",
        "prompt": "你是一个智能故障诊断助手。请分析系统日志和硬件状态，找出潜在问题，并输出分析结果和修复建议。",
        "cmds": [
            ("echo '=== 硬件信息 ===' && lspci -k | grep -E 'VGA|Network|Audio|Kernel driver' | head -20", "检测硬件"),
            ("sudo journalctl -p err -b --no-pager -n 30 2>/dev/null", "系统错误日志"),
            ("free -h", "内存状态"),
            ("echo '=== 诊断完成 ==='", ""),
        ],
    },
    "perf": {
        "name": "AI性能分析",
        "prompt": "你是一个智能性能分析助手。请分析 CPU、内存、磁盘的性能数据，找出瓶颈并输出优化建议。",
        "cmds": [
            ("echo '=== CPU TOP ===' && ps aux --sort=-%cpu | head -11", "CPU 占用 TOP"),
            ("echo '=== 内存 TOP ===' && ps aux --sort=-%mem | head -11", "内存占用 TOP"),
            ("free -h", "内存概况"),
            ("df -h /", "磁盘空间"),
            ("iostat -x 1 2 2>/dev/null || echo 'iostat 不可用'", "磁盘 IO"),
            ("echo '=== 性能分析完成 ==='", ""),
        ],
    },
    "security": {
        "name": "AI安全扫描",
        "prompt": "你是一个智能安全扫描助手。请分析以下安全数据，找出风险并输出处理建议。",
        "cmds": [
            ("ss -tuln", "网络连接"),
            ("ss -tlnp 2>/dev/null | head -20", "监听端口"),
            ("ps aux --sort=-%cpu | head -15", "异常进程"),
            ("sudo last -n 10 2>/dev/null", "登录记录"),
            ("sudo apt-get check 2>/dev/null", "系统完整性"),
            ("echo '=== 安全扫描完成 ==='", ""),
        ],
    },
    "driver": {
        "name": "AI驱动更新",
        "prompt": "你是一个智能驱动管理助手。请根据检测到的硬件驱动版本信息，分析哪些驱动需要更新，并输出详细建议。",
        "cmds": [
            ("echo '=== 显卡 ===' && lspci -k | grep -A3 'VGA\\|3D'", "显卡驱动"),
            ("echo '=== WiFi ===' && lspci -k | grep -A3 Network", "WiFi 驱动"),
            ("echo '=== 音频 ===' && lspci -k | grep -A3 Audio", "音频驱动"),
            ("lsmod | grep -E 'i915|iwlwifi|btusb|nvme|snd' | head -10", "已加载模块"),
            ("dpkg -l intel-microcode 2>/dev/null | tail -2", "微码固件"),
            ("echo '=== 驱动检测完成 ==='", ""),
        ],
    },
    "soft": {
        "name": "AI软件管理",
        "prompt": "你是一个智能软件管理助手。请分析系统软件包状态，输出可升级软件包数量和依赖情况，并给出升级建议。",
        "cmds": [
            ("apt list --upgradable 2>/dev/null | tail -1", "可升级包"),
            ("sudo apt-get check 2>/dev/null", "依赖检查"),
            ("sudo apt-get upgrade -y 2>/dev/null | tail -5", "升级软件包"),
            ("sudo apt-get autoremove -y 2>/dev/null && sudo apt-get clean -y 2>/dev/null", "清理无用包"),
            ("echo '=== 软件升级完成 ==='", ""),
        ],
    },
    "network": {
        "name": "AI网络优化",
        "prompt": "你是一个智能网络优化助手。请分析网络配置和连接状态，找出问题并给出优化建议。",
        "cmds": [
            ("echo '=== 接口 ===' && ip addr | grep -E '^[0-9]|inet '", "网络接口"),
            ("echo '=== DNS ===' && cat /etc/resolv.conf 2>/dev/null", "DNS 配置"),
            ("echo '=== 延迟 ===' && ping -c 4 114.114.114.114 2>&1 | tail -3", "网络延迟"),
            ("ss -s", "连接统计"),
            ("echo '=== 网络优化完成 ==='", ""),
        ],
    },
    "disk": {
        "name": "AI磁盘整理",
        "prompt": "你是一个智能磁盘管理助手。请分析磁盘使用情况和文件系统状态，输出优化建议。",
        "cmds": [
            ("df -h /", "磁盘空间"),
            ("lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT 2>/dev/null", "分区结构"),
            ("sudo fstrim -v / 2>/dev/null || echo 'TRIM 跳过（SSD 无需碎片整理）'", "SSD TRIM"),
            ("find /home -xdev -type f -size +100M -exec ls -lh {} \\; 2>/dev/null | sort -rh -k5 | head -10", "大文件 TOP"),
            ("echo '=== 磁盘优化完成 ==='", ""),
        ],
    },
    "startup": {
        "name": "AI启动优化",
        "prompt": "你是一个智能启动优化助手。请分析开机启动项和服务耗时，输出优化建议并自动执行。",
        "cmds": [
            ("systemd-analyze 2>/dev/null", "启动耗时"),
            ("systemd-analyze blame 2>/dev/null | head -10", "启动耗时 TOP"),
            ("sudo systemctl mask apt-daily.service apt-daily-upgrade.service NetworkManager-wait-online.service plymouth-quit-wait.service --now 2>/dev/null && echo '已禁用慢启动服务'", "禁用慢服务"),
            ("echo '=== 启动优化完成，建议重启 ==='", ""),
        ],
    },
    "memory": {
        "name": "AI内存优化",
        "prompt": "你是一个智能内存优化助手。请分析当前内存使用情况，输出优化建议并自动执行。",
        "cmds": [
            ("free -h", "内存现状"),
            ("ps aux --sort=-%mem | head -11", "内存占用 TOP"),
            ("sync && echo 3 | sudo tee /proc/sys/vm/drop_caches > /dev/null 2>&1", "释放缓存"),
            ("free -h", "释放后内存"),
            ("swapon --show 2>/dev/null", "交换分区"),
            ("echo '=== 内存优化完成 ==='", ""),
        ],
    },
    "clean": {
        "name": "AI清理磁盘",
        "prompt": "清理系统缓存、临时文件、日志文件，释放磁盘空间。",
        "cmds": [
            ("rm -rf ~/.cache/thumbnails/* ~/.local/share/Trash/* /tmp/* 2>/dev/null", "清理缓存/回收站/临时文件"),
            ("sudo journalctl --vacuum-time=7d 2>/dev/null", "清理旧日志"),
            ("sudo apt-get clean -y 2>/dev/null", "清理 apt 缓存"),
            ("echo '=== 磁盘清理完成 ==='", ""),
        ],
    },
}



# ---------------- 执行确认（结构化询问） ----------------
import re as _re
import uuid

NEED_CONFIRM = _re.compile(r"sudo |systemctl (mask|disable|enable|stop|start|restart|set)|apt(-get)? (install|remove|purge|upgrade|dist-upgrade|autoremove)|rm -rf|fstrim|dd |mkfs|useradd|deluser|groupadd|fwupdmgr|journalctl --vacuum|drop_caches")

_ASK_ANS = {}


def _need_confirm(cmd):
    return bool(NEED_CONFIRM.search(cmd))


def _ask_user(cmd, desc):
    """向用户发起一条确认询问；True=执行 / False=跳过。阻塞等待用户回答。"""
    if _state.get("ask_auto"):
        return True
    qid = uuid.uuid4().hex[:8]
    with _lock:
        _state["ask"] = {"id": qid, "cmd": cmd, "desc": desc}
    while not _state.get("stop"):
        with _lock:
            ask = _state.get("ask")
        if ask is None or ask.get("id") != qid:
            break
        time.sleep(0.3)
    with _lock:
        _state["ask"] = None
        ok = _ASK_ANS.get("ok", True) if _ASK_ANS.get("id") == qid else True
        _ASK_ANS.clear()
    if _state.get("stop"):
        return False
    return ok


def _run_shell_cmd(cmd):
    """执行单条 shell 命令，产出 [(行)] 流式。"""
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True)
    _track(p)
    try:
        for line in p.stdout:
            yield line.rstrip()
        p.wait()
    finally:
        _untrack(p)


@app.route("/api/actions")
def api_actions():
    return jsonify([{"key": k, "name": v["name"]} for k, v in AI_ACTIONS.items()])


def _gen_ai(prompt, name):
    _set(running=True, stop=False)
    _ai_out["text"] = ""
    _log(f"# {name} 开始\n")
    try:
        try:
            ai = subprocess.Popen(["aim", "run", prompt],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, timeout=120)
            _track(ai)
            ai_out_lines = []
            for line in ai.stdout:
                ai_out_lines.append(line.rstrip())
            ai.wait()
            _untrack(ai)
            ai_text = "\n".join(ai_out_lines).strip()
            if ai_text:
                _log(f"[AI分析]\n{ai_text[:800]}\n")
        except Exception as e:
            _log(f"[AI] 分析失败: {e}\n")
        yield "ai_done"
    finally:
        with _lock:
            _state["running"] = False
            _state["stop"] = False


@app.route("/api/action", methods=["POST"])
def api_action():
    data = request.get_json(silent=True) or {}
    key = data.get("key")
    action = AI_ACTIONS.get(key)
    if not action:
        return jsonify({"ok": False, "error": "未知动作"}), 400
    if _state["running"]:
        return jsonify({"ok": False, "error": "已有操作在运行"}), 409
    _status("AI 正在执行: " + action["name"])
    threading.Thread(target=lambda: _run_action(action), daemon=True).start()
    return jsonify({"ok": True, "name": action["name"]})


def _run_action(action):
    _set(running=True, stop=False)
    with _lock:
        _ai_out["text"] = ""
        _state["log"] = []
    _log(f"# {action['name']} 开始")
    try:
        try:
            ai = subprocess.Popen(["aim", "run", action["prompt"]],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True)
            _track(ai)
            lines = []
            for line in ai.stdout:
                lines.append(line.rstrip())
            ai.wait()
            _untrack(ai)
            if lines:
                _log("\n[AI分析]\n" + "\n".join(lines)[:900])
        except Exception as e:
            _log(f"\n[AI] 分析失败: {e}")
        for cmd, desc in action["cmds"]:
            if _state.get("stop"):
                _log("\n已停止")
                break
            if _need_confirm(cmd):
                _log(f"\n🔒 需确认: {desc or cmd}")
                if not _ask_user(cmd, desc):
                    _log("  ⏭ 已跳过（用户未批准）")
                    continue
                _log("  ✅ 用户已批准执行")
            _log(f"\n>>> {desc or cmd}")
            for line in _run_shell_cmd(cmd):
                if _state.get("stop"):
                    break
                if line.strip():
                    _log("  " + line)
    finally:
        _set(running=False, stop=False)
        _status("操作完成")
        _log("\n=== 完成 ===")



@app.route("/api/ask")
def api_ask_status():
    with _lock:
        return jsonify({"ask": _state.get("ask"), "running": _state.get("running")})


@app.route("/api/ask-answer", methods=["POST"])
def api_ask_answer():
    data = request.get_json(silent=True) or {}
    with _lock:
        ask = _state.get("ask")
        if not ask:
            return jsonify({"ok": False, "error": "当前无待回答的询问"}), 400
        _ASK_ANS["id"] = ask.get("id")
        _ASK_ANS["ok"] = bool(data.get("ok"))
        if data.get("all"):
            _state["ask_auto"] = True
        _state["ask"] = None
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    _set(stop=True)
    with _lock:
        procs = list(_procs)
    for p in procs:
        try:
            p.kill()
        except Exception:
            pass
    _status("操作已停止")
    _log("\n[已停止] 已终止当前操作")
    return jsonify({"ok": True})


@app.route("/api/log")
def api_log():
    with _lock:
        return jsonify({"log": list(_state["log"]), "running": _state["running"],
                        "status": _state["status"]})


@app.route("/api/status")
def api_status():
    with _lock:
        return jsonify({"status": _state["status"], "running": _state["running"]})


# ---------------- AI 问答 ----------------
@app.route("/api/ask", methods=["POST"])
def api_ask():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"ok": False, "error": "问题为空"}), 400
    if _state["running"]:
        return jsonify({"ok": False, "error": "已有操作在运行"}), 409
    _status("AI 正在回答问题…")
    threading.Thread(target=lambda: _run_ask(question), daemon=True).start()
    return jsonify({"ok": True})


def _run_ask(question):
    _set(running=True, stop=False)
    _log(f"# 问答: {question}")
    try:
        p = subprocess.Popen(["aim", "run", question],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        _track(p)
        for line in p.stdout:
            if _state.get("stop"):
                break
            if line.strip():
                _log(line.rstrip())
        p.wait()
        _untrack(p)
    finally:
        _set(running=False, stop=False)
        _status("完成")


# ---------------- Ollama 模型管理 ----------------
def _ollama_list():
    try:
        r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=30)
        rows = []
        for line in r.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                rows.append({"name": parts[0], "id": parts[1] if len(parts) > 1 else "",
                             "size": parts[2] if len(parts) > 2 else ""})
        return rows
    except Exception:
        return []


@app.route("/api/ollama/models")
def api_ollama_models():
    return jsonify({"models": _ollama_list()})


@app.route("/api/ollama/pull", methods=["POST"])
def api_ollama_pull():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "模型名必填"}), 400
    _status(f"正在拉取模型 {name}…")
    threading.Thread(target=lambda: _ollama_cmd(["ollama", "pull", name], f"拉取 {name}"), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/ollama/delete", methods=["POST"])
def api_ollama_delete():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "模型名必填"}), 400
    _status(f"正在删除模型 {name}…")
    threading.Thread(target=lambda: _ollama_cmd(["ollama", "delete", name], f"删除 {name}"), daemon=True).start()
    return jsonify({"ok": True})


def _ollama_cmd(argv, desc):
    _set(running=True)
    _log(f"# {desc}")
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        _track(p)
        for line in p.stdout:
            if _state.get("stop"):
                break
            if line.strip():
                _log(line.rstrip())
        p.wait()
        _untrack(p)
    finally:
        _set(running=False)
        _status("完成")


@app.route("/")
def index():
    return render_template("index.html")
