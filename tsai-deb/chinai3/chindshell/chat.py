"""流式子进程会话 + 历史记录 —— 供聊天类 HTML套壳应用共用。

前端轮询 /api/stream 拉取增量输出，避免长连接。
历史记录存 ~/.appname/history.json。
"""
import json
import os
import re
import signal
import subprocess
import threading
import time


def _children_of(pid):
    children = []
    try:
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            try:
                with open(f"/proc/{name}/stat", "r") as f:
                    parts = f.read().split()
                if len(parts) > 3 and parts[3] == str(pid):
                    children.append(int(name))
            except Exception:
                pass
    except Exception:
        pass
    return children


def kill_tree(pid, sig=signal.SIGTERM):
    """递归杀死 pid 及其全部后代进程（覆盖 aim→opencode→工具子进程）。"""
    for c in _children_of(pid):
        try:
            kill_tree(c, sig)
        except Exception:
            pass
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, OSError):
        pass


class StreamSession:
    def __init__(self):
        self._lock = threading.Lock()
        self._chunks = []
        self._done = True
        self._error = ""
        self.proc = None
        self._pgid = None

    @property
    def running(self):
        with self._lock:
            return not self._done

    def start(self, cmd, stdin_text=None, start_new_session=True, line_filter=None):
        """启动子进程并泵出其 stdout。cmd 为 argv 列表。

        line_filter(line) -> 行转换函数：返回要追加的文本（可返回 None 跳过）。
        """
        self._chunks = []
        self._done = False
        self._error = ""
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if stdin_text is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=start_new_session,
        )
        self.proc = proc
        try:
            self._pgid = os.getpgid(proc.pid)
        except Exception:
            self._pgid = None

        if stdin_text is not None:
            try:
                proc.stdin.write(stdin_text)
                proc.stdin.close()
            except Exception:
                pass

        def _pump():
            try:
                for line in proc.stdout:
                    if line_filter is not None:
                        line = line_filter(line)
                        if line is None:
                            continue
                    with self._lock:
                        self._chunks.append(line)
            except Exception as e:
                with self._lock:
                    if not self._error:
                        self._error = str(e)
            try:
                rc = proc.wait()
                if rc != 0:
                    with self._lock:
                        if not self._chunks and not self._error:
                            self._error = f"进程退出码 {rc}"
            except Exception:
                pass
            with self._lock:
                self._done = True

        threading.Thread(target=_pump, daemon=True).start()

    def poll(self, since):
        with self._lock:
            new = list(self._chunks[since:])
            done = self._done
            error = self._error
            total = len(self._chunks)
        return new, done, error, total

    def full_text(self):
        with self._lock:
            return "".join(self._chunks)

    def stop(self):
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        kill_tree(proc.pid, signal.SIGTERM)
        try:
            if self._pgid:
                os.killpg(self._pgid, signal.SIGTERM)
        except Exception:
            pass
        try:
            proc.wait(timeout=3)
        except Exception:
            try:
                kill_tree(proc.pid, signal.SIGKILL)
            except Exception:
                pass


AIM_STATE_FILE = os.path.expanduser("~/.local/share/aim/state.json")
AIM_CONVERSATIONS_FILE = os.path.expanduser("~/.local/share/aim/conversations.jsonl")


def current_aim_session():
    """读取 aim 当前会话（aim run 将继续的会话）。"""
    try:
        with open(AIM_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("session") or None
    except Exception:
        return None


def aim_session_to_rank(session):
    """把 aim session id 映射为 `aim se` 编号（aim change 用）。"""
    try:
        with open(AIM_CONVERSATIONS_FILE, "r", encoding="utf-8") as f:
            entries = [json.loads(l) for l in f if l.strip()]
    except Exception:
        return None
    if not entries:
        return None
    ids = sorted(e.get("id", 0) for e in entries if e.get("session") == session)
    if not ids:
        return None
    latest = ids[-1]
    return sum(1 for e in entries if e.get("id", 0) > latest) + 1


def aim_change_session(session):
    """aim change <N> 切换：让后续 aim run 继续该会话。"""
    rank = aim_session_to_rank(session)
    if rank is None:
        return False
    try:
        subprocess.run(["aim", "change", str(rank)],
                       capture_output=True, timeout=15)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 历史记录

def load_history(path, max_history=200):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def save_history(path, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def add_history(path, record, max_history=200):
    recs = load_history(path, max_history)
    recs.insert(0, record)
    save_history(path, recs[:max_history])


class ConversationTracker:
    """跟踪当前对话消息，支持实时写盘 / 存 / 读 / 清历史（~/.appname/history.json）。

    record_reply() 完成后立即 upsert 到历史文件（_live_index 记录正在更新的条目），
    实现"每轮回复完成就实时写入"，避免关掉应用丢失当前对话。
    """

    def __init__(self, history_path, max_history=200, session_provider=None):
        self.path = history_path
        self.max_history = max_history
        self.messages = []
        self._assistant_pending = False
        self._live_index = -1  # history.json 中正在实时更新的记录下标
        # session 提供函数：默认读 aim 当前会话；ainote2 等可覆盖为 opencode 会话
        self.session_provider = session_provider or current_aim_session

    def add_user(self, content):
        if self._assistant_pending:
            self.messages.pop()  # 上一条回复未完成，作废
        self.messages.append({"role": "user", "content": content})
        self._assistant_pending = True

    def record_reply(self, text):
        if self._assistant_pending:
            self.messages.append({"role": "assistant", "content": text.strip()})
            self._assistant_pending = False
            self._flush_live()  # 每轮完成后实时写盘

    def _flush_live(self):
        if self.is_empty():
            return
        title = ""
        for m in self.messages:
            if m.get("role") == "user":
                title = m["content"][:40]
                break
        if not title:
            title = "对话"
        record = {
            "title": title,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "messages": list(self.messages),
            "session": (self.session_provider() if callable(self.session_provider) else None),
        }
        recs = load_history(self.path, self.max_history)
        # 优先原位更新：同一会话的历史记录（支持"载入历史后继续"复用原记录）
        idx = None
        if record.get("session"):
            for i, r in enumerate(recs):
                if r.get("session") == record["session"]:
                    idx = i
                    break
        if idx is None and 0 <= self._live_index < len(recs):
            idx = self._live_index
        if idx is not None:
            recs[idx] = record
            self._live_index = idx
        else:
            recs.insert(0, record)
            self._live_index = 0
        save_history(self.path, recs[:self.max_history])

    def is_empty(self):
        return not [m for m in self.messages if (m.get("content") or "").strip()]

    def save(self):
        if self.is_empty():
            self._live_index = -1
            self._assistant_pending = False
            return
        self._flush_live()
        self.messages = []
        self._assistant_pending = False
        self._live_index = -1

    def load(self):
        return load_history(self.path, self.max_history)

    def clear(self):
        self.messages = []
        self._assistant_pending = False
        self._live_index = -1
        save_history(self.path, [])
