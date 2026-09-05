"""WebKit GTK4 套壳启动器 + Flask 服务启动。

- run():        自带独立 Flask 服务（每个窗口独立进程/后端，支持多开）。
- run_shared(): 连接共享 host 守护进程（chindshell/host.py）——多窗口会共享
                 后端状态，如需独立会话请改用 run()。

多开方案：窗口用普通 Gtk.Window + GLib.MainLoop（不用 Gtk.Application，
避免同 application_id 的 DBus 单实例秒退）。任务栏按 prgname(WMClass) 分组。
"""
import os
import random
import socket
import subprocess
import sys
import threading
import time
import urllib.request


CTX_MENU_JS = r'''
(function(){
  if (window.__ctxMenuInit) return;
  window.__ctxMenuInit = true;
  var menu = null;
  function ensureMenu(){
    if (menu) return menu;
    menu = document.createElement("div");
    menu.style.cssText = "position:fixed;z-index:999999;min-width:150px;background:rgba(255,255,255,.97);"
      +"border:1px solid rgba(0,0,0,.08);border-radius:10px;box-shadow:0 10px 34px rgba(0,0,0,.22);"
      +"padding:5px;font:13px/1.5 -apple-system,Noto Sans SC,Microsoft YaHei,system-ui,sans-serif;"
      +"color:#1a1d21;display:none;user-select:none;";
    menu.addEventListener("contextmenu", function(e){ e.preventDefault(); e.stopPropagation(); });
    document.body.appendChild(menu);
    return menu;
  }
  function hide(){ if (menu) menu.style.display="none"; }
  function addItem(label, fn, danger){
    var el = menu.querySelector("div");
    var b = document.createElement("div");
    b.style.cssText = "padding:7px 14px;border-radius:7px;cursor:pointer;white-space:nowrap;"+(danger?"color:#dc2626;":"");
    b.textContent = label;
    b.addEventListener("click", function(e){ e.stopPropagation(); hide(); fn(); });
    b.addEventListener("mouseenter", function(){ b.style.background="rgba(30,136,229,.12)"; });
    b.addEventListener("mouseleave", function(){ b.style.background="transparent"; });
    el.appendChild(b);
  }
  function show(x, y){
    var m = ensureMenu();
    m.innerHTML = "<div style='display:flex;flex-direction:column;min-width:140px;'></div>";
    var sel = window.getSelection ? window.getSelection().toString() : "";
    var selText = sel && sel.trim();
    function copySel(){
      if (!selText) return;
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(selText);
      else { var ta=document.createElement("textarea"); ta.value=selText; document.body.appendChild(ta); ta.select(); try{document.execCommand("copy");}catch(e){} document.body.removeChild(ta); }
    }
    function copyAll(){
      var body = document.body.innerText || "";
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(body);
    }
    addItem(selText ? "复制选中" : "复制", copySel, false);
    addItem("复制全部", copyAll, false);
    var ae = document.activeElement;
    var inEdit = ae && (ae.tagName==="TEXTAREA" || ae.tagName==="INPUT" || ae.isContentEditable);
    if (inEdit) {
      addItem("粘贴", function(){
        var el = document.activeElement; if (!el) return;
        if (navigator.clipboard && navigator.clipboard.readText) {
          navigator.clipboard.readText().then(function(t){ if (!t || !el.setRangeText) return;
            var start=el.selectionStart||0, end=el.selectionEnd||0;
            el.setRangeText(t, start, end, "end");
            el.dispatchEvent(new Event("input",{bubbles:true}));
            el.dispatchEvent(new Event("change",{bubbles:true}));
          }, function(){});
        }
      }, false);
    }
    addItem("全选", function(){
      var ae = document.activeElement;
      if (ae && (ae.tagName==="TEXTAREA" || ae.tagName==="INPUT")) { ae.select(); }
      else if (window.getSelection) { var r=document.createRange(); r.selectNodeContents(document.body); var s=window.getSelection(); s.removeAllRanges(); s.addRange(r); }
    }, false);
    m.style.display="block";
    var vw=window.innerWidth, vh=window.innerHeight;
    var ox=Math.min(x, vw-168-8), oy=Math.min(y, vh-m.offsetHeight-8);
    m.style.left=ox+"px"; m.style.top=oy+"px";
  }
  document.addEventListener("contextmenu", function(e){
    e.preventDefault(); e.stopPropagation(); show(e.clientX, e.clientY); return false;
  }, true);
  document.addEventListener("click", function(){ hide(); }, true);
  document.addEventListener("scroll", function(){ hide(); }, true);
  window.addEventListener("blur", function(){ hide(); }, true);
})();
'''

def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _rand_gradient(dark=False):
    """随机生成 天蓝 → 粉色 渐变。

    浅色：chinai3 同款浅天蓝→粉；暗色：暗蓝→暗紫（与主题深色设计一致）。
    """
    if dark:
        sky = f"hsl({random.randint(210, 235)}, {random.randint(35, 55)}%, {random.randint(24, 32)}%)"
        pink = f"hsl({random.randint(315, 345)}, {random.randint(35, 55)}%, {random.randint(26, 34)}%)"
    else:
        sky = f"hsl({random.randint(185, 210)}, {random.randint(30, 48)}%, {random.randint(88, 94)}%)"
        pink = f"hsl({random.randint(325, 350)}, {random.randint(34, 52)}%, {random.randint(92, 97)}%)"
    angle = random.randint(0, 359)
    return (sky, pink), angle


def _host_up(port):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1).close()
        return True
    except Exception:
        return False


def _ensure_host(port=19400):
    if _host_up(port):
        return
    env = dict(os.environ)
    env["PYTHONPATH"] = "/usr/chindows" + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.Popen([sys.executable, "-m", "chindshell.host"], env=env,
                     start_new_session=True)
    for _ in range(100):
        time.sleep(0.2)
        if _host_up(port):
            return


def _window(prgname, title, icon, url, width, height, min_w, min_h):
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("WebKit", "6.0")
    from gi.repository import Gdk, GLib, Gtk, WebKit

    try:
        from chindows_theme import style as chstyle
    except ImportError:
        chstyle = None

    GLib.set_prgname(prgname)
    if icon:
        Gtk.Window.set_default_icon_name(icon)

    light_colors, angle = _rand_gradient(False)
    dark_colors, _a = _rand_gradient(True)
    if chstyle is not None:
        chstyle.apply_gtk4()
        try:
            native = dark_colors if chstyle.detect_dark_mode() else light_colors
        except Exception:
            native = light_colors
        chstyle.apply_gradient_gtk4(colors=native, angle=angle)
    print(f"[{title}] 服务: {url} | 渐变(浅): {light_colors[0]}→{light_colors[1]} (暗): {dark_colors[0]}→{dark_colors[1]}", flush=True)

    lsky, lpink = light_colors
    dsky, dpink = dark_colors
    grad_js = (
        "(function(){"
        "function apply(dark){"
        "var s=dark?%r:%r,p=dark?%r:%r;"
        "var r=document.documentElement.style;"
        "r.setProperty('--sky',s);r.setProperty('--pink',p);"
        "r.setProperty('--bg-angle',%r);"
        "}"
        "var m=matchMedia('(prefers-color-scheme: dark)');"
        "apply(m.matches);"
        "if(m.addEventListener){m.addEventListener('change',function(e){apply(e.matches)})}"
        "else if(m.addListener){m.addListener(function(e){apply(e.matches)})}"
        "})()"
    ) % (dsky, lsky, dpink, lpink, f"{angle}deg")

    loop = GLib.MainLoop()
    win = Gtk.Window(title=title)
    win.set_default_size(width, height)
    win.set_size_request(min_w, min_h)
    settings = WebKit.Settings()
    settings.set_javascript_can_open_windows_automatically(False)
    settings.set_enable_back_forward_navigation_gestures(False)
    web = WebKit.WebView(settings=settings)
    web.set_background_color(Gdk.RGBA(0, 0, 0, 0))

    def on_load(w, event):
        if event == WebKit.LoadEvent.FINISHED:
            w.evaluate_javascript(grad_js, -1, None, None, None, None, None)
            w.evaluate_javascript(CTX_MENU_JS, -1, None, None, None, None, None)

    web.connect("load-changed", on_load)
    web.load_uri(url)
    win.set_child(web)

    win.connect("close-request", lambda w: (loop.quit(), False)[1])
    win.present()
    loop.run()


def run(app_id, prgname, title, icon, server_module,
        width=980, height=680, min_w=760, min_h=500):
    """独立 Flask 服务（每个窗口独立进程/后端，支持多开）。"""
    port = _free_port()
    url = f"http://127.0.0.1:{port}/"
    t = threading.Thread(
        target=lambda: server_module.app.run(host="127.0.0.1", port=port, threaded=True),
        daemon=True,
    )
    t.start()
    time.sleep(0.9)
    _window(prgname, title, icon, url, width, height, min_w, min_h)


def run_shared(app_id, prgname, title, icon, route, host_port=19400,
               width=980, height=680, min_w=760, min_h=500):
    """连接共享 host（chindshell.host）。注意：多窗口会共享后端状态。"""
    _ensure_host(host_port)
    url = f"http://127.0.0.1:{host_port}/{route.lstrip('/')}/"
    _window(prgname, title, icon, url, width, height, min_w, min_h)
