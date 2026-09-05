/* AI 模型管理器 — chinai3 风格前端（4 tab 完整复刻） */
const $ = (s) => document.querySelector(s);
const toastEl = $("#toast");
function toast(t, ms = 2400) { toastEl.textContent = t; toastEl.classList.remove("hidden"); clearTimeout(toastEl._t); toastEl._t = setTimeout(() => toastEl.classList.add("hidden"), ms); }
async function api(url, opts = {}) { const r = await fetch(url, Object.assign({ headers: { "Content-Type": "application/json" } }, opts)); if (!r.ok) { try { const e = await r.json(); throw new Error(e.error || e.msg || r.statusText); } catch (e2) { throw new Error(r.statusText); } } return r.json(); }
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
function setStatus(t) { $("#statusText").textContent = t; }
function maskKey(k) { if (!k) return ""; return k.length > 8 ? k.slice(0, 4) + "*".repeat(k.length - 8) + k.slice(-4) : "***"; }

let currentTab = "default";
const tabBody = $("#tabBody");
const renderers = { default: renderDefault, engine: renderEngine, provider: renderProvider };

function switchTab(t) {
    currentTab = t;
    document.querySelectorAll("#tabs .tab-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === t));
    renderers[t]();
}
document.querySelectorAll("#tabs .tab-btn").forEach(b => b.addEventListener("click", () => switchTab(b.dataset.tab)));

/* ---------- 默认模型（自动保存） ---------- */
let modelsCache = [];
let saveTimer = null;
async function saveDefault(quiet) {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
        try {
            await api("/api/model/default", { method: "POST", body: JSON.stringify({ model: $("#defModel").value, small_model: $("#smallModel").value }) });
            if (!quiet) { toast("已自动保存默认模型"); setStatus("已自动保存"); }
        } catch (e) { toast("保存失败: " + e.message); }
    }, 500);
}
async function renderDefault() {
    tabBody.innerHTML = `<div class="sec-note">AIM 底层委托 opencode，两者共用该配置（~/.config/opencode/opencode.jsonc）。改动后自动保存。</div>
      <div class="card"><div class="ct">默认模型</div>
        <div class="row"><span class="lbl">默认模型 (model)</span><input type="text" id="defModel" placeholder="如 provider/model" autocomplete="off">
          <button class="chip small" id="pickDef">← 从列表选</button></div>
        <div class="row"><span class="lbl">小模型 (small_model)</span><input type="text" id="smallModel" placeholder="可选" autocomplete="off">
          <button class="chip small" id="pickSmall">← 从列表选</button></div>
        <div class="row"><button class="chip" id="refreshModels">⟳ 刷新模型列表</button>
          <span class="sec-note" style="margin:0;" id="modelCount"></span>
          <span class="sec-note" style="margin:0 0 0 auto;" id="autoSaveHint">改动自动保存</span></div>
      </div>
      <div class="card"><div class="ct">可用模型（点击「主/小」设到对应框并自动保存）</div>
        <input type="text" id="modelFilter" placeholder="筛选…" style="width:100%;">
        <div class="model-list" id="modelList"></div>
      </div>`;
    let selModel = "";
    async function loadModels(keepSel) {
        try {
            const d = await api("/api/models?_=" + Date.now());
            modelsCache = d.models || [];
            $("#modelCount").textContent = modelsCache.length + " 个";
            renderModelList(keepSel || selModel);
        } catch (e) { }
    }
    function renderModelList(sel) {
        const kw = ($("#modelFilter")?.value || "").toLowerCase();
        const rows = modelsCache.filter(m => !kw || m.toLowerCase().includes(kw));
        const list = $("#modelList"); list.innerHTML = "";
        rows.forEach(m => {
            const it = document.createElement("div"); it.className = "mi";
            it.textContent = m; it.style.background = m === sel ? "rgba(30,136,229,.15)" : "";
            const setAs = (target) => { selModel = m; $("#" + target).value = m; renderModelList(m); saveDefault(); };
            const b1 = document.createElement("button"); b1.className = "chip small"; b1.textContent = "主";
            b1.addEventListener("click", (e) => { e.stopPropagation(); setAs("defModel"); });
            const b2 = document.createElement("button"); b2.className = "chip small"; b2.textContent = "小";
            b2.addEventListener("click", (e) => { e.stopPropagation(); setAs("smallModel"); });
            it.appendChild(b1); it.appendChild(b2);
            list.appendChild(it);
        });
    }
    $("#modelFilter").addEventListener("input", () => renderModelList());
    $("#pickDef").addEventListener("click", () => { const m = modelsCache[0]; if (m) { $("#defModel").value = m; saveDefault(); } });
    $("#pickSmall").addEventListener("click", () => { const m = modelsCache[0]; if (m) { $("#smallModel").value = m; saveDefault(); } });
    $("#defModel").addEventListener("change", () => saveDefault());
    $("#smallModel").addEventListener("change", () => saveDefault());
    $("#defModel").addEventListener("input", () => saveDefault(true));
    $("#smallModel").addEventListener("input", () => saveDefault(true));
    $("#refreshModels").addEventListener("click", () => loadModels(true));
    loadModels();
    try {
        const d = await api("/api/defaults?_=" + Date.now());
        $("#defModel").value = d.model || "";
        $("#smallModel").value = d.small_model || "";
    } catch (e) { }
}

/* ---------- AIM 引擎（仅引擎切换；API/Key 请在「自定义 Provider」页配置） ---------- */
async function renderEngine() {
    tabBody.innerHTML = `<div class="sec-note">切换 AIM 使用的 AI 引擎（opencode / openclaw）。Provider 与 API Key 请在「自定义 Provider」页统一配置。</div>
      <div class="card"><div class="ct">🤖 AI 引擎</div>
        <div class="row"><span class="lbl">当前引擎</span><span id="curEngine" style="font-weight:700;">…</span></div>
        <div class="row">
          <button class="chip" id="toOpenclaw">切换到 openclaw</button>
          <button class="chip" id="toOpencode">切换回 opencode</button>
        </div>
      </div>`;
    async function loadEngine() {
        try { const d = await api("/api/engine?_=" + Date.now()); $("#curEngine").textContent = d.engine; } catch (e) { }
    }
    loadEngine();
    $("#toOpenclaw").addEventListener("click", async () => { const d = await api("/api/engine", { method: "POST", body: JSON.stringify({ target: "openclaw" }) }); toast(d.msg || (d.ok ? "已切换" : "失败")); loadEngine(); });
    $("#toOpencode").addEventListener("click", async () => { const d = await api("/api/engine", { method: "POST", body: JSON.stringify({ target: "opencode" }) }); toast(d.msg || (d.ok ? "已切换" : "失败")); loadEngine(); });
}

/* ---------- 自定义 Provider ---------- */
async function renderProvider() {
    tabBody.innerHTML = `<div class="sec-note">自定义 Provider 写入 opencode.jsonc 的 provider 段，含 baseURL / apiKey / models。</div>
      <div class="card"><div class="ct">Provider 列表</div>
        <table class="data-table" id="provTable"><tr><th>ID</th><th>名称</th><th>BaseURL</th><th>Key</th><th></th></tr></table>
      </div>
      <div class="card"><div class="ct">添加 / 编辑 Provider</div>
        <div class="row"><span class="lbl">Provider ID</span><input type="text" id="pId" placeholder="如 my-provider"></div>
        <div class="row"><span class="lbl">显示名称</span><input type="text" id="pName" placeholder="可选"></div>
        <div class="row"><span class="lbl">npm 包</span><input type="text" id="pNpm" value="@ai-sdk/openai-compatible"></div>
        <div class="row"><span class="lbl">Base URL</span><input type="text" id="pBase" placeholder="http://127.0.0.1:8000/v1"></div>
        <div class="row"><span class="lbl">API Key</span><input type="text" id="pKey" placeholder="可选（已存在则不覆盖）"></div>
        <div class="row"><span class="lbl">模型 ID</span></div>
        <textarea id="pModels" rows="4" placeholder="每行一个模型 ID；视觉模型加 |vision&#10;如：qwen3-coder:a3b&#10;gpt-4o|vision"></textarea>
        <div class="row"><button class="chip primary" id="pSave">保存 Provider</button>
          <button class="chip" id="pClear">清空表单</button></div>
      </div>`;
    async function load() {
        try {
            const d = await api("/api/providers?_=" + Date.now());
            const t = $("#provTable");
            t.innerHTML = `<tr><th>ID</th><th>名称</th><th>BaseURL</th><th>Key</th><th></th></tr>`;
            (d.providers || []).forEach(p => {
                const tr = document.createElement("tr");
                tr.innerHTML = `<td>${esc(p.id)}</td><td>${esc(p.name || "")}</td><td>${esc(p.baseURL || "")}</td><td>${p.hasKey ? "🔑" : ""}</td>`;
                const td = document.createElement("td");
                const eb = document.createElement("button"); eb.className = "chip small"; eb.textContent = "编辑";
                eb.addEventListener("click", () => { fill(p); });
                const db = document.createElement("button"); db.className = "chip small danger"; db.textContent = "删除";
                db.addEventListener("click", async () => { if (confirm("删除 Provider " + p.id + "？")) { await api("/api/provider", { method: "DELETE", body: JSON.stringify({ id: p.id }) }); load(); } });
                td.appendChild(eb); td.appendChild(db); tr.appendChild(td); t.appendChild(tr);
            });
        } catch (e) { }
    }
    function fill(p) {
        $("#pId").value = p.id; $("#pName").value = p.name || ""; $("#pNpm").value = p.npm || "@ai-sdk/openai-compatible";
        $("#pBase").value = p.baseURL || ""; $("#pKey").value = ""; $("#pModels").value = (p.models || []).join("\n");
    }
    $("#pSave").addEventListener("click", async () => {
        const models = $("#pModels").value.split("\n").map(s => s.trim()).filter(Boolean);
        try {
            const d = await api("/api/provider", { method: "POST", body: JSON.stringify({ id: $("#pId").value, name: $("#pName").value, npm: $("#pNpm").value, baseURL: $("#pBase").value, apiKey: $("#pKey").value, models }) });
            toast(d.ok ? "已保存" : (d.error || "失败")); if (d.ok) { $("#pKey").value = ""; load(); }
        } catch (e) { toast(e.message); }
    });
    $("#pClear").addEventListener("click", () => { ["pId", "pName", "pBase", "pKey", "pModels"].forEach(id => $("#" + id).value = ""); });
    load();
}

$("#reloadBtn").addEventListener("click", () => renderers[currentTab]());
switchTab("default");
