import json
import os
import re
import subprocess
import threading

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text):
    return ANSI_RE.sub("", text)


class AimBackend:
    """Thin wrapper around the system `aim` command.

    - new conversation:  aim newrun <message>   (optionally -f <file>)
    - continue:          aim run <message>      (optionally -f <file>)
    """

    def __init__(self):
        self._busy = False
        self._proc = None
        self._lock = threading.Lock()

    @property
    def busy(self):
        return self._busy

    def stop(self):
        """Terminate the currently running aim process, if any."""
        with self._lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass

    def send(self, prompt, files=None, new_conversation=False,
             on_delta=None, on_done=None, on_error=None):
        if self._busy:
            if on_error:
                on_error("上一个请求仍在处理中，请稍候")
            return

        argv = ["aim", "newrun" if new_conversation else "run"]
        argv.append(prompt)
        for f in files or []:
            argv += ["-f", f]

        self._busy = True
        self._proc = None

        def worker():
            proc = None
            try:
                proc = subprocess.Popen(
                    argv,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
                with self._lock:
                    self._proc = proc
                collected = []
                for line in proc.stdout:
                    line = line.rstrip("\n")
                    text = self._parse_line(line)
                    if text:
                        collected.append(text)
                        if on_delta:
                            on_delta(text)
                proc.wait()
                stderr = proc.stderr.read() or ""
                if proc.returncode != 0:
                    msg = stderr.strip() or f"命令异常退出（{proc.returncode}）"
                    if on_error:
                        on_error(strip_ansi(msg))
                    return
                final = strip_ansi("".join(collected)).strip()
                if on_done:
                    on_done(final)
            except Exception as e:
                if on_error:
                    on_error(str(e))
            finally:
                if proc is not None:
                    try:
                        proc.stdout.close()
                    except OSError:
                        pass
                with self._lock:
                    self._proc = None
                self._busy = False

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _parse_line(line):
        if not line:
            return None
        if not line.startswith("{"):
            return line
        try:
            ev = json.loads(line)
        except ValueError:
            return None
        if ev.get("type") != "message":
            return None
        part = ev.get("part") or {}
        ptype = part.get("type")
        if ptype in ("text", "text-delta"):
            return part.get("text") or ""
        return None

    def _run_aim(self, argv, timeout=60):
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return proc

    @staticmethod
    def parse_conversation(text):
        conv = {"id": None, "time": "", "engine": "", "command": "", "prompt": "", "reply": ""}
        section = None
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("=== Conversation #"):
                conv["id"] = s[len("=== Conversation #"):].rstrip("=").strip()
            elif s.startswith("Time:"):
                conv["time"] = s[len("Time:"):].strip()
            elif s.startswith("Engine:"):
                conv["engine"] = s[len("Engine:"):].strip()
            elif s.startswith("Command:"):
                conv["command"] = s[len("Command:"):].strip()
            elif s == "Prompt:":
                section = "prompt"
            elif s == "Reply:":
                section = "reply"
            elif s == "---":
                section = None
            elif section == "prompt":
                conv["prompt"] += line + "\n"
            elif section == "reply":
                conv["reply"] += line + "\n"
        conv["prompt"] = conv["prompt"].strip()
        conv["reply"] = conv["reply"].strip()
        return conv

    def list_conversations(self, on_done, on_error=None):
        def worker():
            try:
                proc = self._run_aim(["aim", "se"], timeout=30)
            except Exception as e:
                if on_error:
                    on_error(str(e))
                return
            if proc.returncode != 0:
                if on_error:
                    on_error(strip_ansi(proc.stderr.strip()) or f"aim se 执行失败（{proc.returncode}）")
                return
            items = []
            for line in proc.stdout.splitlines():
                parts = line.split("\t", 4)
                if len(parts) == 5 and parts[0].strip().isdigit():
                    items.append({
                        "id": int(parts[0].strip()),
                        "time": parts[1].strip(),
                        "engine": parts[2].strip(),
                        "command": parts[3].strip(),
                        "prompt": parts[4].strip(),
                    })
            if on_done:
                on_done(items)

        threading.Thread(target=worker, daemon=True).start()

    def show_conversation(self, cid, on_done, on_error=None):
        def worker():
            try:
                proc = self._run_aim(["aim", "se", str(cid)], timeout=60)
            except Exception as e:
                if on_error:
                    on_error(str(e))
                return
            if proc.returncode != 0:
                if on_error:
                    on_error(strip_ansi(proc.stderr.strip()) or f"aim se {cid} 执行失败（{proc.returncode}）")
                return
            if on_done:
                on_done(self.parse_conversation(proc.stdout))

        threading.Thread(target=worker, daemon=True).start()

    def change_conversation(self, cid, on_done, on_error=None):
        def worker():
            try:
                proc = self._run_aim(["aim", "change", str(cid)], timeout=30)
            except Exception as e:
                if on_error:
                    on_error(str(e))
                return
            if proc.returncode != 0:
                if on_error:
                    on_error(strip_ansi(proc.stderr.strip()) or f"aim change {cid} 失败（{proc.returncode}）")
                return
            if on_done:
                on_done(strip_ansi(proc.stdout).strip())

        threading.Thread(target=worker, daemon=True).start()

    def current_conversation(self, on_done, on_error=None):
        def worker():
            try:
                proc = self._run_aim(["aim", "change"], timeout=30)
            except Exception as e:
                if on_error:
                    on_error(str(e))
                return
            if on_done:
                on_done(strip_ansi(proc.stdout).strip())

        threading.Thread(target=worker, daemon=True).start()

    def current_conversation_id(self, on_done, on_error=None):
        def worker():
            session = None
            try:
                proc = self._run_aim(["aim", "change"], timeout=30)
                for part in (strip_ansi(proc.stdout) or "").split():
                    if part.startswith("session="):
                        session = part.split("=", 1)[1]
                        break
            except Exception as e:
                if on_error:
                    on_error(str(e))
                return
            cid = None
            if session:
                data_path = os.path.expanduser("~/.local/share/aim/conversations.jsonl")
                try:
                    with open(data_path, "r", encoding="utf-8", errors="replace") as f:
                        lines = [ln.strip() for ln in f if ln.strip()]
                    total = 0
                    index = 0
                    for i, ln in enumerate(lines, start=1):
                        try:
                            rec = json.loads(ln)
                        except ValueError:
                            continue
                        total += 1
                        if rec.get("session") == session:
                            index = i
                    # aim se 按时间倒序重新编号：#1=最新
                    if index:
                        cid = total - index + 1
                except OSError:
                    pass
            if on_done:
                on_done(cid)

        threading.Thread(target=worker, daemon=True).start()
