import subprocess
import threading
import json
import os
import time
from pathlib import Path

try:
    import gi
    gi.require_version("GLib", "2.0")
    from gi.repository import GLib
    _HAS_GLIB = True
except Exception:
    _HAS_GLIB = False

DATA_DIR = Path.home() / ".ainote"
DATA_DIR.mkdir(exist_ok=True)


class AimSession:
    def __init__(self, session_id=None):
        self.session_id = session_id
        self.process = None
        self.buffer = ""
        self._lock = threading.Lock()

    def send(self, message, on_data=None, on_done=None, on_error=None, on_debug=None):
        thread = threading.Thread(
            target=self._run_opencode,
            args=(message, on_data, on_done, on_error, on_debug),
            daemon=True
        )
        thread.start()
        return thread

    def _run_opencode(self, message, on_data, on_done, on_error, on_debug=None):
        def debug(kind, msg):
            if on_debug:
                if _HAS_GLIB:
                    GLib.idle_add(on_debug, kind, str(msg))
                else:
                    on_debug(kind, str(msg))

        try:
            args = ["opencode", "run", "--format", "json"]
            if self.session_id:
                args.extend(["--session", self.session_id])
            args.append(message)

            debug("cmd", " ".join(args))

            self.process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )

            debug("pid", self.process.pid)

            full_text = ""
            event_count = 0
            for line in iter(self.process.stdout.readline, ""):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    event_type = event.get("type")
                    event_count += 1
                    if event_count <= 3 or event_type == "error":
                        debug("event", f"[{event_count}] {event_type}: {json.dumps(event, ensure_ascii=False)[:200]}")
                    if event_type == "text":
                        text = event.get("part", {}).get("text", "")
                        if text:
                            full_text += text
                            if on_data:
                                on_data(text)
                    elif event_type in ("step_start", "step_finish"):
                        sid = event.get("sessionID")
                        if sid and not self.session_id:
                            self.session_id = sid
                            debug("session", f"captured session: {sid}")
                except json.JSONDecodeError:
                    debug("warn", f"non-JSON stdout: {line[:100]}")

            self.process.stdout.close()
            self.process.wait(timeout=30)
            debug("done", f"exit={self.process.returncode}, events={event_count}, chars={len(full_text)}")

            if self.process.returncode != 0:
                error = self.process.stderr.read()
                debug("error", f"stderr: {error[:300]}")
                if on_error:
                    on_error(error or f"exit code: {self.process.returncode}")
                return

            if on_done:
                on_done(full_text)

        except subprocess.TimeoutExpired:
            self.process.kill()
            debug("error", "process timed out (30s)")
            if on_error:
                on_error("请求超时")
        except FileNotFoundError:
            debug("error", "opencode not found in PATH")
            if on_error:
                on_error("'opencode' 命令未找到，请确认已安装")
        except Exception as e:
            debug("error", f"{type(e).__name__}: {e}")
            if on_error:
                on_error(str(e))

    def cancel(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    @staticmethod
    def new_session():
        return AimSession()

    def save(self, messages, title="Untitled"):
        data = {
            "session_id": self.session_id,
            "title": title,
            "messages": messages,
            "updated_at": time.time()
        }
        path = DATA_DIR / f"{self.session_id or 'unsaved'}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    @staticmethod
    def load(session_id):
        path = DATA_DIR / f"{session_id}.json"
        if path.exists():
            data = json.loads(path.read_text())
            session = AimSession(data["session_id"])
            return session, data
        return None, None

    @staticmethod
    def list_sessions():
        sessions = []
        for f in sorted(DATA_DIR.glob("*.json"), reverse=True):
            data = json.loads(f.read_text())
            sessions.append(data)
        return sessions
