import os
import socket
import threading


def socket_path():
    # 优先级: XDG_RUNTIME_DIR > HOME > /tmp
    candidates = []
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        candidates.append(xdg)
    home = os.environ.get("HOME")
    if home:
        candidates.append(os.path.join(home, ".cache", "ai-assistant"))
    candidates.append("/tmp")

    for base in candidates:
        try:
            os.makedirs(base, exist_ok=True)
            test_file = os.path.join(base, ".write_test")
            with open(test_file, "w") as f:
                f.write("x")
            os.unlink(test_file)
            return os.path.join(base, "ai-assistant.sock")
        except OSError:
            continue

    # 全部失败，回退到 /tmp
    base = "/tmp"
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "ai-assistant.sock")


class Server:
    def __init__(self, on_command):
        self.on_command = on_command
        self._srv = None
        self._thread = None

    def start(self):
        path = socket_path()
        # 清理残留的 socket 文件
        if os.path.exists(path):
            try:
                os.unlink(path)
                print(f"[IPC] 清理残留 socket: {path}", flush=True)
            except OSError:
                pass
        try:
            self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._srv.bind(path)
            self._srv.listen(8)
            print(f"[IPC] Server 启动成功: {path}", flush=True)
        except OSError:
            print(f"[IPC] Server 启动失败: {path}", flush=True)
            self._srv = None
            return False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        if self._srv:
            try:
                self._srv.close()
            except OSError:
                pass
            self._srv = None

    def _run(self):
        while self._srv:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            data = conn.recv(4096).decode("utf-8", "replace")
            print(f"[IPC] 收到命令: {data!r}", flush=True)
            self.on_command(data)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass


class Client:
    @staticmethod
    def send(command, timeout=1.5):
        path = socket_path()
        if not os.path.exists(path):
            print(f"[IPC] socket 不存在: {path}", flush=True)
            return False
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect(path)
            s.sendall(command.encode("utf-8"))
            s.close()
            print(f"[IPC] 命令发送成功: {command!r}", flush=True)
            return True
        except OSError as e:
            print(f"[IPC] 命令发送失败: {e}", flush=True)
            try:
                s.close()
            except OSError:
                pass
            return False
