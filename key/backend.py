import json
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
