#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import subprocess
import threading
import queue
import time
import sys
import tkinter as tk
from tkinter import scrolledtext

try:
    import chindows_theme.style as chstyle
except ImportError:
    import os as _os, sys as _sys
    _d = _os.path.dirname(_os.path.abspath(__file__))
    while _d and not _os.path.isdir(_os.path.join(_d, "chindows_theme")):
        _p = _os.path.dirname(_d)
        if _p == _d:
            break
        _d = _p
    if _d:
        _sys.path.insert(0, _d)
    try:
        import chindows_theme.style as chstyle
    except Exception:
        chstyle = None

if chstyle is not None:
    P = dict(chstyle.PALETTE)
    F = chstyle.FONTS
else:
    P = dict(accent="#2d7ff9", accent_deep="#1a66e0", accent_soft="#e8f0fe",
             bg="#f4f6f9", surface="#ffffff", border="#e2e6ee",
             border_strong="#c9d2e2", text="#1b1f27", text_muted="#697386",
             ok="#16a34a", warn="#d97706", err="#dc2626")
    F = dict(ui=("Noto Sans CJK SC", 10), ui_bold=("Noto Sans CJK SC", 10, "bold"),
             small=("Noto Sans CJK SC", 9), mono=("Noto Sans Mono CJK SC", 10))

AIM = "/bin/aim"
CONFIG_DIR = os.path.expanduser("~/.huaci")
LOG_FILE = os.path.join(CONFIG_DIR, "huaci.log")
POLL_MS = 300


def log(msg):
    try:
        with open(LOG_FILE, "a") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + str(msg) + "\n")
    except Exception:
        pass


def read_primary():
    # 优先用 xclip 读 X11 primary：wl-paste 每次读取都会让 Mutter 抛出
    # meta_window_set_stack_position_no_sync 断言，导致任务栏疯狂跳动
    try:
        p = subprocess.run(
            ["xclip", "-o", "-selection", "primary"],
            capture_output=True, timeout=1.0,
        )
        if p.returncode == 0:
            return p.stdout.decode("utf-8", errors="replace")
        return None
    except FileNotFoundError:
        pass
    except Exception:
        return None
    try:
        p = subprocess.run(
            ["wl-paste", "--primary", "-n"],
            capture_output=True, timeout=1.0,
        )
        if p.returncode == 0:
            return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        pass
    return None


def run_aim(mode, message, result_queue, stop_event=None, proc_holder=None):
    try:
        cmd = [AIM, mode]
        cmd.append(message)
        log("call: " + " ".join(cmd))
        p = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=dict(os.environ, LANG="C.UTF-8"),
        )
        if proc_holder is not None:
            proc_holder[0] = p
        out, err = p.communicate(timeout=1800)
        if proc_holder is not None:
            proc_holder[0] = None
        if stop_event is not None and stop_event.is_set():
            out = ""
        if not out:
            out = (err or "").strip()
        if not out:
            out = "(无输出，退出码 %d)" % p.returncode
        log("done rc=%d len=%d" % (p.returncode, len(out)))
    except Exception as e:
        out = "执行出错: %s" % e
        log("error: %s" % e)
    result_queue.put(out)


def stop_aim_proc(proc_holder, stop_event):
    stop_event.set()
    proc = proc_holder[0] if proc_holder else None
    if proc is not None:
        try:
            proc.kill()
        except Exception:
            pass


class HuaciApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.last_primary = None
        self.selected_text = ""
        self.btn_pos = (100, 100)
        self.cmd_queue = queue.Queue()
        self.dialog = None
        self.busy = False
        self.hide_after_id = None
        self.HIDE_MS = 3000
        self._stop_event = None
        self._proc_holder = None

        self.btn = tk.Toplevel(self.root)
        self.btn.overrideredirect(True)
        self.btn.attributes("-topmost", True)
        self.btn.attributes("-alpha", 0.95)
        self.btn.configure(bg=P["accent_deep"])
        self.btn_label = tk.Label(
            self.btn, text="AI", fg="white", bg=P["accent"],
            font=(F["ui"][0], 11, "bold"), padx=12, pady=5,
            cursor="hand2",
            highlightthickness=2,
            highlightbackground=P["accent_deep"],
            highlightcolor=P["accent_deep"],
        )
        self.btn_label.pack()
        self.btn_label.bind("<Button-1>", lambda e: self.open_dialog())
        self.btn.withdraw()

        worker = threading.Thread(target=self.poll_worker, daemon=True)
        worker.start()

        self.root.after(POLL_MS, self.poll_queue)

    def poll_worker(self):
        pending = None
        stable_since = 0.0
        while True:
            text = read_primary()
            now = time.time()
            if text is not None and text.strip():
                text = text.strip()
                if text != pending:
                    pending = text
                    stable_since = now
                elif now - stable_since >= 0.25:
                    if pending != self.last_primary:
                        self.last_primary = pending
                        self.cmd_queue.put(("select", pending))
            else:
                pending = None
                if self.last_primary is not None:
                    self.last_primary = None
                    self.cmd_queue.put(("clear", None))
            time.sleep(POLL_MS / 1000.0)

    def poll_queue(self):
        try:
            while True:
                kind, payload = self.cmd_queue.get_nowait()
                if kind == "select":
                    self.selected_text = payload
                    self.show_button()
                elif kind == "clear":
                    if not self.busy:
                        self.selected_text = ""
                        self.cancel_hide()
                        self.btn.withdraw()
                elif kind == "result":
                    self.show_result(payload)
        except queue.Empty:
            pass
        self.root.after(POLL_MS, self.poll_queue)

    def show_button(self):
        try:
            x, y = self.btn.winfo_pointerxy()
        except Exception:
            x, y = 0, 0
        w = 120
        h = 40
        bw = self.btn.winfo_width() or 60
        bh = self.btn.winfo_height() or 28
        sx = self.btn.winfo_screenwidth()
        sy = self.btn.winfo_screenheight()
        px = min(max(x + 12, 4), sx - bw - 4)
        py = min(max(y + 14, 4), sy - bh - 4)
        self.btn.geometry("+%d+%d" % (px, py))
        self.btn.deiconify()
        self.btn.lift()
        self.cancel_hide()
        self.hide_after_id = self.root.after(self.HIDE_MS, self.hide_button)

    def cancel_hide(self):
        if self.hide_after_id is not None:
            try:
                self.root.after_cancel(self.hide_after_id)
            except Exception:
                pass
            self.hide_after_id = None

    def hide_button(self):
        self.hide_after_id = None
        if self.busy:
            return
        if self.dialog is not None and self.dialog.winfo_exists():
            return
        self.btn.withdraw()

    def open_dialog(self):
        if self.dialog is not None and self.dialog.winfo_exists():
            self.dialog.lift()
            return
        try:
            bx, by = self.btn.winfo_pointerxy()
            self.btn_pos = (bx, by)
        except Exception:
            pass
        self.cancel_hide()
        self.btn.withdraw()

        dlg = tk.Toplevel(self.root)
        self.dialog = dlg
        dlg.title("划词提问")
        dlg.attributes("-topmost", True)
        sx = dlg.winfo_screenwidth()
        sy = dlg.winfo_screenheight()
        dx = min(max(self.btn_pos[0] - 240, 10), max(10, sx - 560))
        dy = min(max(self.btn_pos[1] - 20, 10), max(10, sy - 620))
        dlg.geometry("560x620+%d+%d" % (dx, dy))
        dlg.configure(bg=P["bg"])

        ctx_label = tk.Label(dlg, text="选中内容（已加入上下文）", anchor="w",
                             bg=P["bg"], fg=P["text"], font=F["ui"])
        ctx_label.pack(fill="x", padx=12, pady=(12, 4))

        ctx = scrolledtext.ScrolledText(
            dlg, height=6, wrap="word", font=F["ui"],
            bg=P["surface"], fg=P["text"], insertbackground=P["text"],
            relief="flat", highlightthickness=1,
            highlightbackground=P["border_strong"], highlightcolor=P["accent"],
        )
        ctx.pack(fill="both", expand=True, padx=12, pady=2)
        ctx.insert("1.0", self.selected_text)
        ctx.configure(state="disabled")
        self.ctx_box = ctx

        q_label = tk.Label(dlg, text="你的问题：", anchor="w",
                           bg=P["bg"], fg=P["text"], font=F["ui"])
        q_label.pack(fill="x", padx=12, pady=(10, 4))

        self.entry = tk.Text(
            dlg, height=3, wrap="word", font=F["ui"],
            bg=P["surface"], fg=P["text"], insertbackground=P["text"],
            relief="flat", highlightthickness=1,
            highlightbackground=P["border_strong"], highlightcolor=P["accent"],
        )
        self.entry.pack(fill="both", expand=True, padx=12, pady=2)
        self.entry.focus_set()

        btns = tk.Frame(dlg, bg=P["bg"])
        btns.pack(fill="x", padx=12, pady=10)

        self.run_btn = tk.Button(
            btns, text="继续对话 (run)", command=lambda: self.send("run"),
            bg=P["accent"], fg="white", activebackground=P["accent_deep"],
            activeforeground="white", relief="flat", padx=14, pady=5,
            font=F["ui"], cursor="hand2",
        )
        self.run_btn.pack(side="left", padx=(0, 8))

        self.new_btn = tk.Button(
            btns, text="新建对话 (newrun)", command=lambda: self.send("newrun"),
            bg=P["surface"], fg=P["text"], activebackground=P["accent_soft"],
            activeforeground=P["text"], relief="flat", padx=14, pady=5,
            font=F["ui"], cursor="hand2",
            highlightthickness=1, highlightbackground=P["border_strong"],
            highlightcolor=P["border_strong"],
        )
        self.new_btn.pack(side="left")

        self.stop_btn = tk.Button(
            btns, text="停止", command=self.stop_send,
            bg=P["err"], fg="white", activebackground=P["err"],
            activeforeground="white", relief="flat", padx=14, pady=5,
            font=F["ui"], cursor="hand2",
        )
        self.stop_btn.pack(side="left", padx=(8, 0))

        self.status = tk.Label(dlg, text="", anchor="w",
                               bg=P["bg"], fg=P["text_muted"], font=F["small"])
        self.status.pack(fill="x", padx=12)

        res_label = tk.Label(dlg, text="回答：", anchor="w",
                             bg=P["bg"], fg=P["text"], font=F["ui"])
        res_label.pack(fill="x", padx=12, pady=(8, 4))

        self.result = scrolledtext.ScrolledText(
            dlg, height=10, wrap="word", font=F["ui"],
            bg=P["surface"], fg=P["text"], insertbackground=P["text"],
            relief="flat", highlightthickness=1,
            highlightbackground=P["border_strong"], highlightcolor=P["accent"],
        )
        self.result.pack(fill="both", expand=True, padx=12, pady=(2, 12))
        self.result.configure(state="disabled")

        dlg.protocol("WM_DELETE_WINDOW", self.close_dialog)

    def close_dialog(self):
        if self.busy:
            return
        if self.dialog is not None:
            self.dialog.destroy()
            self.dialog = None

    def send(self, mode):
        if self.busy:
            return
        question = self.entry.get("1.0", "end").strip()
        ctx = self.selected_text
        if not question and not ctx:
            self.status.configure(text="请输入问题或选中内容")
            return
        message = question
        if ctx and question:
            message = "以下是划词选中的内容，作为上下文：\n\n%s\n\n我的问题是：%s" % (ctx, question)
        elif ctx:
            message = "以下是划词选中的内容，请据此处理：\n\n%s" % ctx

        self.busy = True
        self.run_btn.configure(state="disabled")
        self.new_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status.configure(text="正在处理，请稍候…")
        self._stop_event = threading.Event()
        self._proc_holder = [None]
        q = queue.Queue()
        t = threading.Thread(target=run_aim,
                             args=(mode, message, q, self._stop_event, self._proc_holder),
                             daemon=True)
        t.start()

        def wait_result():
            out = q.get()
            self.cmd_queue.put(("result", out))

        threading.Thread(target=wait_result, daemon=True).start()

    def stop_send(self):
        if not self.busy:
            return
        stop_aim_proc(self._proc_holder, self._stop_event)
        self.status.configure(text="已停止")

    def show_result(self, text):
        self.busy = False
        if self.dialog is None or not self.dialog.winfo_exists():
            return
        self.run_btn.configure(state="normal")
        self.new_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        if getattr(self, "_stop_event", None) and self._stop_event.is_set():
            self.status.configure(text="已停止")
        else:
            self.status.configure(text="完成")
        self.result.configure(state="normal")
        self.result.delete("1.0", "end")
        self.result.insert("1.0", text)
        self.result.configure(state="disabled")

    def run(self):
        self.root.mainloop()


def main():
    app = HuaciApp()
    app.run()


if __name__ == "__main__":
    main()
