# -*- coding: utf-8 -*-
"""chindows_theme — TSAI-OS 统一 GUI 主题加载模块。

用法（GTK3 应用）::

    import chindows_theme.style as chstyle
    chstyle.apply_gtk3()          # 在 Gtk.main() 之前调用一次即可

用法（GTK4 应用）::

    import chindows_theme.style as chstyle
    chstyle.apply_gtk4()          # 在 app.run() 之前调用

用法（tkinter 应用）::

    import chindows_theme.style as chstyle
    chstyle.apply_tk(root)        # 应用颜色/字体常量到 ttk 样式
"""
import os

_THEME_DIR = os.path.dirname(os.path.abspath(__file__))
_CSS_PATH = os.path.join(_THEME_DIR, "theme.css")

# 与 theme.css 保持一致的调色板（供 tkinter 等非 CSS 框架使用）
PALETTE = {
    "accent": "#2d7ff9",
    "accent_deep": "#1a66e0",
    "accent_soft": "#e8f0fe",
    "bg": "#f4f6f9",
    "surface": "#ffffff",
    "border": "#e2e6ee",
    "border_strong": "#c9d2e2",
    "text": "#1b1f27",
    "text_muted": "#697386",
    "ok": "#16a34a",
    "warn": "#d97706",
    "err": "#dc2626",
}

FONTS = {
    "ui": ("Noto Sans CJK SC", 10),
    "ui_bold": ("Noto Sans CJK SC", 10, "bold"),
    "small": ("Noto Sans CJK SC", 9),
    "mono": ("Noto Sans Mono CJK SC", 10),
}


def css_text() -> str:
    with open(_CSS_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _ensure_parent_on_path() -> None:
    """让本包可以从任意子目录被 import。"""
    parent = os.path.dirname(_THEME_DIR)
    if parent and parent not in __import__("sys").path:
        __import__("sys").path.insert(0, parent)


def apply_gtk3(priority=None):
    """为 GTK3 应用加载统一主题。返回 CssProvider。"""
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk

    provider = Gtk.CssProvider()
    provider.load_from_path(_CSS_PATH)
    if priority is None:
        priority = Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(screen, provider, priority)
    return provider


def apply_gtk4(priority=None):
    """为 GTK4 应用加载统一主题。返回 CssProvider。"""
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gtk, Gdk

    # GTK4 专用覆盖：window 背景圆角。
    # GTK3 的 window 圆角会渲染成黑边，所以圆角由 decoration 提供；
    # GTK4 没有 decoration 节点，圆角直接由 window.background 控制。
    css = css_text() + (
        "\n/* ---- GTK4 专用：窗口圆角 ---- */\n"
        "window.background { border-radius: 12px; }\n"
    )

    provider = Gtk.CssProvider()
    provider.load_from_data(css.encode("utf-8"))
    if priority is None:
        priority = Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(display, provider, priority)
    return provider


def apply_tk(root=None, use_ttk=True):
    """为 tkinter 应用应用统一配色。返回 PALETTE 的浅拷贝。"""
    import tkinter as tk
    from tkinter import ttk

    p = dict(PALETTE)

    def _style_ttk():
        if root is None:
            return
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        # 通用按钮
        style.configure(
            "TButton",
            background=p["accent"], foreground="#ffffff",
            bordercolor=p["accent"], lightcolor=p["accent"],
            darkcolor=p["accent_deep"], focuscolor=p["accent_soft"],
            padding=(14, 7), font=FONTS["ui"],
        )
        style.map("TButton",
                  background=[("active", p["accent_deep"]), ("disabled", "#9db9f5")],
                  bordercolor=[("active", p["accent_deep"])])
        # 次级按钮
        style.configure(
            "Secondary.TButton",
            background=p["surface"], foreground=p["text"],
            bordercolor=p["border_strong"], lightcolor=p["surface"],
            darkcolor=p["border_strong"], padding=(14, 7), font=FONTS["ui"],
        )
        style.map("Secondary.TButton",
                  background=[("active", "#eef3fb")],
                  bordercolor=[("active", p["accent"])])
        # 标签
        style.configure("TLabel", background=p["bg"], foreground=p["text"], font=FONTS["ui"])
        style.configure("Muted.TLabel", background=p["bg"], foreground=p["text_muted"], font=FONTS["small"])
        # 输入框
        style.configure(
            "TEntry",
            fieldbackground=p["surface"], foreground=p["text"],
            bordercolor=p["border_strong"], lightcolor=p["border_strong"],
            darkcolor=p["border_strong"], padding=(8, 6), font=FONTS["ui"],
        )
        style.map("TEntry",
                  bordercolor=[("focus", p["accent"])],
                  lightcolor=[("focus", p["accent"])],
                  darkcolor=[("focus", p["accent"])])
        # 滚动条
        style.configure("Vertical.TScrollbar",
                        background=p["border_strong"], troughcolor=p["bg"],
                        bordercolor=p["bg"], arrowcolor=p["text_muted"])
        style.configure("Horizontal.TScrollbar",
                        background=p["border_strong"], troughcolor=p["bg"],
                        bordercolor=p["bg"], arrowcolor=p["text_muted"])
        # 复选框 / 单选框
        style.configure("TCheckbutton", background=p["bg"], foreground=p["text"], font=FONTS["ui"])
        style.map("TCheckbutton", foreground=[("disabled", p["text_muted"])])
        style.configure("TRadiobutton", background=p["bg"], foreground=p["text"], font=FONTS["ui"])

    _style_ttk()
    return p


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if mode == "validate":
        ok = 0
        for fn, label in ((apply_gtk3, "GTK3"), (apply_gtk4, "GTK4")):
            try:
                fn()
                print(f"{label}: CSS 解析 OK")
                ok += 1
            except Exception as e:
                print(f"{label}: 解析失败 -> {e}")
        print("全部通过" if ok == 2 else "存在失败")
