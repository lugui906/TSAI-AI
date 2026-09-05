# -*- coding: utf-8 -*-
"""chindows_theme — TSAI-OS 统一 GUI 主题加载模块。

用法（GTK3 应用）::

    import chindows_theme.style as chstyle
    chstyle.apply_gtk3()          # 在 Gtk.main() 之前调用一次即可

用法（GTK4 应用）::

    import chindows_theme.style as chstyle
    chstyle.apply_gtk4()          # 在 app.run() 之前调用

GTK3/GTK4 的深色模式会自动跟随系统配色切换：加载时检测
`color-scheme` / `gtk-theme`，并在设置变化时实时重载样式，
无需额外代码。

用法（tkinter 应用）::

    import chindows_theme.style as chstyle
    chstyle.apply_tk(root)            # 应用颜色/字体常量到 ttk 样式
    chstyle.apply_tk(root, follow=True)  # 可选：跟随系统配色实时切换

    # 可选：强制指定配色（light / dark / None=跟随系统）
    chstyle.apply_tk(root, dark=chstyle.detect_dark_mode())

    # 切换后刷新：chstyle.apply_tk(root) 再次调用即可覆盖
"""
import os
import subprocess

_THEME_DIR = os.path.dirname(os.path.abspath(__file__))
_CSS_PATH = os.path.join(_THEME_DIR, "theme.css")

_DARK_BEGIN = "/* DARK_BEGIN */"
_DARK_END = "/* DARK_END */"

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

# 与 theme.css 深色模式块对应的深色调色板
DARK_PALETTE = {
    "accent": "#4a93ff",
    "accent_deep": "#8ab9ff",
    "accent_soft": "#243247",
    "bg": "#14161a",
    "surface": "#1d2026",
    "border": "#2b2f38",
    "border_strong": "#3a4050",
    "text": "#e7eaf0",
    "text_muted": "#99a2b3",
    "ok": "#34d399",
    "warn": "#fbbf24",
    "err": "#f87171",
}

FONTS = {
    "ui": ("Noto Sans CJK SC", 10),
    "ui_bold": ("Noto Sans CJK SC", 10, "bold"),
    "small": ("Noto Sans CJK SC", 9),
    "mono": ("Noto Sans Mono CJK SC", 10),
}


def detect_dark_mode() -> bool:
    """检测系统是否处于深色模式（GNOME/KDE/通用 gsettings）。

    优先读取 `color-scheme`，回退到 `gtk-theme`，再回退到环境变量。
    """
    # 1) org.gnome.desktop.interface color-scheme（GNOME 42+）
    try:
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True, text=True, timeout=3,
        )
        val = (out.stdout or "").strip().lower()
        if "'prefer-dark'" in val or "prefer-dark" in val:
            return True
        if val and "'default'" not in val and "default" not in val:
            return False
    except Exception:
        pass

    # 2) gtk-theme 名称含 dark / darkly / breeze-dark 等
    try:
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
            capture_output=True, text=True, timeout=3,
        )
        val = (out.stdout or "").strip().lower()
        if val and ("dark" in val or "night" in val):
            return True
    except Exception:
        pass

    # 3) 环境变量兜底
    if os.environ.get("GTK_THEME", "").lower().find("dark") != -1:
        return True

    return False


def palette(dark: bool = False) -> dict:
    """按配色模式返回调色板浅拷贝。"""
    return dict(DARK_PALETTE if dark else PALETTE)


def css_text() -> str:
    with open(_CSS_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _dark_css_block() -> str:
    """提取 DARK_BEGIN / DARK_END 之间的深色规则。

    返回未包裹 `@media` 的纯规则文本，供不支持媒体查询的 GTK3 直接追加。
    """
    block = _dark_region()
    media_idx = block.find("{")
    close_idx = block.rfind("}")
    if media_idx != -1 and close_idx != -1 and close_idx > media_idx:
        block = block[media_idx + 1:close_idx]
    return block


def _dark_region() -> str:
    """DARK_BEGIN / DARK_END 之间的原始文本（含 @media 包裹）。"""
    css = css_text()
    start = css.find(_DARK_BEGIN)
    end = css.find(_DARK_END)
    if start == -1 or end == -1 or end <= start:
        return ""
    return css[start + len(_DARK_BEGIN):end]


def _light_css_text() -> str:
    """浅色部分样式：剔除 DARK_BEGIN / DARK_END 段（GTK3 不支持 @media）。"""
    css = css_text()
    start = css.find(_DARK_BEGIN)
    end = css.find(_DARK_END)
    if start == -1 or end == -1 or end <= start:
        return css
    return css[:start] + css[end + len(_DARK_END):]


def _css_for_dark(dark: bool) -> bytes:
    """按配色模式生成完整样式字节流（不含 @media，由 Python 决定深浅）。"""
    css = _light_css_text()
    if dark:
        css += "\n/* ---- 深色模式 ---- */\n" + _dark_css_block()
    return css.encode("utf-8")


def _watch_theme_change(provider) -> None:
    """监听系统配色/主题变化，实时重载 provider 实现自动切换。

    监听 `org.gnome.desktop.interface` 的 color-scheme / gtk-theme，
    以及 `gtk-application-prefer-dark-theme`（若 schema 存在）。
    schema 不存在时静默跳过。
    """
    try:
        from gi.repository import Gio

        source = Gio.SettingsSchemaSource.get_default()
        if source is None:
            return
        schemes = (
            ("org.gnome.desktop.interface", ("color-scheme", "gtk-theme")),
            ("org.gnome.desktop.interface.gtk-settings", ("gtk-application-prefer-dark-theme",)),
        )
        keep = getattr(_watch_theme_change, "_keep", [])
        _watch_theme_change._last = detect_dark_mode()

        def _reload(*_args):
            dark = detect_dark_mode()
            if _watch_theme_change._last == dark:
                return
            _watch_theme_change._last = dark
            provider.load_from_data(_css_for_dark(dark))

        for schema_id, keys in schemes:
            schema = source.lookup(schema_id, False)
            if schema is None:
                continue
            try:
                settings = Gio.Settings.new_full(schema)
            except Exception:
                continue
            for key in keys:
                settings.connect("changed::" + key, _reload)
            keep.append(settings)
        _watch_theme_change._keep = keep
    except Exception:
        pass


def _ensure_parent_on_path() -> None:
    """让本包可以从任意子目录被 import。"""
    parent = os.path.dirname(_THEME_DIR)
    if parent and parent not in __import__("sys").path:
        __import__("sys").path.insert(0, parent)


def apply_gtk3(priority=None):
    """为 GTK3 应用加载统一主题。返回 CssProvider。

    系统配色变化时（color-scheme / gtk-theme）会自动实时重载。
    """
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk

    provider = Gtk.CssProvider()
    provider.load_from_data(_css_for_dark(detect_dark_mode()))
    if priority is None:
        priority = Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(screen, provider, priority)
    _watch_theme_change(provider)
    return provider


def apply_gtk4(priority=None):
    """为 GTK4 应用加载统一主题。返回 CssProvider。

    系统配色变化时（color-scheme / gtk-theme）会自动实时重载。
    深浅色由 Python 统一决定（不依赖 @media 求值，保证各构建一致）。
    """
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gtk, Gdk

    # GTK4 专用覆盖：window 背景圆角。
    # GTK3 的 window 圆角会渲染成黑边，所以圆角由 decoration 提供；
    # GTK4 没有 decoration 节点，圆角直接由 window.background 控制。
    css = _css_for_dark(detect_dark_mode()) + (
        "\n/* ---- GTK4 专用：窗口圆角 ---- */\n"
        "window.background { border-radius: 12px; }\n"
    ).encode("utf-8")

    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    if priority is None:
        priority = Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(display, provider, priority)
    _watch_theme_change(provider)
    return provider


def apply_tk(root=None, use_ttk=True, dark=None, follow=False):
    """为 tkinter 应用应用统一配色。

    dark: None=自动检测系统配色，True=深色，False=浅色。
    follow: True 时每 2 秒检测系统配色，变化后自动重刷 ttk 样式
            （需要 Tk 主循环运行）。返回所用调色板的浅拷贝。
    """
    from tkinter import ttk

    if dark is None:
        dark = detect_dark_mode()
    state = {"dark": bool(dark)}

    def _style_ttk():
        if root is None:
            return
        p = palette(state["dark"])
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        accent_hover = p["accent_deep"]
        active_bg = "#2b3140" if state["dark"] else "#eef3fb"
        # 通用按钮
        style.configure(
            "TButton",
            background=p["accent"], foreground="#ffffff",
            bordercolor=p["accent"], lightcolor=p["accent"],
            darkcolor=p["accent_deep"], focuscolor=p["accent_soft"],
            padding=(16, 7), font=FONTS["ui"],
        )
        style.map("TButton",
                  background=[("active", accent_hover), ("disabled", "#24406b" if state["dark"] else "#9db9f5")],
                  bordercolor=[("active", accent_hover)])
        # 次级按钮
        style.configure(
            "Secondary.TButton",
            background=p["surface"], foreground=p["text"],
            bordercolor=p["border_strong"], lightcolor=p["surface"],
            darkcolor=p["border_strong"], padding=(16, 7), font=FONTS["ui"],
        )
        style.map("Secondary.TButton",
                  background=[("active", active_bg)],
                  bordercolor=[("active", p["accent"])])
        # 标签
        style.configure("TLabel", background=p["bg"], foreground=p["text"], font=FONTS["ui"])
        style.configure("Muted.TLabel", background=p["bg"], foreground=p["text_muted"], font=FONTS["small"])
        # 输入框
        style.configure(
            "TEntry",
            fieldbackground=p["surface"], foreground=p["text"],
            bordercolor=p["border_strong"], lightcolor=p["border_strong"],
            darkcolor=p["border_strong"], padding=(10, 7), font=FONTS["ui"],
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

    def _poll():
        if root is None or not root.winfo_exists():
            return
        cur = detect_dark_mode()
        if cur != state["dark"]:
            state["dark"] = cur
            _style_ttk()
        try:
            root.after(2000, _poll)
        except Exception:
            pass

    _style_ttk()
    if follow and root is not None:
        try:
            root.after(2000, _poll)
        except Exception:
            pass
    return palette(state["dark"])


if __name__ == "__main__":
    import sys

    def _probe(kind):
        """在独立进程中探测，避免 gi 命名空间在 GTK3/GTK4 间互相污染。"""
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from chindows_theme import style as s\n"
            "s.%s()\n"
            "print('%s: CSS 解析 OK')\n"
        ) % (os.path.dirname(_THEME_DIR), kind, kind)
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

    ok = 0
    for kind in ("apply_gtk3", "apply_gtk4"):
        r = _probe(kind)
        print((r.stdout or r.stderr).strip() or f"{kind}: 未知错误")
        if r.returncode == 0:
            ok += 1
    mode = detect_dark_mode()
    print(f"系统深色模式检测: {'深色' if mode else '浅色'}")
    print("全部通过" if ok == 2 else "存在失败")
