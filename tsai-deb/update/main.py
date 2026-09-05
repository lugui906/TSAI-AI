#!/usr/bin/env python3

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gtk, Gdk, GLib
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

import subprocess
import threading

class ChindowsUpdateWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="TSAI-OS更新")
        self.set_default_size(450, 250)
        hb = Gtk.HeaderBar()
        hb.set_show_title_buttons(True)
        hb.set_title_widget(Gtk.Label(label="TSAI-OS更新"))
        self.set_titlebar(hb)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        vbox.set_margin_top(20)
        vbox.set_margin_bottom(20)
        vbox.set_margin_start(24)
        vbox.set_margin_end(24)
        vbox.set_valign(Gtk.Align.CENTER)
        self.set_child(vbox)

        title = Gtk.Label()
        title.set_markup("<span size='xx-large'>更新TSAI-OS</span>")
        title.add_css_class("heading")
        vbox.append(title)

        self.status_label = Gtk.Label(label="随时准备更新")
        self.status_label.add_css_class("dim-label")
        vbox.append(self.status_label)

        btn_sys = Gtk.Button(label="1. 系统更新")
        btn_sys.set_size_request(220, 42)
        btn_sys.add_css_class("suggested-action")
        btn_sys.connect("clicked", self.on_sys_update)
        vbox.append(btn_sys)

        btn_feat = Gtk.Button(label="2. 功能更新")
        btn_feat.set_size_request(220, 42)
        btn_feat.connect("clicked", self.on_feat_update)
        vbox.append(btn_feat)

        self.stop_btn = Gtk.Button(label="停止")
        self.stop_btn.set_size_request(220, 42)
        self.stop_btn.set_sensitive(False)
        self.stop_btn.add_css_class("destructive-action")
        self.stop_btn.connect("clicked", self.on_stop_update)
        vbox.append(self.stop_btn)

        self.spinner = Gtk.Spinner()
        vbox.append(self.spinner)

        self.stop_event = threading.Event()
        self.current_proc = None
        self.log_dialog = None
        self.log_buffer = None

    def on_stop_update(self, button):
        self.stop_event.set()
        if self.current_proc is not None:
            try:
                self.current_proc.kill()
            except Exception:
                pass
        self.status_label.set_text("正在停止更新...")

    def show_upgrade_dialog(self, package_list, on_result):
        dialog = Gtk.Dialog(title="可更新的软件包", transient_for=self)
        dialog.set_default_size(500, 350)
        dialog.add_button("取消", Gtk.ResponseType.CANCEL)
        dialog.add_button("开始更新", Gtk.ResponseType.OK)

        vbox = dialog.get_content_area()
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        vbox.set_spacing(8)
        label = Gtk.Label(label="以下软件包可更新：")
        label.set_halign(Gtk.Align.START)
        vbox.append(label)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_vexpand(True)

        textview = Gtk.TextView()
        textview.set_editable(False)
        textview.set_wrap_mode(Gtk.WrapMode.WORD)
        textview.set_monospace(True)
        buf = textview.get_buffer()
        buf.set_text(package_list if package_list else "没有可更新的软件包")

        sw.set_child(textview)
        vbox.append(sw)

        dialog.connect("response", self.on_upgrade_response, on_result)
        dialog.present()

    def on_upgrade_response(self, dialog, response, on_result):
        proceed = response == Gtk.ResponseType.OK
        dialog.destroy()
        on_result(proceed)

    def show_log_dialog(self, title_text):
        dialog = Gtk.Dialog(title=title_text, transient_for=self)
        dialog.set_default_size(650, 400)
        dialog.add_button("完成", Gtk.ResponseType.OK)

        vbox = dialog.get_content_area()
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        vbox.set_spacing(8)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_vexpand(True)

        textview = Gtk.TextView()
        textview.set_editable(False)
        textview.set_wrap_mode(Gtk.WrapMode.WORD)
        textview.set_monospace(True)
        self.log_buffer = textview.get_buffer()

        sw.set_child(textview)
        vbox.append(sw)

        dialog.connect("response", self.on_log_response)
        dialog.present()
        return dialog

    def on_log_response(self, dialog, response):
        dialog.destroy()
        self.log_buffer = None

    def append_log(self, text):
        if self.log_buffer:
            end_iter = self.log_buffer.get_end_iter()
            self.log_buffer.insert(end_iter, text)

    def on_sys_update(self, button):
        def check_updates():
            GLib.idle_add(self.status_label.set_text, "正在检查更新...")
            GLib.idle_add(self.spinner.start)
            try:
                subprocess.run(["pkexec", "apt", "update"], capture_output=True, text=True)
                result = subprocess.run(
                    ["pkexec", "apt", "list", "--upgradable"],
                    capture_output=True, text=True
                )
                pkg_list = result.stdout

                GLib.idle_add(self.spinner.stop)
                GLib.idle_add(self.status_label.set_text, "检查完成")
                GLib.idle_add(self.show_upgrade_dialog, pkg_list, self.on_upgrade_choice)
            except Exception as e:
                GLib.idle_add(self.status_label.set_text, f"错误: {e}")
                GLib.idle_add(self.spinner.stop)

        threading.Thread(target=check_updates, daemon=True).start()

    def on_upgrade_choice(self, proceed):
        if not proceed:
            self.status_label.set_text("已取消更新")
            return
        self.status_label.set_text("正在系统更新...")
        self.spinner.start()
        self.stop_btn.set_sensitive(True)
        self.show_log_dialog("系统更新日志")
        self.run_upgrade()

    def run_upgrade(self):
        cmds = [
            ["pkexec", "apt", "--fix-broken", "install", "-y"],
            ["pkexec", "apt", "upgrade", "-y"],
        ]

        def work():
            success = True
            for cmd in cmds:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1
                )
                self.current_proc = proc
                for line in iter(proc.stdout.readline, ''):
                    if self.stop_event.is_set():
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        break
                    GLib.idle_add(self.append_log, line)
                proc.wait()
                if proc.returncode != 0:
                    success = False
                    break
            GLib.idle_add(self.finish_up, success)

        threading.Thread(target=work, daemon=True).start()

    def finish_up(self, success):
        if self.stop_event.is_set():
            self.status_label.set_text("更新已停止")
        elif success:
            self.status_label.set_text("系统更新完成")
        else:
            self.status_label.set_text("更新失败（请查看日志）")
        self.spinner.stop()
        self.stop_btn.set_sensitive(False)
        self.stop_event.clear()
        self.current_proc = None

    def on_feat_update(self, button):
        def run():
            GLib.idle_add(self.status_label.set_text, "正在获取功能更新...")
            GLib.idle_add(self.spinner.start)
            try:
                subprocess.run(["xdg-open", "https://lugui906.github.io/up"], check=True)
                GLib.idle_add(self.status_label.set_text, "功能更新已完成")
            except Exception as e:
                GLib.idle_add(self.status_label.set_text, f"错误: {e}")
            GLib.idle_add(self.spinner.stop)

        threading.Thread(target=run, daemon=True).start()


class ChindowsUpdateApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.chindows.update")
        self.window = None

    def do_activate(self):
        if not self.window:
            self.window = ChindowsUpdateWindow(self)
        self.window.present()


def main():
    if chstyle:
        chstyle.apply_gtk4()
    GLib.set_prgname("org.chindows.update")
    app = ChindowsUpdateApp()
    return app.run(None)


if __name__ == "__main__":
    import sys
    sys.exit(main())
