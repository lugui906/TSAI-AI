/* ================= 随机渐变背景由宿主 GTK 窗口提供（网页停用背景） ================= */

const $ = (sel) => document.querySelector(sel);

let config = { backend: "aim", engine: "chat", ollama_url: "http://localhost:11434", ollama_model: "qwen3:0.6b", aim_model: "opencode/deepseek-v4-flash-free", sidebar_open: true, ai_apps_collapsed: false };
let messages = [];
let generating = false;
let controller = null;
let multiMode = false;
let selectedMsgs = new Set();       // 消息多选
let selectedHistory = new Set();    // 历史多选
let apps = [];
let attachedFiles = [];             // [{name, path}]
let speakingEl = null;              // 正在朗读的消息元素
let sysApps = [];

const ENGINE_NAMES = { chat: "通用对话", key: "AI助手", scr: "桌面控制", auto: "自动化", schedule: "日程" };

/* ================= 控件：元素 ================= */
const msgList = $("#msgList");
const welcome = $("#welcome");
const input = $("#input");
const sendBtn = $("#sendBtn");
const stopBtn = $("#stopBtn");
const attachBtn = $("#attachBtn");
const fileBar = $("#fileBar");
const fileChips = $("#fileChips");
const modelSelect = $("#modelSelect");
const modelChip = $("#modelChip");
const modelStatus = $("#modelStatus");
const backendSeg = $("#backendSeg");
const historyList = $("#historyList");
const hDelBtn = $("#hDelBtn");
const hMultiBtn = $("#hMultiBtn");
const hClearBtn = $("#hClearBtn");
const appList = $("#appList");
const appSec = $("#appSec");
const sidebar = $("#sidebar");
const batchBar = $("#batchBar");
const selCount = $("#selCount");
const settingsModal = $("#settingsModal");
const sysAppList = $("#sysAppList");
const saveMsg = $("#saveMsg");
const toastEl = $("#toast");

/* ================= 工具 ================= */
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

function scrollBottom() { msgList.scrollTop = msgList.scrollHeight; }

function toast(text, ms = 2200) {
    toastEl.textContent = text;
    toastEl.classList.remove("hidden");
    clearTimeout(toastEl._t);
    toastEl._t = setTimeout(() => toastEl.classList.add("hidden"), ms);
}

/* 欢迎页 / 消息区 切换 */
function syncEmpty() {
    const empty = messages.length === 0;
    welcome.classList.toggle("hidden", !empty);
    msgList.classList.toggle("hidden", empty);
}

async function api(url, opts = {}) {
    const res = await fetch(url, Object.assign({ headers: { "Content-Type": "application/json" } }, opts));
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
}

/* ================= Markdown 渲染（轻量） ================= */
function renderMarkdown(text) {
    const lines = String(text).replace(/\r/g, "").split("\n");
    const html = [];
    let i = 0;
    let listType = null;
    while (i < lines.length) {
        let line = lines[i];
        if (line.trim() === "") { listType = null; i++; continue; }

        const fence = line.match(/^```(\S*)/);
        if (fence) {
            const lang = fence[1];
            const code = [];
            i++;
            while (i < lines.length && !/^```/.test(lines[i])) { code.push(lines[i]); i++; }
            i++;
            html.push(`<pre><span class="lang">${esc(lang || "code")}</span><code>${esc(code.join("\n"))}</code></pre>`);
            listType = null;
            continue;
        }

        const table = line.trim().startsWith("|");
        if (table) {
            const rows = [];
            while (i < lines.length && lines[i].trim().startsWith("|")) {
                rows.push(lines[i].trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim()));
                i++;
            }
            const header = rows[0] || [];
            const body = rows.slice(1).filter(r => !(r.length === 1 && /^[-:]+$/.test(r[0])));
            html.push("<table><thead><tr>" + header.map(c => `<th>${inline(c)}</th>`).join("") + "</tr></thead><tbody>" +
                body.map(r => `<tr>${r.map(c => `<td>${inline(c)}</td>`).join("")}</tr>`).join("") + "</tbody></table>");
            listType = null;
            continue;
        }

        const h = line.match(/^(#{1,4})\s+(.*)$/);
        if (h) { html.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); listType = null; i++; continue; }

        if (/^>\s?/.test(line)) { html.push(`<blockquote>${inline(line.replace(/^>\s?/, ""))}</blockquote>`); listType = null; i++; continue; }

        if (/^\s*[-*]\s+/.test(line)) {
            if (listType !== "ul") { html.push("<ul>"); listType = "ul"; }
            html.push(`<li>${inline(line.replace(/^\s*[-*]\s+/, ""))}</li>`);
            i++; continue;
        }
        if (/^\s*\d+[.)]\s+/.test(line)) {
            if (listType !== "ol") { html.push("<ol>"); listType = "ol"; }
            html.push(`<li>${inline(line.replace(/^\s*\d+[.)]\s+/, ""))}</li>`);
            i++; continue;
        }
        if (listType) { html.push(`</${listType}>`); listType = null; }

        if (/^(-{3,}|\*{3,})$/.test(line.trim())) { html.push("<hr>"); i++; continue; }

        html.push(`<p>${inline(line)}</p>`);
        i++;
    }
    if (listType) html.push(`</${listType}>`);
    return html.join("");
}

function inline(t) {
    let s = esc(t);
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    s = s.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
    s = s.replace(/__([^_]+)__/g, "<b>$1</b>");
    s = s.replace(/(^|[^*])\*([^*]+)\*(?!\*)/g, "$1<i>$2</i>");
    s = s.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank">$1</a>');
    return s;
}

/* ================= 消息 ================= */
function msgEl(role, content) {
    const el = document.createElement("div");
    el.className = `msg ${role}`;
    el.dataset.role = role;
    el.dataset.raw = content;
    const who = document.createElement("div");
    who.className = "who";
    who.textContent = role === "user" ? "你" : (ENGINE_NAMES[config.engine] || "ChinAI3");
    const body = document.createElement("div");
    body.className = "body";
    if (role === "assistant" && content === "") body.classList.add("streaming-cursor");
    body.innerHTML = renderMarkdown(content);
    el.append(who, body);

    const act = document.createElement("div");
    act.className = "act-row";
    if (role === "assistant") {
        act.appendChild(actBtn("🔊 朗读", () => toggleSpeak(el), false));
        act.appendChild(actBtn("重试", () => retry(el), false));
    }
    act.appendChild(actBtn("复制", () => copyText(el.dataset.raw), false));
    act.appendChild(actBtn("删除", () => delMsg(el), true));
    el.appendChild(act);
    el.addEventListener("click", (e) => {
        if (e.target.closest(".act-btn")) return;
        if (multiMode) toggleSelect(el);
    });
    return el;
}

function actBtn(label, fn, danger) {
    const b = document.createElement("button");
    b.className = `act-btn${danger ? " danger" : ""}`;
    b.textContent = label;
    b.addEventListener("click", (e) => { e.stopPropagation(); fn(); });
    return b;
}

function addMessage(role, content) {
    const el = msgEl(role, content);
    msgList.appendChild(el);
    scrollBottom();
    return el;
}

function updateMsg(el, raw, done = false) {
    el.dataset.raw = raw;
    const body = el.querySelector(".body");
    body.classList.toggle("streaming-cursor", !done && raw === "");
    body.innerHTML = renderMarkdown(raw);
    scrollBottom();
}

function delMsg(el) {
    const idx = [...msgList.children].indexOf(el);
    if (idx >= 0) messages.splice(idx, 1);
    selectedMsgs.delete(el);
    el.remove();
    refreshSelectUI();
    syncEmpty();
}

function copyText(t) {
    navigator.clipboard.writeText(t).then(() => {
        const b = sendBtn;
        const old = b.textContent;
        b.textContent = "✓";
        setTimeout(() => (b.textContent = old), 900);
    });
}

function retry(el) {
    messages.pop();
    el.remove();
    if (!messages.length) return;
    const lastUser = [...messages].reverse().find(m => m.role === "user");
    if (lastUser) send({ reuse: lastUser.content, addUser: false });
}

/* ================= 多选（消息） ================= */
function toggleSelect(el) {
    if (selectedMsgs.has(el)) { selectedMsgs.delete(el); el.classList.remove("selected"); }
    else { selectedMsgs.add(el); el.classList.add("selected"); }
    refreshSelectUI();
}
function refreshSelectUI() {
    batchBar.classList.toggle("hidden", selectedMsgs.size === 0);
    selCount.textContent = selectedMsgs.size;
}
function batchDelete() {
    for (const el of [...selectedMsgs]) {
        const idx = [...msgList.children].indexOf(el);
        if (idx >= 0) messages.splice(idx, 1);
        el.remove();
    }
    selectedMsgs.clear();
    refreshSelectUI();
    syncEmpty();
}
function batchCopy() {
    const text = [...selectedMsgs].map(el => el.dataset.raw).join("\n\n");
    copyText(text);
    selectedMsgs.clear();
    [...msgList.children].forEach(el => el.classList.remove("selected"));
    refreshSelectUI();
}

/* ================= 发送 / 流式 ================= */
async function nameConversationIfNew() {
    if (titleFetched || convTitle || config.backend === "ollama") return;
    titleFetched = true;
    const firstUser = messages.find(m => m.role === "user");
    if (!firstUser) return;
    try {
        const d = await api("/api/title", { method: "POST", body: JSON.stringify({ text: firstUser.content }) });
        if (d.title) {
            convTitle = d.title;
            updateHistorySave();
        }
    } catch (e) { /* 命名失败则用默认标题 */ }
}

async function send(opt = {}) {
    let text = opt.reuse || input.value.trim();
    const hasFiles = (opt.files || attachedFiles).length > 0;
    if ((!text && !hasFiles) || generating) return;
    // 功能#1：开启时，把活动上下文拼接进消息（不改输入框）
    if (ctxShareOn) {
        try {
            const withCtx = await appendCtxToMessage(text);
            if (withCtx && withCtx !== text) text = withCtx;
        } catch (e) {}
    }
    // 界面上下文（tine tree）：点 🌐 读取一次，下条消息自动前置给 AI
    try {
        const tk = await api("/api/ctx-tine/peek", { method: "POST" }).catch(() => null);
        if (tk && tk.ok && tk.text) {
            text = "【界面上下文（当前窗口控件树，供参考）】\n" + tk.text.slice(0, 3000) + "\n\n" + text;
        }
    } catch (e) {}
    stopSpeak();
    input.value = "";
    autosize();

    const files = opt.files || attachedFiles;
    // 文件信息并入同一条 user 消息，避免引擎只取"最后一条user"时丢失文本
    let userText = text;
    if (files.length) {
        const note = files.map(f => `📎 ${f.name}（${f.path}）`).join("\n");
        userText = text ? (text + "\n\n" + note) : note;
    }
    if (opt.addUser !== false) {
        addMessage("user", userText);
        messages.push({ role: "user", content: userText });
    }
    attachedFiles = [];
    renderFileChips();
    syncEmpty();

    const el = addMessage("assistant", "");
    generating = true;
    controller = new AbortController();
    sendBtn.classList.add("hidden");
    stopBtn.classList.remove("hidden");

    try {
        const res = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                messages,
                model: currentModel(),
                engine: config.engine,
                files: files.map(f => f.path),
            }),
            signal: controller.signal,
        });
        if (!res.ok || !res.body) throw new Error("请求失败");
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += dec.decode(value, { stream: true });
            updateMsg(el, buf, false);
        }
        updateMsg(el, buf, true);
        messages.push({ role: "assistant", content: buf });
        updateHistorySave();
        nameConversationIfNew();
    } catch (e) {
        if (e.name !== "AbortError") {
            updateMsg(el, `错误: ${e.message}`, true);
        }
    } finally {
        generating = false;
        controller = null;
        sendBtn.classList.remove("hidden");
        stopBtn.classList.add("hidden");
    }
}

async function stop() {
    if (controller) { try { controller.abort(); } catch (e) { } }
    try { await fetch("/api/stop", { method: "POST" }); } catch (e) { }
}

/* ================= 朗读 TTS ================= */
async function ttsApi(body) {
    try { await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); } catch (e) { }
}

function markSpeaking(el) {
    if (speakingEl) {
        const b = speakingEl.querySelector(".act-btn.tts");
        if (b) b.textContent = "🔊 朗读";
    }
    speakingEl = el;
    if (el) {
        const b = el.querySelector(".act-btn.tts");
        if (b) b.textContent = "⏹ 停止";
    }
}

async function toggleSpeak(el) {
    if (speakingEl === el) {
        stopSpeak();
        return;
    }
    const text = (el.dataset.raw || "").trim();
    if (!text) return;
    ttsApi({ stop: true });
    markSpeaking(el);
    ttsApi({ text });
}

function stopSpeak() {
    if (speakingEl) {
        const b = speakingEl.querySelector(".act-btn.tts");
        if (b) b.textContent = "🔊 朗读";
        speakingEl = null;
    }
    ttsApi({ stop: true });
}

/* ================= 文件上传 ================= */
function renderFileChips() {
    fileChips.innerHTML = "";
    attachedFiles.forEach((f, i) => {
        const c = document.createElement("span");
        c.className = "file-chip";
        const n = document.createElement("span");
        n.className = "n"; n.textContent = f.name;
        const x = document.createElement("button");
        x.className = "x"; x.textContent = "×";
        x.addEventListener("click", () => {
            attachedFiles.splice(i, 1);
            renderFileChips();
        });
        c.append(n, x);
        fileChips.appendChild(c);
    });
    fileBar.classList.toggle("hidden", attachedFiles.length === 0);
}

function uploadFiles(fileList) {
    if (!fileList || !fileList.length) return;
    const fd = new FormData();
    for (const f of fileList) fd.append("files", f);
    fetch("/api/upload", { method: "POST", body: fd })
        .then(r => r.json())
        .then(d => {
            const items = (d && d.files) || [];
            if (d && d.ok && items.length) {
                attachedFiles.push(...items);
                renderFileChips();
                toast(`已上传 ${items.length} 个文件`);
            } else if (d && d.error) {
                toast("上传失败: " + d.error);
            } else {
                toast("上传失败（服务器未返回文件）");
            }
        })
        .catch((e) => { console.error("[upload]", e); toast("上传失败: " + (e && e.message || "网络错误")); });
}

function pickFiles() {
    const inp = document.createElement("input");
    inp.type = "file";
    inp.multiple = true;
    inp.style.display = "none";
    document.body.appendChild(inp);   // WebKit 需在 DOM 中才能稳定弹出选择器
    inp.onchange = () => {
        if (inp.files.length) uploadFiles(inp.files);
        document.body.removeChild(inp);
    };
    inp.oncancel = () => { document.body.removeChild(inp); };
    inp.click();
}

/* ================= 历史 ================= */
let historyCache = [];
let convId = Date.now();
let convTitle = "";
let titleFetched = false;
let historyMulti = false;

function updateHistorySave() {
    if (!messages.length) return;
    api("/api/history/add", { method: "POST", body: JSON.stringify({ id: convId, title: historyTitle(), messages }) }).catch(() => { });
    refreshHistory();
}
function historyTitle() {
    if (convTitle) return convTitle;
    const u = messages.find(m => m.role === "user");
    return u ? u.content.slice(0, 40) : "对话";
}

async function refreshHistory() {
    try { historyCache = await api("/api/history"); } catch (e) { historyCache = []; }
    historyList.innerHTML = "";
    if (!historyCache.length) {
        historyList.innerHTML = '<div class="empty">暂无记录</div>';
        return;
    }
    historyCache.forEach(r => {
        const b = document.createElement("button");
        b.className = "h-item";
        b.dataset.id = r.id;
        const t = document.createElement("div");
        t.className = "t"; t.textContent = r.title;
        const m = document.createElement("div");
        m.className = "m"; m.textContent = r.time;
        b.append(t, m);
        b.addEventListener("click", () => {
            if (historyMulti) {
                if (selectedHistory.has(r.id)) { selectedHistory.delete(r.id); b.classList.remove("selected"); }
                else { selectedHistory.add(r.id); b.classList.add("selected"); }
                updateHSel();
            } else {
                loadHistory(r);
            }
        });
        historyList.appendChild(b);
    });
}

function loadHistory(r) {
    messages = (r.messages || []).map(m => ({ role: m.role, content: m.content }));
    msgList.innerHTML = "";
    messages.forEach(m => msgList.appendChild(msgEl(m.role, m.content)));
    scrollBottom();
    syncEmpty();
    if (multiMode) exitMultiMode();
    toast("已载入历史对话");
    // 自动延续对应的 AIM 会话
    if (r.session) {
        api("/api/conversation/switch-session", { method: "POST", body: JSON.stringify({ session: r.session }) })
            .then(d => { if (d.ok) addNotice("⇄ 已自动切换到对应 AIM 会话，继续输入即从该会话延续。"); })
            .catch(() => { });
    }
}

function updateHSel() {
    hDelBtn.classList.toggle("hidden", selectedHistory.size === 0);
}

async function hBatchDelete() {
    if (!selectedHistory.size) return;
    await api("/api/history/delete", { method: "POST", body: JSON.stringify({ ids: [...selectedHistory] }) });
    selectedHistory.clear();
    updateHSel();
    refreshHistory();
}

async function hClear() {
    if (!confirm("确认清空全部历史记录？")) return;
    await api("/api/history/clear", { method: "POST" });
    selectedHistory.clear();
    updateHSel();
    refreshHistory();
}

function enterHistoryMulti() {
    historyMulti = true;
    hDelBtn.classList.remove("hidden");
    hMultiBtn.textContent = "✓ 完成";
    historyList.querySelectorAll(".h-item").forEach(b => b.classList.add("selected"));
    selectedHistory = new Set(historyCache.map(r => r.id));
    updateHSel();
}
function exitHistoryMulti() {
    historyMulti = false;
    selectedHistory.clear();
    updateHSel();
    hMultiBtn.textContent = "☑ 多选";
    historyList.querySelectorAll(".h-item").forEach(b => b.classList.remove("selected"));
}

function exitMultiMode() {
    multiMode = false;
    selectedMsgs.clear();
    [...msgList.children].forEach(el => el.classList.remove("selected"));
    refreshSelectUI();
    $("#multiBtn").classList.remove("selected");
    $("#multiBtn").textContent = "☑ 多选";
}

function newChat() {
    updateHistorySave();
    convTitle = ""; titleFetched = false;
    convId = Date.now();
    stopSpeak();
    attachedFiles = [];
    renderFileChips();
    messages = [];
    msgList.innerHTML = "";
    if (multiMode) exitMultiMode();
    if (historyMulti) exitHistoryMulti();
    syncEmpty();
    fetch("/api/reset", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ engine: config.engine }) }).catch(() => { });
    input.focus();
}

/* ================= AI 应用 / 引擎 ================= */
async function loadApps() {
    try {
        const d = await api("/api/apps");
        apps = d.apps || [];
    } catch (e) { apps = []; }
    renderApps();
}

function renderApps() {
    appList.innerHTML = "";
    if (!apps.length) return;
    apps.forEach(a => {
        const b = document.createElement("div");
        b.className = `app-item${a.active && a.type === "engine" ? " selected" : ""}`;
        b.dataset.id = a.id;

        const ai = document.createElement("span");
        ai.className = "ai"; ai.textContent = a.icon;

        const n = document.createElement("span");
        n.className = "n";
        const t = document.createElement("span");
        t.className = "t"; t.textContent = a.name;
        const d = document.createElement("span");
        d.className = "d"; d.textContent = a.desc;
        n.append(t, d);

        if (a.type === "engine") {
            const open = document.createElement("button");
            open.className = "open"; open.textContent = "↗";
            open.title = "打开完整应用";
            open.addEventListener("click", (e) => { e.stopPropagation(); launchApp(a.id); });
            b.append(ai, n, open);
            b.addEventListener("click", () => setEngine(a.id));
        } else {
            b.append(ai, n);
            b.addEventListener("click", () => launchApp(a.id));
        }
        appList.appendChild(b);
    });
}

async function launchApp(id) {
    try {
        const d = await api("/api/launch", { method: "POST", body: JSON.stringify({ app: id }) });
        toast(d.ok ? `已启动 ${d.name}` : `启动失败: ${d.error}`);
    } catch (e) {
        toast(`启动失败: ${e.message}`);
    }
}

function setEngine(id) {
    if (id === config.engine) return;
    if (messages.length) {
        if (!confirm("切换引擎将开启新对话，当前对话会保存到历史记录，继续？")) return;
        updateHistorySave();
    }
    config.engine = id;
    persistConfig();
    convId = Date.now();
    convTitle = ""; titleFetched = false;
    stopSpeak();
    attachedFiles = [];
    renderFileChips();
    messages = [];
    msgList.innerHTML = "";
    if (multiMode) exitMultiMode();
    if (historyMulti) exitHistoryMulti();
    syncEmpty();
    fetch("/api/reset", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ engine: id }) }).catch(() => { });
    apps.forEach(a => { a.active = (a.id === id); });
    renderApps();
    refreshHistory();
    toast(`已切换到 ${ENGINE_NAMES[id] || "通用对话"}`);
    input.focus();
}

function updateSidebar() {
    sidebar.classList.toggle("hidden", !config.sidebar_open);
    $("#sidebarToggle").textContent = config.sidebar_open ? "☰" : "☰";
}

function toggleSidebar() {
    config.sidebar_open = !config.sidebar_open;
    persistConfig();
    updateSidebar();
}

function updateAppSec() {
    appSec.classList.toggle("collapsed", !!config.ai_apps_collapsed);
}

function toggleAppSec() {
    config.ai_apps_collapsed = !config.ai_apps_collapsed;
    persistConfig();
    updateAppSec();
}

/* ================= 模型 / 后端 ================= */
function currentModel() {
    if (modelSelect.options.length) return modelSelect.value;
    return config.backend === "ollama" ? config.ollama_model : config.aim_model;
}

async function loadModels(opts = {}) {
    const silent = opts.silent || false;
    if (modelStatus && !silent) modelStatus.textContent = "检测中…";
    try {
        const d = await api(`/api/models?backend=${config.backend}`);
        modelSelect.innerHTML = "";
        const models = d.models || [];
        const saved = currentModel();
        if (!models.length) {
            const o = document.createElement("option");
            o.value = saved; o.textContent = saved;
            modelSelect.appendChild(o);
            if (modelStatus) modelStatus.textContent = "未检测到模型，使用上次选择";
        } else {
            models.forEach(m => {
                const o = document.createElement("option");
                o.value = m; o.textContent = m;
                modelSelect.appendChild(o);
            });
            if (models.includes(saved)) modelSelect.value = saved;
            if (modelStatus) modelStatus.textContent = `已检测到 ${models.length} 个模型 · ${config.backend === "ollama" ? "Ollama" : "aim"}`;
        }
        saveCurrentModel();
    } catch (e) {
        if (modelStatus) modelStatus.textContent = "检测失败";
    }
}

function saveCurrentModel() {
    if (config.backend === "ollama") config.ollama_model = modelSelect.value;
    else config.aim_model = modelSelect.value;
    persistConfig();
    updateModelChip();
}
modelSelect.addEventListener("change", saveCurrentModel);

async function setBackend(name) {
    config.backend = name;
    persistConfig();
    backendSeg.querySelectorAll(".chip").forEach(c => c.classList.toggle("selected", c.dataset.backend === name));
    await loadModels({ silent: true });
}

async function loadEngine() {
    try {
        const d = await api("/api/aim/engine");
        updateEngineChip(d.engine);
    } catch (e) { /* 忽略 */ }
}
function updateEngineChip(engine) {
    const seg = document.getElementById("engineSeg");
    if (!seg) return;
    const e = engine === "openclaw" ? "openclaw" : "opencode";
    seg.querySelectorAll(".seg-item").forEach(b => {
        b.classList.toggle("selected", b.dataset.engine === e);
    });
}
async function toggleEngine(target) {
    const d = await api("/api/aim/engine", { method: "POST", body: JSON.stringify({ target }) });
    if (d.ok) {
        updateEngineChip(d.engine || target);
        toast(`已切换 AIM 引擎 → ${d.engine || target}`);
    } else {
        toast("引擎切换失败: " + (d.error || ""));
    }
}

function updateModelChip() {
    modelChip.textContent = `🧠 ${currentModel()}`;
    modelChip.title = `当前模型：${currentModel()}\n点击在设置中切换`;
}

/* ================= 配置 / 设置弹窗 ================= */
function persistConfig() {
    fetch("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config) }).catch(() => { });
}

function openSettings() {
    backendSeg.querySelectorAll(".chip").forEach(c => c.classList.toggle("selected", c.dataset.backend === config.backend));
    saveMsg.textContent = "";
    settingsModal.classList.remove("hidden");
    loadModels({ silent: true });
    loadSysApps();
}

function closeSettings() {
    settingsModal.classList.add("hidden");
}

function saveSettings() {
    saveCurrentModel();
    persistConfig();
    closeSettings();
    toast("设置已保存");
}

async function loadSysApps() {
    try {
        const d = await api("/api/system-ai-apps");
        sysApps = d.apps || [];
    } catch (e) { sysApps = []; }
    sysAppList.innerHTML = "";
    if (!sysApps.length) {
        sysAppList.innerHTML = '<div class="sysapp-empty">未发现带 AI 的应用</div>';
        return;
    }
    sysApps.forEach(a => {
        const row = document.createElement("div");
        row.className = "sysapp-item";
        const n = document.createElement("div");
        n.className = "n";
        const t = document.createElement("div");
        t.className = "t"; t.textContent = a.name;
        const d = document.createElement("div");
        d.className = "d"; d.textContent = a.comment || a.file;
        n.append(t, d);
        const b = document.createElement("button");
        b.className = "open"; b.textContent = "打开";
        b.addEventListener("click", () => launchSysApp(a));
        row.append(n, b);
        sysAppList.appendChild(row);
    });
}

async function launchSysApp(a) {
    try {
        const d = await api("/api/launch-sys", { method: "POST", body: JSON.stringify({ cmd: a.cmd }) });
        toast(d.ok ? `已启动 ${a.name}` : `启动失败: ${d.error}`);
    } catch (e) {
        toast(`启动失败: ${e.message}`);
    }
}

/* ================= 输入框 ================= */
function autosize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
}
input.addEventListener("input", autosize);
// 粘贴图片/文件 -> 作为附件上传（粘贴纯文本则按默认处理，不拦截）
input.addEventListener("paste", (e) => {
    const cd = e.clipboardData;
    if (!cd) return;
    // 优先取剪贴板里的文件（含截图/图片/复制文件）
    let files = [];
    if (cd.files && cd.files.length) {
        files = Array.from(cd.files);
    } else if (cd.items && cd.items.length) {
        for (const it of cd.items) {
            if (it.kind === "file") {
                const f = it.getAsFile();
                if (f) files.push(f);
            }
        }
    }
    if (files.length) {
        e.preventDefault();   // 阻止把文件路径/二进制粘进文本框
        uploadFiles(files);
        toast(`已从剪贴板取到 ${files.length} 个文件`);
    }
    // 无文件时放任默认粘贴（纯文本）
});
input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !(e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        send();
    }
});
document.querySelectorAll(".sugg-chip").forEach(c => {
    c.addEventListener("click", () => { input.value = c.dataset.q || ""; send(); });
});

/* ================= 绑定 ================= */
sendBtn.addEventListener("click", () => send());
stopBtn.addEventListener("click", stop);
attachBtn.addEventListener("click", pickFiles);
$("#newChatBtn").addEventListener("click", newChat);
$("#sidebarToggle").addEventListener("click", toggleSidebar);
$("#appSecToggle").addEventListener("click", toggleAppSec);
$("#multiBtn").addEventListener("click", () => {
    multiMode = !multiMode;
    $("#multiBtn").classList.toggle("selected", multiMode);
    $("#multiBtn").textContent = multiMode ? "✓ 完成" : "☑ 多选";
    if (!multiMode) {
        selectedMsgs.clear();
        [...msgList.children].forEach(el => el.classList.remove("selected"));
        refreshSelectUI();
    }
});
$("#batchCopy").addEventListener("click", batchCopy);
$("#batchDel").addEventListener("click", batchDelete);
$("#batchCancel").addEventListener("click", exitMultiMode);
hClearBtn.addEventListener("click", hClear);
hDelBtn.addEventListener("click", hBatchDelete);
$("#convBtn").addEventListener("click", () => {
    $("#convModal").classList.remove("hidden");
    loadConversations();
});
$("#convClose").addEventListener("click", () => $("#convModal").classList.add("hidden"));
$("#convCancel").addEventListener("click", () => $("#convModal").classList.add("hidden"));
$("#convModal").addEventListener("click", (e) => { if (e.target === $("#convModal")) $("#convModal").classList.add("hidden"); });
hMultiBtn.addEventListener("click", () => {
    if (historyMulti) exitHistoryMulti();
    else enterHistoryMulti();
});
$("#settingsBtn").addEventListener("click", openSettings);
$("#modelChip").addEventListener("click", openSettings);
document.querySelectorAll("#engineSeg .seg-item").forEach(b => {
    b.addEventListener("click", () => toggleEngine(b.dataset.engine));
});
$("#settingsClose").addEventListener("click", closeSettings);
settingsModal.addEventListener("click", (e) => { if (e.target === settingsModal) closeSettings(); });
$("#settingsSave").addEventListener("click", saveSettings);
$("#detectBtn").addEventListener("click", () => loadModels({ silent: false }));
backendSeg.addEventListener("click", (e) => {
    const c = e.target.closest(".chip");
    if (c) setBackend(c.dataset.backend);
});

/* ================= aim 会话切换 ================= */
async function loadConversations() {
    const list = $("#convList");
    try {
        const d = await api("/api/conversations");
        const convs = d.conversations || [];
        list.innerHTML = convs.length
            ? convs.map(c =>
                `<button class="h-item" data-n="${c.num}"><span class="t">#${c.num} · ${c.mode || ''} ${c.engine || ''}</span><span class="d">${c.time || ''} · ${String(c.prompt || '').slice(0, 40)}</span></button>`).join('')
            : '<div class="empty">暂无会话</div>';
        list.querySelectorAll('.h-item').forEach(b => {
            b.onclick = () => switchConversation(Number(b.dataset.n));
        });
    } catch (e) { list.innerHTML = '<div class="empty">加载失败</div>'; }
}

function addNotice(text) {
    if (!messages.length) {
        welcome.classList.add("hidden");
        msgList.classList.remove("hidden");
    }
    msgList.appendChild(msgEl("system", text));
    msgList.scrollTop = msgList.scrollHeight;
}

async function switchConversation(num) {
    newChat();   // 清空当前对话（保存本地历史 + 重置）
    const d = await api("/api/conversation/switch", { method: "POST", body: JSON.stringify({ num }) });
    if (!d.ok) { toastMsg(d.error || '切换失败'); return; }
    $("#convModal").classList.add("hidden");
    addNotice("⇄ 已切换到 aim 会话 #" + num + "，继续输入即从该会话继续。");
    toastMsg(d.msg || ("已切换到会话 #" + num));
}

/* ================= 初始化 ================= */
(async function init() {
    try {
        config = Object.assign(config, await api("/api/config"));
    } catch (e) { }
    if (!config.engine) config.engine = "chat";
    updateSidebar();
    updateAppSec();
    await loadApps();
    backendSeg.querySelectorAll(".chip").forEach(c => c.classList.toggle("selected", c.dataset.backend === config.backend));
    await loadModels({ silent: true });
    updateModelChip();
    loadEngine();
    refreshHistory();
    syncEmpty();
    input.focus();

    // 外部打开：?auto=1&msg=<urlencoded> → 自动开启新对话并发送该消息
    try {
        const q = new URLSearchParams(location.search);
        const msg = q.get("msg") || "";
        if (q.get("auto") === "1" && msg) {
            newChat();
            setTimeout(() => { send({ reuse: msg }); }, 600);
        }
    } catch (e) { }
})();



/* =============== AI 活动记录 (功能#1/#2/#3) =============== */
let ctxShareOn = false;
let actTab = "win";

async function loadCtxState() {
    try { const d = await api("/api/activity?_=" + Date.now()); ctxShareOn = !!d.ctx_share; renderCtxBtn(); } catch (e) {}
}
function renderCtxBtn() {
    const b = document.getElementById("ctxBtn");
    if (!b) return;
    b.classList.toggle("selected", ctxShareOn);
    b.textContent = ctxShareOn ? "📡 开" : "📡";
    b.title = ctxShareOn ? "发送时自动附加活动上下文（点击关闭）" : "发送时自动附加活动上下文（点击开启）";
}
async function toggleCtxShare() {
    ctxShareOn = !ctxShareOn;
    renderCtxBtn();
    try { await api("/api/ctx_share", { method: "POST", body: JSON.stringify({ on: ctxShareOn }) }); toast(ctxShareOn ? "已开启：发送时自动附加活动上下文" : "已关闭活动上下文附加"); } catch (e) { ctxShareOn = !ctxShareOn; renderCtxBtn(); toast("切换失败"); }
    updateActHint();
}
async function fetchCtxText() {
    /* 发送时拼接用的上下文文本（读 /api/context，返回 {context,brief}） */
    const min = (typeof ctxMinOn === "number" && ctxMinOn > 0) ? ctxMinOn : 10;
    const d = await api("/api/context?minutes=" + min + "&_=" + Date.now());
    const brief = (d && (d.brief || d.context)) || "";
    return brief;
}

/* ---------- 发送时拼接：把活动上下文加到用户消息前 ---------- */
async function appendCtxToMessage(text) {
    let brief = "";
    try { brief = await fetchCtxText(); } catch (e) { return text; }
    if (!brief.trim()) return text;
    return "用户需要你读取以下最近活动记录辅助分析当前请求：\n" + brief + "\n\n---- 以下为用户当前请求 ----\n" + text;
}

/* ---------- 控制面板 ---------- */
function escHtml(s) {
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function actOpen() { document.getElementById("actModal").classList.remove("hidden"); actRefresh(); }
function actClose() { document.getElementById("actModal").classList.add("hidden"); }
function setActTab(t) {
    actTab = t;
    document.querySelectorAll("#actModal .seg-item").forEach(x => x.classList.toggle("selected", x.dataset.tab === t));
    actRefresh();
}
function renderActStatus(st) {
    const dot = document.getElementById("actStatusDot");
    if (!dot) return;
    const live = st && st.running;
    const rc = st && st.event_count;
    dot.innerHTML = (live ? "🟢 记录中" : "🔴 未运行") + " · " + (rc||0) + " 条事件";
    dot.title = (st && st.last_ts) ? ("最近事件: " + st.last_ts) : "";
}
function updateActHint() {
    const h = document.getElementById("actHint");
    if (h) h.textContent = ctxShareOn ? "开启中：下一条消息将自动附带窗口/文件活动记录。" : "";
    const tg = document.getElementById("ctxShareToggle");
    if (tg) { tg.textContent = ctxShareOn ? "开" : "关"; tg.classList.toggle("selected", ctxShareOn); }
}
async function actRefresh() {
    try {
        const d = await api("/api/activity?_=" + Date.now());
        ctxShareOn = !!d.ctx_share;
        renderCtxBtn(); updateActHint(); renderActStatus(d.status);
        const list = document.getElementById("actPanelList");
        if (!list) return;
        list.innerHTML = "";
        if (actTab === "win") {
            if (!d.windows || !d.windows.length) { list.innerHTML = '<div class="empty">暂无窗口记录</div>'; return; }
            d.windows.slice().reverse().forEach(w => {
                const row = document.createElement("div");
                row.style.cssText = "display:flex;gap:6px;align-items:flex-start;padding:3px 2px;border-bottom:1px solid rgba(128,128,128,.12);";
                const state = w.state === "active" ? "🟢" : "⚪";
                row.innerHTML = `<span style="color:var(--text-2);flex:0 0 74px;font-size:11px;">${escHtml(w.ts||"").slice(11,19)}</span>` +
                    `<span style="flex:0 0 auto;">${state}</span>` +
                    `<span style="flex:1;">${escHtml(w.app||"")} · ${escHtml(w.title||"")}</span>`;
                list.appendChild(row);
            });
        } else {
            if (!d.files || !d.files.length) { list.innerHTML = '<div class="empty">暂无最近文件</div>'; return; }
            d.files.forEach(f => {
                const row = document.createElement("div");
                row.style.cssText = "display:flex;gap:6px;align-items:center;padding:4px 2px;border-bottom:1px solid rgba(128,128,128,.12);cursor:pointer;";
                row.title = "点击附加到会话，AI 将获得该文件路径：\n" + f.path;
                const icon = f.kind === "open" ? "📂" : "✏️";
                row.innerHTML = `<span>${icon}</span><span style="flex:0 0 auto;max-width:190px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escHtml(f.name||"")}</span><span style="flex:1;color:var(--text-2);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escHtml(f.path||"")}</span><span class="chip small">＋ 附加</span>`;
                row.addEventListener("click", () => { attachRecentFile(f); });
                list.appendChild(row);
            });
        }
    } catch (e) {
        const list = document.getElementById("actPanelList");
        if (list) list.innerHTML = '<div class="empty">加载失败</div>';
    }
}
function attachRecentFile(f) {
    if (!f || !f.path) return;
    const base = (f.name || f.path.split("/").pop() || "文件");
    const exists = attachedFiles.find(x => x.path === f.path);
    if (!exists) { attachedFiles.push({ name: base, path: f.path }); renderFileChips(); toast("已附加：" + base); }
    else { toast("该文件已在附加列表"); }
    actClose();
}

/* ---------- 事件绑定 ---------- */
(function initAct() {
    const ctxBtn = document.getElementById("ctxBtn");
    if (ctxBtn) ctxBtn.addEventListener("click", toggleCtxShare);
    const apb = document.getElementById("actPanelBtn");
    if (apb) apb.addEventListener("click", actOpen);
    const acl = document.getElementById("actClose");
    if (acl) acl.addEventListener("click", actClose);
    const actM = document.getElementById("actModal");
    if (actM) actM.addEventListener("click", e => { if (e.target === actM) actClose(); });
    const arf = document.getElementById("actRefresh");
    if (arf) arf.addEventListener("click", actRefresh);
    const tgs = document.getElementById("ctxShareToggle");
    if (tgs) tgs.addEventListener("click", toggleCtxShare);
    const tw = document.getElementById("actTabWin");
    if (tw) tw.addEventListener("click", () => setActTab("win"));
    const tf = document.getElementById("actTabFile");
    if (tf) tf.addEventListener("click", () => setActTab("file"));
    loadCtxState();
    // 进入聊天时若开启则提示
    setInterval(() => { if (document.getElementById("actModal") && !document.getElementById("actModal").classList.contains("hidden")) actRefresh(); }, 4000);
})();

/* =============== AI 记忆 页面 (#需求2) =============== */
let ctxMinOn = 10;           // 附加上下文时长（分钟），由 /api/memory 载入
let memUpdating = false;

function memOpen() { document.getElementById("memModal").classList.remove("hidden"); memLoad(); }
function memClose() { document.getElementById("memModal").classList.add("hidden"); }
function memFmtList(arr) { return (arr && arr.length) ? arr.join("、") : "(未记录)"; }

async function memLoad() {
    try {
        const d = await api("/api/memory?_=" + Date.now());
        ctxMinOn = Number(d.ctx_minutes) || 10;
        renderCtxMinSeg();
        renderMemInterval(d.interval);
        renderMemBody(d.memory);
    } catch (e) { toast("加载记忆失败"); }
}
function renderMemInterval(iv) {
    document.querySelectorAll("#memIntervalSeg .seg-item").forEach(x =>
        x.classList.toggle("selected", x.dataset.iv === (iv || "off")));
}
function renderCtxMinSeg() {
    document.querySelectorAll("#ctxMinSeg .seg-item").forEach(x =>
        x.classList.toggle("selected", Number(x.dataset.min) === ctxMinOn));
}
function renderMemBody(m) {
    const el = document.getElementById("memBody");
    if (!el) return;
    m = m || {};
    const rows = [
        ["🧩 用户习惯", memFmtList(m.habits)],
        ["💼 职业", m.profession || "(未记录)"],
        ["🖥️ 常用软件", memFmtList(m.common_apps)],
        ["📝 备注", m.notes || "(未记录)"],
    ];
    el.innerHTML = rows.map(([k, v]) =>
        `<div style="display:flex;gap:8px;"><span style="flex:0 0 90px;color:var(--text-2);">${k}</span><span style="flex:1;">${escHtml(v)}</span></div>`
    ).join("") +
    `<div style="border-top:1px solid rgba(128,128,128,.15);padding-top:6px;color:var(--text-2);font-size:11px;">最近更新：${escHtml(m.updated_at || "(从未更新)")}</div>`;
}
async function memUpdateNow() {
    if (memUpdating) return;
    memUpdating = true;
    const st = document.getElementById("memUpdateState");
    if (st) st.textContent = "AI 正在分析日志并更新记忆…";
    try {
        const d = await api("/api/memory/update", { method: "POST", body: JSON.stringify({ minutes: 60*24*7 }) });
        if (d.stubbed) {
            if (st) st.textContent = "AI 未启用（stub）：请先在 ~/.activity/config.json 设置 ai_enabled=true";
        } else if (d.saved) {
            if (st) st.textContent = "✓ 记忆已更新";
        } else {
            if (st) st.textContent = "更新完成（内容未变）";
        }
        memLoad();
        toast("记忆更新请求已处理");
    } catch (e) {
        if (st) st.textContent = "更新失败";
        toast("更新失败");
    }
    memUpdating = false;
}
async function memSetInterval(iv) {
    try {
        const d = await api("/api/memory/interval", { method: "POST", body: JSON.stringify({ interval: iv }) });
        if (d.ok) { renderMemInterval(iv); toast(d.interval === "off" ? "已关闭自动更新" : "自动循环更新已设为：" + d.interval); }
    } catch (e) { toast("设置失败"); }
}
async function memSetMinutes(min) {
    ctxMinOn = min;
    renderCtxMinSeg();
    try { await api("/api/config", { method: "POST", body: JSON.stringify({ ctx_minutes: min }) }); toast("附加上下文时长：" + min + " 分钟"); } catch (e) {}
}

(function initMem() {
    const mb = document.getElementById("memBtn");
    if (mb) mb.addEventListener("click", memOpen);
    const mc = document.getElementById("memClose");
    if (mc) mc.addEventListener("click", memClose);
    const mr = document.getElementById("memRefresh");
    if (mr) mr.addEventListener("click", memLoad);
    const mm = document.getElementById("memModal");
    if (mm) mm.addEventListener("click", e => { if (e.target === mm) memClose(); });
    const mu = document.getElementById("memUpdateBtn");
    if (mu) mu.addEventListener("click", memUpdateNow);
    document.querySelectorAll("#memIntervalSeg .seg-item").forEach(x =>
        x.addEventListener("click", () => memSetInterval(x.dataset.iv)));
    document.querySelectorAll("#ctxMinSeg .seg-item").forEach(x =>
        x.addEventListener("click", () => memSetMinutes(Number(x.dataset.min))));
    // 启动时载入 ctx 时长默认值
    api("/api/memory?_=" + Date.now()).then(d => {
        ctxMinOn = Number(d.ctx_minutes) || 10;
        renderCtxMinSeg();
    }).catch(() => {});
})();

/* =============== AI 日程 页面 =============== */
let schedOn=[];

function schedOpen(){ document.getElementById("schedModal").classList.remove("hidden"); schedLoad(); }
function schedClose(){ document.getElementById("schedModal").classList.add("hidden"); }
function schedEsc(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
async function schedLoad(){
  try{
    const d=await api("/api/schedule?_="+Date.now());
    schedOn=d.items||[];
    renderSchedList();
  }catch(e){ const l=document.getElementById("schedList"); if(l) l.innerHTML='<div class="empty">加载失败</div>'; }
}
function condLabel(c){
  c=c||{}; const w=c.when||"";
  if(c.type==="cron") return "cron: "+w;
  if(c.type==="event") return "事件: "+w;
  return "时间: "+w;
}
function renderSchedList(){
  const l=document.getElementById("schedList"); if(!l) return;
  if(!schedOn.length){ l.innerHTML='<div class="empty">暂无日程</div>'; return; }
  l.innerHTML="";
  schedOn.slice().reverse().forEach(it=>{
    const row=document.createElement("div");
    row.style.cssText="border:1px solid rgba(128,128,128,.18);border-radius:6px;padding:6px;display:flex;flex-direction:column;gap:4px;";
    const done=it.status==="done";
    row.innerHTML=
      `<div style="display:flex;align-items:center;gap:6px;">
         <span style="font-weight:600;flex:1;">${schedEsc(it.title||"")}</span>
         <span style="font-size:11px;color:var(--text-2);">${done?"✅ 已完成":"⏳ "+condLabel(it.condition)}</span>
       </div>
       <div style="color:var(--text-2);font-size:11px;">${schedEsc((it.task_prompt||"").slice(0,80))}</div>
       <div style="display:flex;gap:6px;align-items:center;">
         <button class="chip small sched-run" data-id="${it.id}">▶ 执行</button>
         <button class="chip small sched-toggle" data-id="${it.id}">${done?"↺ 重置":"✓ 完成"}</button>
         <button class="chip small sched-del" data-id="${it.id}">✕ 删除</button>
         <span style="flex:1;"></span>
         <span style="font-size:10px;color:var(--text-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:120px;">${schedEsc(it.result||"").slice(0,60)}</span>
       </div>`;
    row.querySelector(".sched-run").addEventListener("click",()=>schedRun(it.id));
    row.querySelector(".sched-toggle").addEventListener("click",()=>schedToggle(it.id));
    row.querySelector(".sched-del").addEventListener("click",()=>schedDel(it.id));
    l.appendChild(row);
  });
}
async function schedRun(id){
  try{ await api("/api/schedule/"+id+"/run",{method:"POST"}); toast("已触发执行"); schedLoad(); }catch(e){ toast("执行失败"); }
}
async function schedToggle(id){
  try{ await api("/api/schedule/"+id+"/toggle",{method:"POST"}); schedLoad(); }catch(e){ }
}
async function schedDel(id){
  try{ await api("/api/schedule/"+id,{method:"DELETE"}); schedLoad(); }catch(e){ }
}
function schedShowForm(show){
  const f=document.getElementById("schedForm"); if(f) f.classList.toggle("hidden",!show);
}
async function schedSave(){
  const title=document.getElementById("schedTitle").value.trim();
  const task=document.getElementById("schedTask").value.trim();
  const type=document.getElementById("schedType").value;
  const when=document.getElementById("schedWhen").value.trim();
  if(!task){ toast("请填写任务描述"); return; }
  try{
    await api("/api/schedule",{method:"POST",body:JSON.stringify({title,task_prompt:task,condition:{type,when}})});
    toast("已添加日程"); schedShowForm(false);
    ["schedTitle","schedTask","schedWhen"].forEach(id=>document.getElementById(id).value="");
    schedLoad();
  }catch(e){ toast("保存失败"); }
}
(function initSched(){
  const b=document.getElementById("schedBtn"); if(b) b.addEventListener("click",schedOpen);
  const c=document.getElementById("schedClose"); if(c) c.addEventListener("click",schedClose);
  const m=document.getElementById("schedModal"); if(m) m.addEventListener("click",e=>{if(e.target===m)schedClose();});
  const r=document.getElementById("schedRefresh"); if(r) r.addEventListener("click",schedLoad);
  const ab=document.getElementById("schedAddBtn"); if(ab) ab.addEventListener("click",()=>{schedShowForm(true);document.getElementById("schedTitle").focus();});
  const cb=document.getElementById("schedCancel"); if(cb) cb.addEventListener("click",()=>schedShowForm(false));
  const sb=document.getElementById("schedSave"); if(sb) sb.addEventListener("click",schedSave);
})();

/* ================= 截图 / 界面上下文（复刻 key） ================= */
(function initShotCtx() {
    const shotBtn = document.getElementById("shotBtn");
    if (shotBtn) shotBtn.addEventListener("click", async () => {
        toast("请框选要截取的区域…");
        try {
            const d = await api("/api/screenshot", { method: "POST" });
            if (d.ok) {
                attachedFiles.push({ name: d.path.split("/").pop(), path: d.path });
                renderFileChips();
                addMessage("system", `📷 已截图并作为附件：${d.path.split("/").pop()}`);
                if (d.ocr) addMessage("system", "OCR 识别：\n" + d.ocr.slice(0, 1500));
                toast("截图已附加，随下条消息发送");
            } else toast("截图失败: " + (d.error || ""));
        } catch (e) { toast("截图失败"); }
    });

    const tineBtn = document.getElementById("ctxTineBtn");
    if (tineBtn) tineBtn.addEventListener("click", async () => {
        toast("读取界面上下文…");
        try {
            const d = await api("/api/ctx-tine", { method: "POST" });
            if (d.ok && d.preview) {
                addMessage("system", "🌐 已读取界面上下文（随下条消息自动前置给 AI）：\n" + d.preview + (d.len > 200 ? "…" : ""));
                toast("已读取，随下条消息发送");
            } else toast("未读取到界面内容");
        } catch (e) { toast("读取失败"); }
    });
})();
