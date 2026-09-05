(() => {
    const $ = s => document.querySelector(s);
    const editor = $('#editor'), edName = $('#edName'), edFmt = $('#edFmt'), edStatus = $('#edStatus');
    const fileList = $('#fileList'), dirInput = $('#dirInput');
    const aiMsgList = $('#aiMsgList'), aiInput = $('#aiInput'), ctxBox = $('#ctxBox');
    const toast = $('#toast'), statusText = $('#statusText'), statusDot = $('#statusDot');

    let filepath = null, busy = false, lastCount = 0, histRecords = [];
    let ctxText = '', pendingMode = '';
    let toastTimer = null;
    const ACTION_PROMPTS = {
        '改写': '请改写以下文本，保持原意但改进表达：\n\n{text}',
        '翻译成中文': '请将以下文本翻译成中文：\n\n{text}',
        '翻译成英文': '请将以下文本翻译成英文：\n\n{text}',
        '续写': '请续写以下文本：\n\n{text}',
        '总结': '请总结以下文本的要点：\n\n{text}',
        '扩写': '请详细扩写以下文本：\n\n{text}',
        '简化': '请简化以下文本，使其更易读：\n\n{text}',
    };

    function toastMsg(t) {
        toast.textContent = t; toast.classList.add('show');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toast.classList.remove('show'), 1800);
    }
    function setStatus(t, cls = '') { statusText.textContent = t; statusDot.className = 'dot' + (cls ? ' ' + cls : ''); }
    function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
    async function api(url, opts = {}) {
        const r = await fetch(url, opts);
        return r.json();
    }
    function getSel() {
        return editor.value.slice(editor.selectionStart, editor.selectionEnd);
    }
    function updateCtx() {
        ctxText = getSel().trim();
        if (ctxText) {
            ctxBox.classList.remove('hidden');
            ctxBox.textContent = ctxText.length > 150 ? ctxText.slice(0, 150) + '…' : ctxText;
        } else {
            ctxBox.classList.add('hidden');
            ctxBox.textContent = '未选中文本';
        }
    }

    // ---- 文件浏览 ----
    async function loadDir() {
        const d = await api('/api/dir');
        const f = $('#filterSel').value;
        const files = f ? d.files.filter(x => x.ext === f) : d.files;
        fileList.innerHTML = files.length
            ? files.map(x => `<button class="list-item" data-p="${esc(d.dir + '/' + x.name)}">${esc(x.name)}</button>`).join('')
            : '<div class="empty">暂无文件</div>';
        fileList.querySelectorAll('.list-item').forEach(b => {
            b.onclick = () => openPath(b.dataset.p);
        });
    }
    async function openPath(p) {
        const r = await api('/api/file?path=' + encodeURIComponent(p));
        if (!r.ok) { toastMsg(r.error || '打开失败'); return; }
        filepath = r.path;
        editor.value = r.content;
        edName.textContent = r.name;
        edFmt.textContent = (r.ext || '').replace('.', '').toUpperCase();
        edStatus.textContent = '';
        updateCtx();
        setStatus('已打开 ' + r.name);
    }
    async function saveDoc() {
        if (!filepath) {
            const name = prompt('保存为（文件名）', '未命名.md');
            if (!name) return;
            filepath = (await api('/api/dir')).dir + '/' + name;
        }
        const r = await api('/api/file', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: filepath, content: editor.value }) });
        toastMsg(r.ok ? '已保存' : (r.error || '保存失败'));
        if (r.ok) {
            edName.textContent = filepath.split('/').pop();
            edStatus.textContent = '已保存 ' + new Date().toLocaleTimeString();
            loadDir();
        }
    }

    // ---- AI ----
    function aiAddMsg(text, role) {
        const d = document.createElement('div');
        d.className = 'ai-msg ' + (role || 'assistant');
        d.textContent = text;
        aiMsgList.appendChild(d);
        aiMsgList.scrollTop = aiMsgList.scrollHeight;
        return d;
    }
    let streamEl = null;
    function setAiBusy(b) { busy = b; const bEl = $('#aiSend'); bEl.textContent = b ? '停止' : '发送'; bEl.classList.toggle('stop', b); bEl.disabled = false; }
    async function aiSend(message, mode) {
        if (busy) { aiStop(); return; }
        if (!message.trim()) return;
        aiAddMsg(message, 'user');
        pendingMode = mode;
        setAiBusy(true);
        setStatus('AI 思考中…', 'run');
        streamEl = aiAddMsg('', 'assistant');
        lastCount = 0;
        const r = await api('/api/ai/send', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, mode, selection: ctxText, full_doc: editor.value }),
        });
        if (!r.ok) {
            streamEl.textContent = r.error || '发送失败';
            setAiBusy(false);
            setStatus('就绪');
            return;
        }
        aiPoll();
    }
    async function aiPoll() {
        try {
            const d = await api('/api/ai/stream?since=' + lastCount);
            lastCount = d.total;
            if (streamEl) streamEl.textContent += d.chunks.join('');
            aiMsgList.scrollTop = aiMsgList.scrollHeight;
            if (d.done) {
                setAiBusy(false);
                setStatus(d.error ? '失败' : '就绪', d.error ? 'err' : '');
                if (d.error) aiAddMsg(d.error, 'system');
                else if (streamEl) applyResult(streamEl.textContent.trim());
                streamEl = null;
                loadHistory();
                return;
            }
            setTimeout(aiPoll, 250);
        } catch (e) { setTimeout(aiPoll, 800); }
    }
    function applyResult(text) {
        if (pendingMode === 'selection' && ctxText && editor.selectionStart !== editor.selectionEnd) {
            const s = editor.selectionStart, e = editor.selectionEnd;
            editor.value = editor.value.slice(0, s) + text + editor.value.slice(e);
            editor.setSelectionRange(s, s + text.length);
            toastMsg('已替换选中文本');
        } else {
            editor.value = text;
            toastMsg('已应用到文档');
        }
        updateCtx();
        edStatus.textContent = '已由 AI 修改';
    }
    async function aiStop() {
        if (!busy) return;
        await api('/api/ai/stop');
        setAiBusy(false);
        setStatus('已停止');
    }
    async function aiNew() {
        await api('/api/ai/new', { method: 'POST' });
        aiMsgList.innerHTML = ''; streamEl = null;
        await loadHistory();
        toastMsg('已开启新会话');
    }
    async function loadHistory() {
        histRecords = await api('/api/history');
        $('#histList').innerHTML = histRecords.length
            ? histRecords.map((r, i) => `<button class="h-item" data-i="${i}"><span class="t">${esc(r.title || '对话')}</span><span class="d">${esc(r.time || '')}</span></button>`).join('')
            : '<div class="empty">暂无记录</div>';
        $('#histList').querySelectorAll('.h-item').forEach(b => {
            b.onclick = () => {
                const rec = histRecords[Number(b.dataset.i)];
                if (!rec) return;
                aiMsgList.innerHTML = '';
                (rec.messages || []).forEach(m => aiAddMsg(m.content || m.text || '', m.role === 'user' ? 'user' : 'assistant'));
                toastMsg('已加载历史会话');
                if (rec.session) {
                    api('/api/history/switch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session: rec.session, messages: rec.messages || [] }) })
                        .then(d => { if (d.ok) toastMsg('已切换到对应会话，继续输入即延续'); })
                        .catch(() => { });
                }
            };
        });
    }

    function onAction(name) {
        if (name === '全文改写') {
            if (!editor.value.trim()) { aiAddMsg('没有打开的文档', 'system'); return; }
            aiAddMsg('[全文改写]', 'user');
            aiSend('请完整改写以下文档，改进表达和结构：\n---\n' + editor.value + '\n---', 'full');
            return;
        }
        if (name === '全文总结' || name === '全文翻译') {
            if (!editor.value.trim()) { aiAddMsg('没有打开的文档', 'system'); return; }
            const p = name === '全文总结' ? '请总结以下文档的要点：\n---\n{doc}\n---' : '请将以下文档翻译成中文：\n---\n{doc}\n---';
            aiAddMsg('[' + name + ']', 'user');
            aiSend(p.replace('{doc}', editor.value), 'full');
            return;
        }
        const prompt = ACTION_PROMPTS[name];
        if (!ctxText) { aiAddMsg('请先在编辑器中选择文本', 'system'); return; }
        aiAddMsg('[' + name + '] ' + ctxText.slice(0, 50) + '...', 'user');
        aiSend(prompt.replace('{text}', ctxText), 'selection');
    }

    // ---- 事件 ----
    $('#refreshBtn').onclick = loadDir;
    $('#saveBtn').onclick = saveDoc;
    $('#newBtn').onclick = () => { editor.value = ''; filepath = null; edName.textContent = '未命名'; edFmt.textContent = ''; updateCtx(); };
    $('#openBtn').onclick = () => openPicker.click();
    dirInput.onkeydown = async e => {
        if (e.key === 'Enter') {
            const r = await api('/api/dir', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dir: dirInput.value }) });
            if (r.ok) { dirInput.value = r.dir; loadDir(); } else toastMsg(r.error || '目录不存在');
        }
    };
    $('#browseBtn').onclick = () => dirPicker.click();
    $('#filterSel').onchange = loadDir;
    $('#monoBtn').onchange = e => editor.classList.toggle('mono', e.target.checked);
    editor.oninput = () => { edStatus.textContent = '未保存'; };
    editor.addEventListener('keyup', updateCtx);
    editor.addEventListener('mouseup', updateCtx);
    editor.addEventListener('select', updateCtx);
    document.addEventListener('keydown', e => {
        if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); saveDoc(); }
        if ((e.ctrlKey || e.metaKey) && e.key === 'o') { e.preventDefault(); openPicker.click(); }
    });

    $('#aiSend').onclick = () => {
        if (busy) { aiStop(); return; }
        const v = aiInput.value.trim();
        if (!v) return;
        aiInput.value = '';
        aiSend(v, 'chat');
    };
    aiInput.onkeydown = e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#aiSend').click(); }
    };
    document.querySelectorAll('.ai-actions button').forEach(b => {
        b.onclick = () => onAction(b.dataset.act);
    });
    $('#histToggle').onclick = () => {
        const h = $('#histPane');
        h.style.display = h.style.display === 'none' ? '' : 'none';
        if (h.style.display !== 'none') loadHistory();
    };
    $('#histClear').onclick = async () => {
        if (!confirm('清空全部历史记录？')) return;
        await api('/api/history/clear', { method: 'POST' });
        await loadHistory();
        toastMsg('历史已清空');
    };

    // 目录/文件选择器（WebKit 提供真实路径）
    const openPicker = document.createElement('input');
    openPicker.type = 'file';
    openPicker.style.display = 'none';
    openPicker.onchange = () => {
        const f = openPicker.files[0];
        if (!f) return;
        if (f.path) openPath(f.path);
        else { const rd = new FileReader(); rd.onload = () => { filepath = f.name; editor.value = rd.result; edName.textContent = f.name; }; rd.readAsText(f); }
        openPicker.value = '';
    };
    document.body.appendChild(openPicker);
    const dirPicker = document.createElement('input');
    dirPicker.type = 'file';
    dirPicker.setAttribute('webkitdirectory', '');
    dirPicker.style.display = 'none';
    dirPicker.onchange = () => {
        const f = dirPicker.files[0];
        if (f && f.webkitRelativePath) {
            const d = f.webkitRelativePath.split('/').slice(0, -1).join('/');
            dirInput.value = d;
            api('/api/dir', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dir: d }) })
                .then(r => r.ok && loadDir());
        }
        dirPicker.value = '';
    };
    document.body.appendChild(dirPicker);

    (async () => {
        const d = await api('/api/dir');
        dirInput.value = d.dir;
        loadDir();
        loadHistory();
    })();
    editor.focus();
})();
