/* AI 助手 — chinai3 风格前端（完整复刻原版 key/ui.py 交互） */
const $ = (s) => document.querySelector(s);
const toastEl = $("#toast");
function toast(t, ms = 2400) { toastEl.textContent = t; toastEl.classList.remove("hidden"); clearTimeout(toastEl._t); toastEl._t = setTimeout(() => toastEl.classList.add("hidden"), ms); }
async function api(url, opts = {}) { const r = await fetch(url, Object.assign({ headers: { "Content-Type": "application/json" } }, opts)); if (!r.ok) throw new Error(r.statusText); return r.json(); }
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const msgList = $("#msgList"), welcome = $("#welcome"), input = $("#input");
const sendBtn = $("#sendBtn"), stopBtn = $("#stopBtn");
let generating = false, since = 0, poller = null;
let attachedFiles = [];   // [{path,name}]
let messages = [];

/* ---------- 消息渲染（气泡 + 操作行，仿 chinai3 msgEl） ---------- */
function msgEl(role, content) {
    const who = role === "user" ? "你" : (role === "system" ? "系统" : "AI");
    const el = document.createElement("div");
    el.className = `msg ${role === "user" ? "user" : (role === "system" ? "assistant" : "assistant")}`;
    el.dataset.role = role;
    const w = document.createElement("div"); w.className = "who"; w.textContent = who;
    const b = document.createElement("div"); b.className = "body";
    b.innerHTML = renderMarkdown(content || "");
    el.append(w, b);
    return el;
}
function addMessage(role, content) {
    welcome.classList.add("hidden");
    msgList.classList.remove("hidden");
    const el = msgEl(role, content || "");
    if (role === "assistant") {
        const row = document.createElement("div"); row.className = "act-row";
        const c = mkAct("复制", () => { navigator.clipboard.writeText(bText(el)); toast("已复制"); });
        row.append(c); el.appendChild(row);
    }
    msgList.appendChild(el);
    scrollBottom();
    return el;
}
function bText(el) { const b = el.querySelector(".body"); return b ? b.textContent : ""; }
function mkAct(label, fn) { const b = document.createElement("button"); b.className = "act-btn"; b.textContent = label; b.addEventListener("click", fn); return b; }
function renderMarkdown(t) {
    const lines = String(t).split("\n");
    let html = "", inCode = false, codeLang = "", codeBuf = [], listType = null;
    const flush = () => {
        if (inCode) { html += `<pre><span class="lang">${esc(codeLang)}</span><code>${esc(codeBuf.join("\n"))}</code></pre>`; inCode = false; codeBuf = []; codeLang = ""; }
    };
    for (let raw of lines) {
        const line = raw;
        const fence = line.match(/^```(\w*)\s*$/);
        if (fence) { if (inCode) { flush(); } else { flush(); inCode = true; codeLang = fence[1] || ""; } continue; }
        if (inCode) { codeBuf.push(line); continue; }
        if (/^\|/.test(line) && line.includes("|")) {
            const cells = line.split("|").slice(1, -1).map(c => c.trim());
            if (cells.every(c => /^:?-{2,}:?$/.test(c))) continue;
            html += "<tr>" + cells.map(c => `<td>${inline(c)}</td>`).join("") + "</tr>";
            if (!html.includes("<table>")) { /* wait for header */ }
            continue;
        }
        const h = line.match(/^(#{1,4})\s+(.*)$/);
        if (h) { flush(); html += `<h${h[1].length}>${inline(h[1][1] ? line.replace(/^#{1,4}\s+/, "") : "")}</h${h[1].length}>`; html = html.replace(`<h${h[1].length}>${inline(line.replace(/^#{1,4}\s+/, ""))}`, `<h${h[1].length}>${inline(line.replace(/^#{1,4}\s+/, ""))}`); continue; }
        if (/^\s*[-*]\s+/.test(line)) { flush(); if (listType !== "ul") { if (listType) html += `</${listType}>`; html += "<ul>"; listType = "ul"; } html += `<li>${inline(line.replace(/^\s*[-*]\s+/, ""))}</li>`; continue; }
        if (/^\s*\d+\.\s+/.test(line)) { flush(); if (listType !== "ol") { if (listType) html += `</${listType}>`; html += "<ol>"; listType = "ol"; } html += `<li>${inline(line.replace(/^\s*\d+\.\s+/, ""))}</li>`; continue; }
        if (/^\s*(---|\*\*\*)\s*$/.test(line)) { flush(); if (listType) { html += `</${listType}>`; listType = null; } html += "<hr>"; continue; }
        if (/^\s*>\s?/.test(line)) { flush(); html += `<blockquote>${inline(line.replace(/^\s*>\s?/, ""))}</blockquote>`; continue; }
        if (/^\s*$/.test(line)) { if (listType) { html += `</${listType}>`; listType = null; } html += ""; continue; }
        flush(); if (listType) { html += `</${listType}>`; listType = null; }
        html += `<p>${inline(line)}</p>`;
    }
    flush();
    if (listType) html += `</${listType}>`;
    return html;
}
function inline(s) {
    return esc(s)
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
        .replace(/__([^_]+)__/g, "<b>$1</b>")
        .replace(/\*([^*]+)\*/g, "<i>$1</i>")
        .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
function updateMsg(el, buf, done) {
    const b = el.querySelector(".body");
    if (!b) return;
    b.innerHTML = renderMarkdown(buf);
    el.classList.remove("streaming");
    scrollBottom();
}
function scrollBottom() { msgList.scrollTop = msgList.scrollHeight; }
function syncEmpty() { const empty = messages.length === 0; welcome.classList.toggle("hidden", !empty); msgList.classList.toggle("hidden", empty); }

/* ---------- 附件 ---------- */
function renderFiles() {
    const bar = $("#fileBar"), chips = $("#fileChips");
    if (!attachedFiles.length) { bar.classList.add("hidden"); return; }
    bar.classList.remove("hidden");
    chips.innerHTML = "";
    attachedFiles.forEach((f, i) => {
        const c = document.createElement("span"); c.className = "file-chip";
        const n = document.createElement("span"); n.className = "n"; n.textContent = f.name;
        const x = document.createElement("button"); x.className = "x"; x.textContent = "×";
        x.addEventListener("click", () => { attachedFiles.splice(i, 1); renderFiles(); });
        c.append(n, x); chips.appendChild(c);
    });
}
$("#attachBtn").addEventListener("click", () => {
    const fi = document.createElement("input");
    fi.type = "file";
    fi.onchange = async () => {
        const file = fi.files[0];
        if (!file) return;
        const fd = new FormData(); fd.append("file", file);
        try {
            const d = await fetch("/api/upload", { method: "POST", body: fd }).then(r => r.json());
            if (d.ok) { attachedFiles.push({ name: d.name, path: d.path }); renderFiles(); toast(`已附加 ${d.name}`); }
            else toast("上传失败");
        } catch (e) { toast("上传失败"); }
    };
    fi.click();
});

/* ---------- 发送 / 停止 ---------- */
async function send() {
    const text = input.value.trim();
    if (!text || generating) return;
    input.value = ""; autosize();
    addMessage("user", text);
    messages.push({ role: "user", content: text });
    const el = addMessage("assistant", "");
    generating = true; since = 0;
    sendBtn.classList.add("hidden"); stopBtn.classList.remove("hidden");
    try {
        const d = await api("/api/send", { method: "POST", body: JSON.stringify({ text, files: attachedFiles.map(f => f.path) }) });
        if (!d.ok) { updateMsg(el, "错误: " + (d.error || ""), true); endSend(); return; }
        attachedFiles = []; renderFiles();
        poller = setInterval(async () => {
            try {
                const s = await api("/api/stream?since=" + since);
                if (s.chunks) { el.querySelector(".body").innerHTML = renderMarkdown(el.querySelector(".body").textContent + s.chunks); since = s.total; }
                if (s.done) {
                    clearInterval(poller); poller = null;
                    let full = el.querySelector(".body").textContent;
                    if (s.error && !full) full = "错误: " + s.error;
                    updateMsg(el, full, true);
                    messages.push({ role: "assistant", content: full });
                    endSend();
                    refreshHistory();
                }
            } catch (e) { clearInterval(poller); poller = null; endSend(); }
        }, 350);
    } catch (e) { updateMsg(el, "错误: " + e.message, true); endSend(); }
}
function endSend() { generating = false; since = 0; sendBtn.classList.remove("hidden"); stopBtn.classList.add("hidden"); }
async function stop() { try { await api("/api/stop", { method: "POST" }); } catch (e) { } toast("已停止"); }

sendBtn.addEventListener("click", send);
stopBtn.addEventListener("click", stop);
input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 140) + "px"; }
input.addEventListener("input", autosize);

/* ---------- 新对话 ---------- */
$("#newChatBtn").addEventListener("click", async () => {
    await api("/api/newchat", { method: "POST" }).catch(() => { });
    messages = []; msgList.innerHTML = ""; welcome.classList.remove("hidden");
    msgList.classList.add("hidden"); input.value = ""; autosize();
    attachedFiles = []; renderFiles(); input.focus();
});

/* ---------- 截图 ---------- */
$("#shotBtn").addEventListener("click", async () => {
    toast("请框选要截取的区域…");
    try {
        const d = await api("/api/screenshot", { method: "POST" });
        if (d.ok) {
            attachedFiles.push({ name: d.path.split("/").pop(), path: d.path });
            renderFiles();
            addMessage("system", `📷 已截图并作为附件：${d.path.split("/").pop()}`);
            if (d.ocr) addMessage("system", "OCR 识别：\n" + d.ocr.slice(0, 1500));
            toast("截图已附加，随下条消息发送");
        } else toast("截图失败: " + (d.error || ""));
    } catch (e) { toast("截图失败"); }
});

/* ---------- 界面上下文 ---------- */
async function doContext() {
    toast("读取界面上下文…");
    try {
        const d = await api("/api/context", { method: "POST" });
        if (d.ok && d.preview) {
            addMessage("system", "🌐 已读取界面上下文（随下条消息自动发给 AI）：\n" + d.preview + (d.len > 200 ? "…" : ""));
            $("#ctxBar").classList.remove("hidden");
            toast("已读取，随下条消息发送");
        } else { toast("未读取到界面内容"); }
    } catch (e) { toast("读取失败"); }
}
$("#ctxBtn").addEventListener("click", doContext);
$("#ctxClear").addEventListener("click", async () => {
    await api("/api/context", { method: "POST", body: JSON.stringify({ clear: true }) }).catch(() => { });
    $("#ctxBar").classList.add("hidden");
});

/* ---------- 对话记录（会话弹窗） ---------- */
const convList = $("#convList");
async function loadConversations() {
    try {
        const d = await api("/api/conversations?_=" + Date.now());
        const rows = d.conversations || [];
        convList.innerHTML = rows.length ? "" : '<div class="empty">暂无会话</div>';
        rows.forEach(r => {
            const it = document.createElement("div"); it.className = "h-item";
            it.style.display = "flex"; it.style.gap = "6px"; it.style.alignItems = "center";
            const t = document.createElement("span"); t.className = "t"; t.style.flex = "1";
            t.textContent = `#${r.num} · ${r.prompt ? String(r.prompt).slice(0, 40) : (r.command || "")}`;
            const d2 = document.createElement("span"); d2.className = "d"; d2.textContent = (r.time || "").slice(5, 16);
            const view = mkChip("查看", () => viewConv(r.num));
            const sw = mkChip("继续", () => switchConv(r.num));
            it.append(t, d2, view, sw);
            it.addEventListener("dblclick", () => viewConv(r.num));
            convList.appendChild(it);
        });
    } catch (e) { convList.innerHTML = '<div class="empty">加载失败</div>'; }
}
function mkChip(t, fn) { const b = document.createElement("button"); b.className = "chip small"; b.textContent = t; b.addEventListener("click", (e) => { e.stopPropagation(); fn(); }); return b; }
async function viewConv(num) {
    try {
        const d = await api("/api/conversation/view", { method: "POST", body: JSON.stringify({ num }) });
        if (d.ok) { showConvDetail(num, d.text); }
    } catch (e) { toast("查看失败"); }
}
function showConvDetail(num, text) {
    const mask = document.createElement("div"); mask.className = "modal-mask";
    mask.innerHTML = `<div class="modal"><div class="modal-head"><span class="modal-title">会话 #${num}</span><button class="modal-close">×</button></div><div class="modal-body"><pre style="white-space:pre-wrap;font-size:12px;max-height:60vh;overflow:auto;">${esc(text)}</pre><div class="model-row"><span class="muted">可复制下方内容或关闭</span></div></div></div>`;
    mask.querySelector(".modal-close").addEventListener("click", () => mask.remove());
    mask.addEventListener("click", (e) => { if (e.target === mask) mask.remove(); });
    document.body.appendChild(mask);
}
async function switchConv(num) {
    toast("切换会话…");
    try {
        const d = await api("/api/conversation/switch", { method: "POST", body: JSON.stringify({ num }) });
        if (d.ok) {
            $("#settingsModal").classList.add("hidden");
            toast("已切换到会话 #" + num);
            msgList.innerHTML = ""; messages = [];
            addMessage("system", `⇄ 已切换到 AIM 会话 #${num}，继续输入即从该会话延续。`);
        } else toast(d.error || "切换失败");
    } catch (e) { toast("切换失败"); }
}
$("#convBtn").addEventListener("click", () => { $("#settingsModal").classList.remove("hidden"); loadConversations(); });
$("#settingsClose").addEventListener("click", () => $("#settingsModal").classList.add("hidden"));
$("#convRefresh").addEventListener("click", loadConversations);
$("#settingsModal").addEventListener("click", (e) => { if (e.target.id === "settingsModal") $("#settingsModal").classList.add("hidden"); });

/* ---------- 历史记录弹窗 ---------- */
const histMask = document.createElement("div"); histMask.className = "modal-mask hidden"; histMask.id = "histModal";
histMask.innerHTML = `<div class="modal"><div class="modal-head"><span class="modal-title">🕘 历史记录</span><button class="modal-close" id="histClose">×</button></div><div class="modal-body"><div class="model-row"><span class="muted">点击记录恢复对话（绑定对应 AIM 会话）</span><button class="chip" id="histRefresh" style="margin-left:auto;">⟳ 刷新</button></div><div id="histList"><div class="empty">加载中…</div></div></div></div>`;
document.body.appendChild(histMask);
const histList = $("#histList");
let historyCache = [];
async function refreshHistory() {
    try { historyCache = await api("/api/history?_=" + Date.now()); } catch (e) { historyCache = []; }
    histList.innerHTML = "";
    if (!historyCache.length) { histList.innerHTML = '<div class="empty">暂无记录</div>'; return; }
    historyCache.forEach(r => {
        const it = document.createElement("div"); it.className = "h-item";
        const t = document.createElement("div"); t.className = "t"; t.textContent = (r.title || "对话").slice(0, 30);
        const m = document.createElement("div"); m.className = "m"; m.textContent = (r.time || "") + (r.session ? "" : "");
        it.append(t, m);
        it.addEventListener("click", () => loadHistory(r));
        histList.appendChild(it);
    });
}
async function loadHistory(r) {
    try {
        const d = await api("/api/history/switch", { method: "POST", body: JSON.stringify({ record: r }) });
        if (d.ok) {
            messages = (d.messages || []).map(m => ({ role: m.role, content: m.content }));
            msgList.innerHTML = "";
            messages.forEach(m => { const el = msgEl(m.role, m.content); msgList.appendChild(el); });
            syncEmpty(); scrollBottom();
            histMask.classList.add("hidden");
            toast("已恢复历史对话" + (d.session ? "（绑定 AIM 会话）" : ""));
            if (d.session) addMessage("system", "⇄ 已自动切换到对应 AIM 会话，继续输入即从该会话延续。");
        }
    } catch (e) { toast("恢复失败"); }
}
$("#histBtn").addEventListener("click", () => { histMask.classList.remove("hidden"); refreshHistory(); });
$("#histClose").addEventListener("click", () => histMask.classList.add("hidden"));
$("#histRefresh").addEventListener("click", refreshHistory);
histMask.addEventListener("click", (e) => { if (e.target === histMask) histMask.classList.add("hidden"); });

/* ---------- 建议 chip ---------- */
document.querySelectorAll(".sugg-chip").forEach(b => b.addEventListener("click", () => { input.value = b.dataset.q; input.focus(); send(); }));

/* ---------- IPC 通知轮询 ---------- */
setInterval(async () => {
    try {
        const n = await api("/api/notice?_=" + Date.now());
        if (n.cmd) {
            const label = n.cmd === "wake" ? "🔔" : n.cmd === "screenshot" ? "📷" : "🌐";
            addMessage("system", label + " " + n.text);
            if (n.cmd === "screenshot" && /截图:.*\.png/.test(n.text)) {
                const m = n.text.match(/截图: (\S+\.png)/);
                if (m) { attachedFiles.push({ name: m[1].split("/").pop(), path: m[1] }); renderFiles(); }
            }
        }
    } catch (e) { }
}, 1500);

syncEmpty();
input.focus();
