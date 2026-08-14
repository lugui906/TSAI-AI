import threading
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from .models import Task
from . import storage
from .scheduler import execute_task


def _run_task_and_save(task):
    result = execute_task(task)
    task.last_result = result
    storage.update_task(task)


class MainWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="ClockAI")
        self.set_default_size(900, 600)
        self.set_border_width(0)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(vbox)

        toolbar = Gtk.Toolbar()
        toolbar.set_style(Gtk.ToolbarStyle.BOTH)

        add_btn = Gtk.ToolButton(label="添加任务")
        add_btn.set_icon_name("list-add")
        add_btn.connect("clicked", self._on_add)
        toolbar.insert(add_btn, 0)

        sep = Gtk.SeparatorToolItem()
        toolbar.insert(sep, 1)

        self.run_once_btn = Gtk.ToolButton(label="执行到期任务")
        self.run_once_btn.set_icon_name("media-playback-start")
        self.run_once_btn.connect("clicked", self._on_run_once)
        toolbar.insert(self.run_once_btn, 2)

        separator = Gtk.SeparatorToolItem()
        separator.set_draw(False)
        separator.set_expand(True)
        toolbar.insert(separator, 3)

        self.refresh_btn = Gtk.ToolButton(label="刷新")
        self.refresh_btn.set_icon_name("view-refresh")
        self.refresh_btn.connect("clicked", lambda b: self._reload())
        toolbar.insert(self.refresh_btn, 4)

        vbox.pack_start(toolbar, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_shadow_type(Gtk.ShadowType.IN)

        self.store = Gtk.ListStore(str, str, str, str, str, str, str)

        self.treeview = Gtk.TreeView(model=self.store)
        self.treeview.set_rules_hint(True)
        self.treeview.set_search_column(3)

        self.sel = self.treeview.get_selection()
        self.sel.set_mode(Gtk.SelectionMode.SINGLE)

        renderer = Gtk.CellRendererText()
        columns_info = [
            ("ID", 0, 130),
            ("时间", 1, 70),
            ("周期", 2, 90),
            ("提示词", 3, 200),
            ("启用", 4, 60),
            ("上次运行", 5, 160),
            ("结果", 6, 200),
        ]
        for title, idx, width in columns_info:
            col = Gtk.TreeViewColumn(title, renderer, text=idx)
            col.set_resizable(True)
            col.set_min_width(width)
            col.set_sort_column_id(idx)
            self.treeview.append_column(col)

        self.treeview.connect("row-activated", self._on_row_activated)

        scrolled.add(self.treeview)
        vbox.pack_start(scrolled, True, True, 0)

        action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        action_bar.set_margin_start(8)
        action_bar.set_margin_end(8)
        action_bar.set_margin_top(6)
        action_bar.set_margin_bottom(6)

        self.toggle_btn = Gtk.Button(label="禁用")
        self.toggle_btn.connect("clicked", self._on_toggle)
        action_bar.pack_start(self.toggle_btn, False, False, 0)

        edit_btn = Gtk.Button(label="编辑")
        edit_btn.connect("clicked", self._on_edit)
        action_bar.pack_start(edit_btn, False, False, 0)

        delete_btn = Gtk.Button(label="删除")
        delete_btn.get_style_context().add_class("destructive-action")
        delete_btn.connect("clicked", self._on_delete)
        action_bar.pack_start(delete_btn, False, False, 0)

        run_btn = Gtk.Button(label="立即执行")
        run_btn.connect("clicked", self._on_run_now)
        action_bar.pack_start(run_btn, False, False, 0)

        separator2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        action_bar.pack_start(separator2, False, False, 6)

        self.status_label = Gtk.Label(label="调度器: 已停止")
        self.status_label.set_margin_start(6)
        action_bar.pack_start(self.status_label, False, False, 0)

        spacer = Gtk.Label()
        action_bar.pack_end(spacer, True, True, 0)

        self.scheduler_btn = Gtk.Button(label="启动调度器")
        self.scheduler_btn.get_style_context().add_class("suggested-action")
        self.scheduler_btn.connect("clicked", self._on_toggle_scheduler)
        action_bar.pack_end(self.scheduler_btn, False, False, 0)

        vbox.pack_end(action_bar, False, False, 0)

        self.scheduler_running = False
        self._timer_id = None

        self._reload()

    def _get_selected_task(self):
        model, treeiter = self.sel.get_selected()
        if treeiter is None:
            return None
        task_id = model[treeiter][0]
        tasks = storage.load_tasks()
        for t in tasks:
            if t.id == task_id:
                return treeiter, t
        return None

    def _reload(self):
        self.store.clear()
        tasks = storage.load_tasks()
        for t in tasks:
            result_preview = (t.last_result or "")[:60]
            self.store.append([
                t.id, t.time, t.period, t.prompt,
                "是" if t.enabled else "否",
                t.last_run or "-",
                result_preview,
            ])
        self._update_toggle_btn()

    def _update_toggle_btn(self):
        result = self._get_selected_task()
        if result is None:
            self.toggle_btn.set_label("禁用")
            self.toggle_btn.set_sensitive(False)
            return
        treeiter, task = result
        self.toggle_btn.set_sensitive(True)
        self.toggle_btn.set_label("禁用" if task.enabled else "启用")

    def _on_add(self, btn):
        dialog = AddTaskDialog(self)
        dialog.run()

    def _on_edit(self, btn):
        result = self._get_selected_task()
        if result is None:
            return
        treeiter, task = result
        dialog = EditTaskDialog(self, task)
        dialog.run()

    def _on_toggle(self, btn):
        result = self._get_selected_task()
        if result is None:
            return
        treeiter, task = result
        task.enabled = not task.enabled
        storage.update_task(task)
        self._reload()

    def _on_delete(self, btn):
        result = self._get_selected_task()
        if result is None:
            return
        treeiter, task = result
        dialog = Gtk.MessageDialog(
            parent=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"确认删除任务 {task.id}?",
        )
        dialog.format_secondary_text(task.prompt[:80])
        resp = dialog.run()
        dialog.destroy()
        if resp == Gtk.ResponseType.YES:
            storage.delete_task(task.id)
            self._reload()

    def _on_run_now(self, btn):
        result = self._get_selected_task()
        if result is None:
            return
        treeiter, task = result
        self.status_label.set_text(f"执行中: {task.prompt[:40]}...")
        threading.Thread(target=self._run_task_with_feedback, args=(task,), daemon=True).start()

    def _run_task_with_feedback(self, task):
        result = execute_task(task)
        task.last_result = result
        storage.update_task(task)
        GLib.idle_add(self._show_run_result, task, result)

    def _show_run_result(self, task, msg):
        dialog = Gtk.MessageDialog(
            parent=self.get_toplevel(),
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="执行结果",
        )
        dialog.format_secondary_text(msg)
        dialog.run()
        dialog.destroy()
        self._reload()

    def _on_row_activated(self, treeview, path, col):
        result = self._get_selected_task()
        if result is None:
            return
        treeiter, task = result
        dialog = Gtk.Dialog(
            title="任务详情",
            parent=self.get_toplevel(),
            modal=True,
            buttons=(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE),
        )
        dialog.set_default_size(600, 400)
        box = dialog.get_content_area()
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_spacing(8)

        lbl1 = Gtk.Label(label=f"提示词: {task.prompt}", xalign=0)
        lbl1.set_line_wrap(True)
        box.pack_start(lbl1, False, False, 0)

        sep = Gtk.HSeparator()
        box.pack_start(sep, False, False, 0)

        lbl2 = Gtk.Label(label="结果:", xalign=0)
        box.pack_start(lbl2, False, False, 0)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_min_content_height(200)
        result_text = task.last_result or "(无结果)"
        tv = Gtk.TextView()
        tv.set_editable(False)
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.get_buffer().set_text(result_text)
        sw.add(tv)
        box.pack_start(sw, True, True, 0)

        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def _on_run_once(self, btn):
        from .scheduler import run_once
        threading.Thread(target=run_once, daemon=True).start()

    def _on_toggle_scheduler(self, btn):
        if not self.scheduler_running:
            self.scheduler_running = True
            self.status_label.set_text("调度器: 运行中")
            btn.set_label("停止调度器")
            btn.get_style_context().remove_class("suggested-action")
            btn.get_style_context().add_class("destructive-action")
            self._schedule_tick()
        else:
            self.scheduler_running = False
            self.status_label.set_text("调度器: 已停止")
            btn.set_label("启动调度器")
            btn.get_style_context().remove_class("destructive-action")
            btn.get_style_context().add_class("suggested-action")
            if self._timer_id:
                GLib.source_remove(self._timer_id)
                self._timer_id = None

    def _schedule_tick(self):
        if not self.scheduler_running:
            return
        self._timer_id = GLib.timeout_add_seconds(30, self._on_tick)

    def _on_tick(self):
        if not self.scheduler_running:
            return False
        from datetime import datetime
        now = datetime.now().replace(second=0, microsecond=0)
        tasks = storage.load_tasks()
        for task in tasks:
                if task.should_run(now):
                    task.last_run = now.isoformat()
                    storage.update_task(task)
                    threading.Thread(target=_run_task_and_save, args=(task,), daemon=True).start()
        return True


class AddTaskDialog:
    def __init__(self, parent):
        self.parent = parent
        self.dialog = Gtk.Dialog(
            title="添加任务",
            parent=parent,
            flags=Gtk.DialogFlags.MODAL,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_ADD, Gtk.ResponseType.OK),
        )
        self.dialog.set_default_size(400, 200)

        box = self.dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        grid = Gtk.Grid()
        grid.set_column_spacing(8)
        grid.set_row_spacing(8)

        grid.attach(Gtk.Label(label="提示词:", xalign=1), 0, 0, 1, 1)
        self.prompt_entry = Gtk.Entry()
        grid.attach(self.prompt_entry, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="时间 (HH:MM):", xalign=1), 0, 1, 1, 1)
        self.time_entry = Gtk.Entry()
        grid.attach(self.time_entry, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="周期:", xalign=1), 0, 2, 1, 1)
        self.period_combo = Gtk.ComboBoxText()
        periods = ["daily", "hourly", "interval:5", "interval:10", "interval:30", "interval:60"]
        for p in periods:
            self.period_combo.append_text(p)
        self.period_combo.set_active(0)
        grid.attach(self.period_combo, 1, 2, 1, 1)

        box.add(grid)
        self.dialog.show_all()
        self.dialog.connect("response", self._on_response)

    def run(self):
        self.dialog.run()

    def _on_response(self, dialog, response):
        if response == Gtk.ResponseType.OK:
            prompt = self.prompt_entry.get_text().strip()
            time_val = self.time_entry.get_text().strip()
            period = self.period_combo.get_active_text()
            if prompt and time_val:
                task = Task.create(prompt=prompt, time=time_val, period=period)
                storage.add_task(task)
                self.parent._reload()
        dialog.destroy()


class EditTaskDialog:
    def __init__(self, parent, task):
        self.parent = parent
        self.task = task
        self.dialog = Gtk.Dialog(
            title="编辑任务",
            parent=parent,
            flags=Gtk.DialogFlags.MODAL,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK),
        )
        self.dialog.set_default_size(400, 200)

        box = self.dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        grid = Gtk.Grid()
        grid.set_column_spacing(8)
        grid.set_row_spacing(8)

        grid.attach(Gtk.Label(label="提示词:", xalign=1), 0, 0, 1, 1)
        self.prompt_entry = Gtk.Entry()
        self.prompt_entry.set_text(task.prompt)
        grid.attach(self.prompt_entry, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="时间 (HH:MM):", xalign=1), 0, 1, 1, 1)
        self.time_entry = Gtk.Entry()
        self.time_entry.set_text(task.time)
        grid.attach(self.time_entry, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="周期:", xalign=1), 0, 2, 1, 1)
        self.period_combo = Gtk.ComboBoxText()
        periods = ["daily", "hourly", "interval:5", "interval:10", "interval:30", "interval:60"]
        active = 0
        for i, p in enumerate(periods):
            self.period_combo.append_text(p)
            if p == task.period:
                active = i
        self.period_combo.set_active(active)
        grid.attach(self.period_combo, 1, 2, 1, 1)

        box.add(grid)
        self.dialog.show_all()
        self.dialog.connect("response", self._on_response)

    def run(self):
        self.dialog.run()

    def _on_response(self, dialog, response):
        if response == Gtk.ResponseType.OK:
            prompt = self.prompt_entry.get_text().strip()
            time_val = self.time_entry.get_text().strip()
            period = self.period_combo.get_active_text()
            if prompt and time_val:
                self.task.prompt = prompt
                self.task.time = time_val
                self.task.period = period
                storage.update_task(self.task)
                self.parent._reload()
        dialog.destroy()


def main():
    win = MainWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
