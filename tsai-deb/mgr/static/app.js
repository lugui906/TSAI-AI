/* AI 电脑管家 — chinai3 风格前端（完整 12 面板） */
const $ = (s) => document.querySelector(s);
const toastEl = $("#toast");
function toast(t, ms = 2200) { toastEl.textContent = t; toastEl.classList.remove("hidden"); clearTimeout(toastEl._t); toastEl._t = setTimeout(() => toastEl.classList.add("hidden"), ms); }
async function api(url, opts = {}) { const r = await fetch(url, Object.assign({ headers: { "Content-Type": "application/json" } }, opts)); if (!r.ok) { try { const e = await r.json(); throw new Error(e.error || r.statusText); } catch (e2) { throw new Error(r.statusText); } } return r.json(); }
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const FMT = (b) => { if (b >= 1073741824) return (b / 1073741824).toFixed(1) + "G"; if (b >= 1048576) return (b / 1048576).toFixed(0) + "M"; if (b >= 1024) return (b / 1024).toFixed(0) + "K"; return b + "B"; };
const FSPD = (b) => FMT(b) + "/s";
const Pct = (p) => Math.round(p) + "%";

const MENUS = [
    { id: "aifunc", name: "🤖 AI功能" },
    { id: "disk", name: "💾 磁盘清理" },
    { id: "startup", name: "🚀 启动项" },
    { id: "aimodel", name: "📦 AI模型" },
    { id: "toolbox", name: "🧰 工具箱" },
    { id: "log", name: "📜 操作日志" },
];

const sidebar = $("#sidebar"), panelBody = $("#panelBody");
let currentPanel = "aifunc";
let timers = {};

function clearTimers() { Object.values(timers).forEach(t => clearInterval(t)); timers = {}; }
function setStatus(text, state) {
    $("#statusText").textContent = text;
    const d = $("#statusDot"); d.className = "dot" + (state === "run" ? " run" : state === "err" ? " err" : "");
}
function setIntervalSafe(key, fn, ms) { if (timers[key]) clearInterval(timers[key]); timers[key] = setInterval(fn, ms); }

function cell(k, v, bar, color) {
    return `<div class="cell"><div class="k">${esc(k)}</div><div class="v" style="${color ? "color:" + color : ""}">${esc(v)}</div>${bar !== undefined && bar !== null ? `<div class="bar"><i style="width:${Math.min(bar, 100)}%"></i></div>` : ""}</div>`;
}


/* 自动滚动：仅在用户停留在底部附近时才跟随；上翻查看历史时暂停跟随 */
const _scrollWatch = new WeakMap();
function watchAutoScroll(el) {
    if (!el || _scrollWatch.has(el)) return;
    _scrollWatch.set(el, true);
    el.addEventListener("scroll", () => {
        const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        el.dataset.autoScroll = nearBottom ? "1" : "0";
    }, { passive: true });
    el.dataset.autoScroll = "1";
}
function autoScroll(el) {
    if (!el || !el.isConnected) return;
    if (el.dataset.autoScroll !== "0") {   // 默认跟随；用户上翻后停
        el.scrollTop = el.scrollHeight;
    }
}

async function loadSys() {
    try { return await api("/api/sysinfo?_=" + Date.now()); } catch (e) { return null; }
}

/* ============ 面板渲染 ============ */
function renderPanel() {
    clearTimers();
    const p = MENUS.find(m => m.id === currentPanel);
    document.querySelectorAll("#sidebar .menu-btn").forEach(b => b.classList.toggle("active", b.dataset.p === currentPanel));
    const fn = { aifunc: renderAIfunc, disk: renderDisk, startup: renderStartup,
        aimodel: renderAImodel, toolbox: renderToolbox, log: renderLog }[currentPanel];
    fn();
}

function buildMenu() {
    sidebar.innerHTML = "";
    MENUS.forEach(m => {
        const b = document.createElement("button");
        b.className = "menu-btn"; b.dataset.p = m.id;
        b.innerHTML = `<span>${m.name}</span>`;
        b.addEventListener("click", () => { currentPanel = m.id; renderPanel(); });
        sidebar.appendChild(b);
    });
}
buildMenu();

async function startAction(key, logEl) {
    try {
        await api("/api/action", { method: "POST", body: JSON.stringify({ key }) });
        $("#stopOpBtn").classList.remove("hidden");
        setStatus("AI 正在执行…", "run");
        toast("开始执行");
        pollLog(logEl, key);
    } catch (e) { toast(e.message); }
}
function pollLog(logEl, actionKey) {
    if (timers["logpoll"]) clearInterval(timers["logpoll"]);
    timers["logpoll"] = setInterval(async () => {
        try {
            const d = await api("/api/log?_=" + Date.now());
            if (logEl && logEl.isConnected) { logEl.textContent = d.log.join("\n"); watchAutoScroll(logEl); autoScroll(logEl); }
            if (!d.running) { clearInterval(timers["logpoll"]); delete timers["logpoll"]; $("#stopOpBtn").classList.add("hidden"); setStatus(d.status || "就绪"); refreshAllPanels(); }
        } catch (e) { }
    }, 600);
}
function refreshAllPanels() {
    if (currentPanel === "log") renderLog();
}
$("#stopOpBtn").addEventListener("click", async () => { await api("/api/stop", { method: "POST" }).catch(() => { }); $("#stopOpBtn").classList.add("hidden"); toast("已停止"); });

/* ---------- 磁盘清理 ---------- */
async function renderDisk() {
    panelBody.innerHTML = `<div class="ptitle">磁盘清理</div><div id="diskList"></div>
      <div class="btn-row"><button class="chip primary" id="diskCleanBtn">🧹 AI清理磁盘</button></div>
      <div style="margin:14px 0 8px;font-weight:600;">输出</div><div class="logbox" id="diskLog">（点击 AI清理磁盘 开始）</div>`;
    const d = await loadSys(); if (!d) return;
    const list = $("#diskList"); list.innerHTML = "";
    (d.disks || []).forEach(disk => {
        const c = document.createElement("div"); c.className = "cell"; c.style.marginBottom = "8px";
        c.innerHTML = `<div class="k">${esc(disk.device)} — ${esc(disk.mountpoint)}</div>
          <div class="v" style="font-size:14px;">已用 ${disk.percent}% (${FMT(disk.used)} / ${FMT(disk.total)})</div>
          <div class="bar"><i style="width:${disk.percent}%"></i></div>`;
        list.appendChild(c);
    });
    $("#diskCleanBtn").addEventListener("click", () => startAction("clean", $("#diskLog")));
}

/* ---------- 启动项 ---------- */
async function renderStartup() {
    panelBody.innerHTML = `<div class="ptitle">启动项</div>
      <div class="hint">系统启动时自动运行的用户程序与用户服务（读取 ~/.config/autostart 与 systemd 用户服务）</div>
      <div style="overflow:auto;max-height:60vh;"><table class="data-table" id="stTable"></table></div>`;
    try {
        const d = await api("/api/startup?_=" + Date.now());
        const t = $("#stTable");
        t.innerHTML = `<tr><th>名称</th><th>路径</th><th>状态</th><th>来源</th></tr>` +
            (d.items || []).map(i => `<tr><td>${esc(i.name)}</td><td>${esc(i.path)}</td><td>${esc(i.status)}</td><td>${esc(i.source)}</td></tr>`).join("");
    } catch (e) { panelBody.innerHTML += `<div class="hint">加载失败</div>`; }
}

/* ---------- AI 功能 ---------- */
async function renderAIfunc() {
    panelBody.innerHTML = `<div class="ptitle">AI智能功能</div>
      <div class="act-grid" id="aiFuncList" style="grid-template-columns:repeat(auto-fill,minmax(180px,1fr));"></div>
      <div style="margin:16px 0 8px;font-weight:600;">实时输出</div>
      <div class="logbox big" id="aiOut"></div>`;
    const acts = [
        ["AI系统优化", "optimize"], ["AI故障诊断", "diag"], ["AI性能分析", "perf"], ["AI安全扫描", "security"],
        ["AI驱动更新", "driver"], ["AI软件管理", "soft"], ["AI网络优化", "network"], ["AI磁盘整理", "disk"],
        ["AI启动优化", "startup"], ["AI内存优化", "memory"], ["AI问题解答", "ask"],
    ];
    const l = $("#aiFuncList"); l.innerHTML = "";
    acts.forEach(([name, key]) => {
        const b = document.createElement("button"); b.className = "chip"; b.textContent = name;
        if (key === "ask") b.addEventListener("click", () => openAsk($("#aiOut")));
        else b.addEventListener("click", () => startAction(key, $("#aiOut")));
        l.appendChild(b);
    });
    refreshLogView($("#aiOut"));
    if (timers["logview"]) clearInterval(timers["logview"]);
    timers["logview"] = setInterval(() => { const el = $("#aiOut"); if (el && currentPanel === "aifunc") refreshLogView(el); }, 800);
}
async function refreshLogView(el) {
    try {
        const d = await api("/api/log?_=" + Date.now());
        if (el && el.isConnected) { el.textContent = d.log.join("\n"); watchAutoScroll(el); autoScroll(el); }
        if (!d.running) $("#stopOpBtn").classList.add("hidden");
    } catch (e) { }
}
function openAsk(logEl) {
    const q = prompt("请输入您的问题：", "例如：如何优化系统性能？");
    if (!q || !q.trim()) return;
    runAsk(q, logEl);
}
async function runAsk(q, logEl) {
    try {
        await api("/api/ask", { method: "POST", body: JSON.stringify({ question: q }) });
        toast("AI 正在回答…"); $("#stopOpBtn").classList.remove("hidden"); setStatus("AI 正在回答…", "run");
        if (timers["logpoll"]) clearInterval(timers["logpoll"]);
        timers["logpoll"] = setInterval(async () => {
            try {
                const d = await api("/api/log?_=" + Date.now());
                if (logEl && logEl.isConnected) { logEl.textContent = d.log.join("\n"); watchAutoScroll(logEl); autoScroll(logEl); }
                if (!d.running) { clearInterval(timers["logpoll"]); delete timers["logpoll"]; $("#stopOpBtn").classList.add("hidden"); setStatus(d.status || "就绪"); refreshAllPanels(); }
            } catch (e) { }
        }, 600);
    } catch (e) { toast(e.message); }
}

/* ---------- AI 模型 ---------- */
async function renderAImodel() {
    panelBody.innerHTML = `<div class="ptitle">AI模型 (Ollama)</div>
      <div class="hint">本地 Ollama 模型管理；AI 引擎模型请在「AI 模型管理器」(se) 中配置</div>
      <div style="overflow:auto;max-height:46vh;"><table class="data-table" id="omTable"></table></div>
      <div class="btn-row">
        <button class="chip" id="omRefresh">🔄 刷新模型列表</button>
        <button class="chip" id="omPull">⬇ 拉取模型</button>
        <button class="chip danger" id="omDelete">🗑 删除模型</button>
      </div>`;
    async function upd() {
        try {
            const d = await api("/api/ollama/models?_=" + Date.now());
            const t = $("#omTable");
            t.innerHTML = `<tr><th>模型名称</th><th>模型ID</th><th>大小</th></tr>` +
                d.models.map(m => `<tr><td>${esc(m.name)}</td><td>${esc(m.id)}</td><td>${esc(m.size)}</td></tr>`).join("");
        } catch (e) { }
    }
    upd();
    $("#omRefresh").addEventListener("click", upd);
    $("#omPull").addEventListener("click", async () => {
        const n = prompt("请输入模型名称（如 llama3, qwen2）", "llama3");
        if (!n || !n.trim()) return;
        try { await api("/api/ollama/pull", { method: "POST", body: JSON.stringify({ name: n.trim() }) }); toast("开始拉取 " + n); monitorCmd(); } catch (e) { toast(e.message); }
    });
    $("#omDelete").addEventListener("click", async () => {
        const n = prompt("请输入要删除的模型名称");
        if (!n || !n.trim()) return;
        if (!confirm(`确定要删除模型 ${n} 吗？`)) return;
        try { await api("/api/ollama/delete", { method: "POST", body: JSON.stringify({ name: n.trim() }) }); toast("正在删除 " + n); monitorCmd(); } catch (e) { toast(e.message); }
    });
}
function monitorCmd() {
    $("#stopOpBtn").classList.remove("hidden"); setStatus("执行中…", "run");
    if (timers["logpoll"]) clearInterval(timers["logpoll"]);
    timers["logpoll"] = setInterval(async () => {
        try {
            const d = await api("/api/log?_=" + Date.now());
            const el = $("#aiOut");
            if (!d.running) { clearInterval(timers["logpoll"]); delete timers["logpoll"]; $("#stopOpBtn").classList.add("hidden"); setStatus(d.status || "就绪"); if (currentPanel === "aimodel") renderAImodel(); }
        } catch (e) { }
    }, 800);
}

/* ---------- 工具箱 ---------- */
function renderToolbox() {
    panelBody.innerHTML = `<div class="ptitle">工具箱</div>
      <div class="tool-grid">
        <button class="chip" data-app="terminal">🖥 打开终端</button>
        <button class="chip" data-app="files">📁 文件管理器</button>
        <button class="chip" data-app="browser">🌐 浏览器</button>
        <button class="chip" data-app="settings">⚙ 系统设置</button>
        <button class="chip" data-app="monitor">📊 系统监视器</button>
      </div>`;
    document.querySelectorAll(".tool-grid .chip").forEach(b => b.addEventListener("click", async () => {
        try { await api("/api/toolbox", { method: "POST", body: JSON.stringify({ app: b.dataset.app }) }); toast("已启动"); }
        catch (e) { toast(e.message); }
    }));
}

/* ---------- 操作日志 ---------- */
async function renderLog() {
    panelBody.innerHTML = `<div class="ptitle">操作日志</div>
      <div class="row"><button class="chip danger" id="logClear">🗑️ 清空</button></div>
      <div class="logbox big" id="logMain">（暂无日志）</div>`;
    async function upd() {
        try {
            const d = await api("/api/log?_=" + Date.now());
            const el = $("#logMain");
            if (el && el.isConnected) { el.textContent = d.log.join("\n") || "（暂无日志）"; watchAutoScroll(el); autoScroll(el); }
        } catch (e) { }
    }
    upd();
    setIntervalSafe("log", upd, 1000);
    $("#logClear").addEventListener("click", async () => { try { await api("/api/stop", { method: "POST" }); } catch (e) { } });
}

/* ---------- 执行确认弹窗（全局轮询） ---------- */
const askModal = $("#askModal");
let askHandling = false;
async function pollAsk() {
    if (askHandling) return;
    try {
        const d = await api("/api/ask?_=" + Date.now());
        if (d.ask && d.ask.id) {
            askHandling = true;
            askModal.classList.remove("hidden");
            $("#askDesc").textContent = d.ask.desc || "是否执行以下操作？";
            $("#askCmd").textContent = d.ask.cmd || "";
        }
    } catch (e) { }
}
async function answerAsk(ok, all) {
    askHandling = false;
    askModal.classList.add("hidden");
    try { await api("/api/ask-answer", { method: "POST", body: JSON.stringify({ ok, all: !!all }) }); }
    catch (e) { toast(e.message); }
}
$("#askAllow").addEventListener("click", () => answerAsk(true, false));
$("#askSkip").addEventListener("click", () => answerAsk(false, false));
$("#askAll").addEventListener("click", () => answerAsk(true, true));
setInterval(pollAsk, 600);

/* ---------- 刷新按钮 & 启动 ---------- */
$("#refreshBtn").addEventListener("click", () => renderPanel());
renderPanel();
