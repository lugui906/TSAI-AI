# -*- coding: utf-8 -*-
"""
Nautilus 扩展：在文件管理器右键菜单集成 AI 对话入口。
- 在选中文件/文件夹的右键菜单中显示 “AI 对话”
- 在空白处右键时显示 “对当前目录 AI 对话”
- 点击后启动/复用右侧 AI 对话面板，并把选中的路径作为附件传入
- 后端：aim newrun <内容> <选中路径> / aim run <内容> <选中路径>
"""
import os
import shutil
import subprocess

from gi.repository import Nautilus, GObject

CHAT_APP = os.environ.get("AI_FILE_CHAT_BIN") or shutil.which("ai-file-chat") or "/usr/local/bin/ai-file-chat"


class AIFileChatExtension(Nautilus.MenuProvider, GObject.GObject):
    def __init__(self):
        pass

    # 右键选中文件/文件夹
    def get_file_items(self, *args):
        files = args[-1]
        if not files:
            return None

        paths = []
        for f in files:
            if f.get_uri_scheme() != "file":
                return None
            location = f.get_location()
            if location is None:
                return None
            paths.append(location.get_path())

        item = Nautilus.MenuItem(
            name="AIFileChat::AskSelected",
            label="AI 对话（附带选中项）",
            tip="在右侧 AI 对话面板中把选中的文件/文件夹作为附件提问",
            icon="system-run-symbolic",
        )
        item.connect("activate", self._launch, paths)
        return [item]

    # 右键空白处
    def get_background_items(self, *args):
        window = args[-1]
        if window is None:
            return None
        folder = window.get_current_directory()
        if folder is None or folder.get_uri_scheme() != "file":
            return None
        current_dir = folder.get_path()

        item = Nautilus.MenuItem(
            name="AIFileChat::AskFolder",
            label="对当前目录 AI 对话",
            tip="把当前文件夹作为附件，在右侧 AI 对话面板中提问",
            icon="system-run-symbolic",
        )
        item.connect("activate", self._launch, [current_dir])
        return [item]

    def _launch(self, _menu, paths):
        if not os.path.isfile(CHAT_APP):
            subprocess.Popen(["zenity", "--error", "--text",
                              f"未找到 {CHAT_APP}，请先安装 ai-file-chat。"])
            return
        cmd = [CHAT_APP] + list(paths)
        subprocess.Popen(cmd, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
