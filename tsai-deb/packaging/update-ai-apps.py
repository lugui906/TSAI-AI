#!/usr/bin/env python3
"""把 AI 应用归类到应用菜单的『AI应用』文件夹（dconf 键文件写入 + dconf update）。

原理（dconf 系统库，无需 GSettings 会话）：
  * 扫描 desktop 文件，识别 AI 应用；
  * 把结果写成 dconf 键文件 /etc/dconf/db/local.d/10-ai-apps.dconf；
  * 运行 dconf update 编译进系统库，所有用户生效。

涉及 key：
  * org.gnome.desktop.app-folders        —— 定义文件夹及成员
  * org.gnome.shell.app-picker-layout    —— 控制文件夹/应用在网格中的位置

用法: python3 update-ai-apps.py
   脚本先在当前用户下读取现有 dconf 布局，再自动用 sudo 以 root 写入键文件。
   改完打开活动概览即可看到『AI应用』文件夹。
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from gi.repository import GLib

FOLDER_ID = "ai-apps"
FOLDER_NAME = "AI应用"
FOLDER_KEY = f"/org/gnome/desktop/app-folders/folders/{FOLDER_ID}"

DB_DIR = "/etc/dconf/db/local.d"
KEYFILE = f"{DB_DIR}/10-ai-apps.dconf"

KEY_CHILDREN = "/org/gnome/desktop/app-folders/folder-children"
KEY_PICKER = "/org/gnome/shell/app-picker-layout"

DESKTOP_DIRS = [
    "/usr/share/applications",
    "/usr/local/share/applications",
    "~/.local/share/applications",
    "/var/lib/flatpak/exports/share/applications",
    "~/.local/share/flatpak/exports/share/applications",
    "/var/lib/snapd/desktop/applications",
]

INCLUDE_IDS = {
    "ai-assistant", "aipage", "ais", "ai-set-model", "ai-subtitle",
    "ai-voice", "org.chindows.ai-voice",
    "chin32-aicmd-executor", "chinai-tui",
    "com.local.AiAssistant",
    "com.tsai.ai-agent", "com.tsai.ai-knowledge", "com.tsai.ai-note",
    "com.tsai.ai-screen-control", "com.tsai.ai-timer", "com.tsai.chinai3",
    "com.tsai.meeting-hm", "com.tsai.meeting-hy",
    "se-model-manager", "org.chindows.se-model-manager",
    "webai", "token-monitor", "openclaw", "open_solo",
}

EXCLUDE_IDS = {"com.aipc.manager", "ibus-setup-libpinyin"}

NAME_LATIN_TOKENS = ("AI", "AIS", "AIPage", "WebAI", "ChinAI", "OpenClaw", "Token")
NAME_CN_TOKENS = ("智能", "模型", "语音", "字幕", "会议")


def expand(path):
    return Path(os.path.expanduser(path))


def desktop_names(path):
    names = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            in_entry = False
            for raw in fh:
                line = raw.strip()
                if line.startswith("[") and line.endswith("]"):
                    in_entry = line == "[Desktop Entry]"
                    continue
                if not in_entry or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                if key == "Name" or key.startswith("Name["):
                    names.append(val.strip())
    except OSError:
        pass
    return names


def discover_apps():
    apps = {}
    seen = set()
    for d in DESKTOP_DIRS:
        for f in sorted(expand(d).glob("*.desktop")):
            did = f.stem
            if did in seen:
                continue
            apps[did] = desktop_names(f)
            seen.add(did)
    return apps


def is_ai_app(did, names):
    if did in EXCLUDE_IDS:
        return False
    if did in INCLUDE_IDS:
        return True
    if (did.startswith("ai-") or did.startswith("chin32-")
            or "chinai" in did or did.startswith("webai")
            or did.startswith("com.tsai.ai-") or did.startswith("com.tsai.meeting-")
            or did.startswith("com.tsai.chinai")):
        return True
    for n in names:
        for tok in NAME_LATIN_TOKENS:
            if re.search(r"(^|[^A-Za-z0-9])" + re.escape(tok) + r"([^A-Za-z0-9]|$)", n):
                return True
        for tok in NAME_CN_TOKENS:
            if tok in n:
                return True
    return False


def dconf_read(key):
    cmd = ["dconf", "read", key]
    if os.geteuid() == 0 and os.environ.get("SUDO_USER"):
        cmd = ["sudo", "-Hu", os.environ["SUDO_USER"], *cmd]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def current_folder_children():
    txt = dconf_read(KEY_CHILDREN)
    if not txt:
        return []
    try:
        return list(GLib.Variant.parse(GLib.VariantType.new("as"), txt).unpack())
    except GLib.Error:
        return []


def current_picker_pages():
    txt = dconf_read(KEY_PICKER)
    if not txt:
        return [{}]
    try:
        v = GLib.Variant.parse(GLib.VariantType.new("aa{sv}"), txt)
    except GLib.Error:
        return [{}]
    pages = []
    for i in range(v.n_children()):
        d = v.get_child_value(i).unpack()
        pages.append({k: vv["position"] for k, vv in d.items()})
    return pages or [{}]


def var_str_list(items):
    if not items:
        return "@as []"
    return "[" + ", ".join(f"'{i}'" for i in items) + "]"


def picker_text(pages):
    chunks = []
    for page in pages:
        inner = ", ".join(f"'{k}': <{{'position': <{v}>}}>" for k, v in page.items())
        chunks.append("{" + inner + "}")
    return "[" + ", ".join(chunks) + "]"


def picker_pages_for(ids):
    ai_ids = {f"{i}.desktop" for i in ids}
    pages = current_picker_pages()
    old_pos = None
    clean = []
    for page in pages:
        mapping = {}
        for k, v in page.items():
            if k == FOLDER_ID:
                old_pos = v
            elif k not in ai_ids:
                mapping[k] = v
        clean.append(mapping)
    if not clean:
        clean = [{}]
    if old_pos is None:
        positions = [v for k, v in clean[0].items()]
        old_pos = max(positions) + 1 if positions else 5
    clean[0][FOLDER_ID] = old_pos
    return clean


def build_keyfile(children, ids, pages):
    parts = [
        "# 由 update-ai-apps.py 自动生成，请勿手改（重新生成: python3 update-ai-apps.py）",
        "",
        f"[{FOLDER_KEY[1:]}]",
        f"name='{FOLDER_NAME}'",
        "translate=false",
        "apps=" + var_str_list([f"{i}.desktop" for i in ids]),
        "categories=@as []",
        "excluded-apps=@as []",
        "",
        "[org/gnome/desktop/app-folders]",
        "folder-children=" + var_str_list(children),
        "",
        "[org/gnome/shell]",
        "app-picker-layout=" + picker_text(pages),
    ]
    return "\n".join(parts) + "\n"


def collect():
    apps = discover_apps()
    ai = {did: names for did, names in apps.items() if is_ai_app(did, names)}
    ids = sorted(ai)
    children = current_folder_children()
    if FOLDER_ID not in children:
        children.append(FOLDER_ID)
    pages = picker_pages_for(ids)
    return {"ids": ids, "children": children, "pages": pages}


def apply(data):
    ids, children, pages = data["ids"], data["children"], data["pages"]
    os.makedirs(DB_DIR, exist_ok=True)
    with open(KEYFILE, "w", encoding="utf-8") as fh:
        fh.write(build_keyfile(children, ids, pages))
    subprocess.run(["dconf", "update"], check=True)
    print(f"已写入键文件 {KEYFILE}")
    print(f"『{FOLDER_NAME}』文件夹成员（{len(ids)} 个）：")
    for i in ids:
        print(f"  - {i}.desktop")
    print("dconf update 完成；打开活动概览即可看到『AI应用』文件夹。")


def main():
    if os.geteuid() == 0:
        payload = sys.argv[1] if len(sys.argv) > 1 and os.path.exists(sys.argv[1]) else None
        if payload:
            with open(payload, encoding="utf-8") as fh:
                data = json.load(fh)
            os.unlink(payload)
        else:
            data = collect()
        apply(data)
        return
    data = collect()
    fd, tmp = tempfile.mkstemp(prefix="ai-apps-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.execvp("sudo", ["sudo", sys.executable, os.path.abspath(__file__), tmp])


if __name__ == "__main__":
    main()
