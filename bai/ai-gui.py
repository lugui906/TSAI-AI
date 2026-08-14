#!/usr/bin/env python3
import subprocess
import threading
import re

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from aim.config import ensure_dirs
from aim.agent import list_agents, get_agent, save_agent, delete_agent

AIM_CMD = "/bin/aim"


def _run_aim(args, stdin_text):
    try:
        r = subprocess.run([AIM_CMD] + args, input=stdin_text,
                           capture_output=True, text=True, timeout=180)
        return r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        return "", "超时", -1
    except FileNotFoundError:
        return "", "找不到 /bin/aim", -1


def _parse_conv_id(stdout):
    m = re.search(r"ID: (\w+)", stdout)
    return m.group(1) if m else None


def _parse_reply(stdout, agent_name):
    return stdout.strip() or None


class AIChatApp:
    def __init__(self):
        ensure_dirs()
        self.current_agent = None
        self.conv_id = None
        self._busy = False

        self.win = Gtk.Window(title="AI Chat")
        self.win.set_default_size(860, 640)
        self.win.connect("destroy", Gtk.main_quit)

        nb = Gtk.Notebook()
        self.win.add(nb)

        self._build_agent_page(nb)
        self._build_chat_page(nb)
        self._refresh_agents()

    # ── 角色设定 ──

    def _build_agent_page(self, nb):
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vb.set_margin_start(16)
        vb.set_margin_end(16)
        vb.set_margin_top(16)
        vb.set_margin_bottom(16)
        sw.add(vb)

        vb.pack_start(Gtk.Label(label="<b>AI 角色设定</b>", use_markup=True, xalign=0),
                      False, False, 0)

        hb = Gtk.Box(spacing=8)
        hb.pack_start(Gtk.Label(label="已有角色:"), False, False, 0)
        self.combo = Gtk.ComboBoxText()
        self.combo.connect("changed", self._on_select)
        hb.pack_start(self.combo, True, True, 0)
        hb.pack_start(self._btn("删除", self._on_delete), False, False, 0)
        vb.pack_start(hb, False, False, 0)

        g = Gtk.Grid(column_spacing=8, row_spacing=6)
        vb.pack_start(g, False, False, 0)

        self.ent = {}
        g.attach(Gtk.Label(label="名称:", xalign=0), 0, 0, 1, 1)
        self.ent["name"] = Gtk.Entry()
        g.attach(self.ent["name"], 1, 0, 1, 1)
        g.attach(Gtk.Label(label="身份:", xalign=0), 0, 1, 1, 1)
        self.ent["role"] = Gtk.Entry()
        g.attach(self.ent["role"], 1, 1, 1, 1)

        g.attach(Gtk.Label(label="描述:", xalign=0), 0, 2, 1, 1)
        self.ent["description"] = Gtk.Entry()
        g.attach(self.ent["description"], 1, 2, 1, 1)

        for i, (k, lbl) in enumerate([("prompt","提示词"),("personality","性格"),
                                       ("background","背景"),("rules","规则")]):
            row = i + 3
            g.attach(Gtk.Label(label=lbl, xalign=0, valign=Gtk.Align.START), 0, row, 1, 1)
            sw2 = Gtk.ScrolledWindow()
            sw2.set_min_content_height(64)
            tv = Gtk.TextView()
            tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            buf = tv.get_buffer()
            sw2.add(tv)
            g.attach(sw2, 1, row, 1, 1)
            self.ent[k] = buf

        bb = Gtk.Box(spacing=8)
        bb.pack_start(self._btn("保存", self._on_save), False, False, 0)
        bb.pack_start(self._btn("去对话", self._on_go_chat), False, False, 0)
        vb.pack_start(bb, False, False, 0)

        self.stat = Gtk.Label(xalign=0)
        vb.pack_start(self.stat, False, False, 0)
        nb.append_page(sw, Gtk.Label(label="角色"))

    # ── 对话 ──

    def _build_chat_page(self, nb):
        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vb.set_margin_start(8)
        vb.set_margin_end(8)
        vb.set_margin_top(8)
        vb.set_margin_bottom(8)

        hb = Gtk.Box(spacing=8)
        hb.pack_start(Gtk.Label(label="角色:"), False, False, 0)
        self.lbl_agent = Gtk.Label(xalign=0)
        hb.pack_start(self.lbl_agent, True, True, 0)
        hb.pack_end(self._btn("新对话", lambda _: self._new_chat()), False, False, 0)
        vb.pack_start(hb, False, False, 0)

        self.buf = Gtk.TextBuffer()

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        tv = Gtk.TextView(buffer=self.buf)
        tv.set_editable(False)
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.set_cursor_visible(False)
        sw.add(tv)
        self.scroll = sw
        vb.pack_start(sw, True, True, 0)

        bx = Gtk.Box(spacing=4)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("输入消息...")
        self.entry.connect("activate", self._on_send)
        bx.pack_start(self.entry, True, True, 0)
        self.sbtn = Gtk.Button(label="发送")
        self.sbtn.connect("clicked", self._on_send)
        bx.pack_start(self.sbtn, False, False, 0)
        vb.pack_start(bx, False, False, 0)

        self.st = Gtk.Label(xalign=0)
        vb.pack_start(self.st, False, False, 0)
        nb.append_page(vb, Gtk.Label(label="对话"))

    # ── 工具 ──

    def _btn(self, label, cb):
        b = Gtk.Button(label=label)
        b.connect("clicked", cb)
        return b

    def _refresh_agents(self):
        self.combo.remove_all()
        self.combo.append("", "")
        for n, _ in sorted(list_agents(), key=lambda x: x[0]):
            self.combo.append(n, n)

    def _on_select(self, _c):
        n = self.combo.get_active_id()
        if n:
            a = get_agent(n)
            if a:
                self._fill_form(a)
                self.current_agent = n
        else:
            self._clear_form()
            self.current_agent = None

    def _clear_form(self):
        self.ent["name"].set_text("")
        self.ent["role"].set_text("")
        self.ent["description"].set_text("")
        for k in ("prompt","personality","background","rules"):
            self.ent[k].set_text("")

    def _fill_form(self, a):
        self.ent["name"].set_text(a.get("name",""))
        self.ent["role"].set_text(a.get("role",""))
        self.ent["description"].set_text(a.get("description",""))
        for k in ("prompt","personality","background","rules"):
            self.ent[k].set_text(a.get(k,""))

    def _form_data(self):
        d = {}
        d["role"] = self.ent["role"].get_text().strip()
        d["description"] = self.ent["description"].get_text().strip()
        for k in ("prompt","personality","background","rules"):
            b = self.ent[k]
            d[k] = b.get_text(b.get_start_iter(), b.get_end_iter(), True).strip()
        return d

    def _on_save(self, _b):
        n = self.ent["name"].get_text().strip()
        if not n:
            self.stat.set_markup('<span color="red">名称必填</span>')
            return
        save_agent(n, self._form_data())
        self.current_agent = n
        self._refresh_agents()
        self.combo.set_active_id(n)
        self.stat.set_markup(f'<span color="green">已保存 {n}</span>')

    def _on_delete(self, _b):
        n = self.combo.get_active_id()
        if not n:
            return
        d = Gtk.MessageDialog(transient_for=self.win, flags=0,
                              message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.YES_NO,
                              text=f"删除 {n}？")
        r = d.run()
        d.destroy()
        if r == Gtk.ResponseType.YES:
            delete_agent(n)
            self._refresh_agents()
            self.combo.set_active_id("")
            self._clear_form()
            self.current_agent = None

    def _on_go_chat(self, _b):
        if not self.current_agent:
            n = self.ent["name"].get_text().strip()
            if not n:
                self.stat.set_markup('<span color="red">先保存角色</span>')
                return
            self._on_save(None)
        nb = self.win.get_child()
        nb.set_current_page(1)
        self._new_chat()

    def _new_chat(self):
        self.conv_id = None
        self.buf.set_text("")
        if self.current_agent:
            self.lbl_agent.set_markup(f"<b>{self.current_agent}</b>")
        self.st.set_text("")
        self.entry.grab_focus()

    def _on_send(self, _w):
        if self._busy:
            return
        msg = self.entry.get_text().strip()
        if not msg or not self.current_agent:
            return

        self.entry.set_text("")
        self.sbtn.set_sensitive(False)
        self._busy = True

        end = self.buf.get_end_iter()
        self.buf.insert(end, f"你: {msg}\n\n")
        self.st.set_text("正在思考...")

        name = self.current_agent

        def build_persona(agent):
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

        def work():
            if self.conv_id is None:
                agent = get_agent(name)
                persona = build_persona(agent) if agent else ""
                full_msg = f"请扮演以下角色：\n{persona}\n\n用户说：{msg}" if persona else msg
                out, err, code = _run_aim(["newrun", name], full_msg)
            else:
                out, err, code = _run_aim(["run", self.conv_id], msg)
            GLib.idle_add(self._on_reply, out, err, code, name)

        threading.Thread(target=work, daemon=True).start()

    def _on_reply(self, out, err, code, name):
        self._busy = False
        self.sbtn.set_sensitive(True)

        if not out.strip():
            msg = err.strip()[:120] if err.strip() else f"退出码 {code}"
            self.st.set_markup(f'<span color="red">{msg}</span>')
            self.entry.grab_focus()
            return

        cid = _parse_conv_id(out)
        if cid and not self.conv_id:
            self.conv_id = cid
            self.lbl_agent.set_markup(f"<b>{name}</b>  ID:{cid}")

        reply = _parse_reply(out, name)
        if reply:
            end = self.buf.get_end_iter()
            self.buf.insert(end, f"{name}: {reply}\n\n")
            v = self.scroll.get_vadjustment()
            v.set_value(v.get_upper() - v.get_page_size())
            self.st.set_text("")
        else:
            self.st.set_markup(f'<span color="red">{err or "无回复"}</span>')

        self.entry.grab_focus()


if __name__ == "__main__":
    AIChatApp().win.show_all()
    Gtk.main()
