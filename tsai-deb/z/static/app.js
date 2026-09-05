(() => {
    const $ = s => document.querySelector(s);
    const msgList = $('#msgList'), welcome = $('#welcome'), entry = $('#entry');
    const sendBtn = $('#sendBtn');
    function setBusy(b) { busy = b; sendBtn.textContent = b ? '停止' : '发送'; sendBtn.classList.toggle('stop', b); sendBtn.disabled = false; }
    const statusText = $('#statusText'), statusDot = $('#statusDot');
    const toast = $('#toast'), historyList = $('#historyList');

    let lastCount = 0, busy = false, histRecords = [];
    let toastTimer = null;

    function toastMsg(t) {
        toast.textContent = t;
        toast.classList.add('show');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toast.classList.remove('show'), 1800);
    }
    function setStatus(t, cls = '') {
        statusText.textContent = t;
        statusDot.className = 'dot' + (cls ? ' ' + cls : '');
    }
    function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
    function showChat() { msgList.classList.remove('hidden'); welcome.classList.add('hidden'); }

    function addMsg(who, text, cls = '') {
        showChat();
        const d = document.createElement('div');
        d.className = 'msg ' + (who === '你' ? 'user' : 'ai');
        d.innerHTML = `<div class="who">${esc(who)}</div><div class="bubble ${cls}"></div>`;
        d.querySelector('.bubble').textContent = text;
        msgList.appendChild(d);
        msgList.scrollTop = msgList.scrollHeight;
        return d;
    }
    let streamBubble = null;
    function beginStream() { const m = addMsg('AI', ''); streamBubble = m.querySelector('.bubble'); }
    function appendStream(t) { if (streamBubble) streamBubble.textContent += t; msgList.scrollTop = msgList.scrollHeight; }
    function endStream() { streamBubble = null; }

    function renderHistoryFrom(messages) {
        msgList.innerHTML = '';
        streamBubble = null;
        for (const m of messages) {
            const role = m.role === 'user' ? '你' : 'AI';
            addMsg(role, m.content || '');
        }
        if (messages.length) showChat();
    }

    async function api(url, opts = {}) {
        const r = await fetch(url, opts);
        return r.json();
    }

    async function loadHistory() {
        histRecords = await api('/api/history');
        historyList.innerHTML = histRecords.length
            ? histRecords.map((r, i) =>
                `<button class="h-item" data-i="${i}"><span class="t">${esc(r.title || '对话')}</span><span class="d">${esc(r.time || '')}</span></button>`).join('')
            : '<div class="empty">暂无记录</div>';
        historyList.querySelectorAll('.h-item').forEach(b => {
            b.onclick = () => {
                const rec = histRecords[Number(b.dataset.i)];
                if (!rec) return;
                renderHistoryFrom(rec.messages || []);
                toastMsg('已加载历史对话');
                lastCount = 0;
                if (rec.session) {
                    api('/api/history/switch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session: rec.session, messages: rec.messages || [] }) })
                        .then(d => { if (d.ok) toastMsg('已切换到对应 AIM 会话，继续输入即延续'); })
                        .catch(() => { });
                }
            };
        });
    }

    async function newChat() {
        await api('/api/new', { method: 'POST' });
        msgList.innerHTML = '';
        streamBubble = null;
        msgList.classList.add('hidden');
        welcome.classList.remove('hidden');
        await loadHistory();
        toastMsg('已开启新对话');
        entry.focus();
    }

    async function send() {
        const msg = entry.value.trim();
        if (busy) { stop(); return; }
        if (!msg) return;
        entry.value = '';
        addMsg('你', msg);
        setBusy(true);
        setStatus('AI 思考中…', 'run');
        beginStream(); lastCount = 0;
        const r = await api('/api/send', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: msg }),
        });
        if (!r.ok) {
            endStream();
            if (streamBubble) streamBubble.textContent = r.error || '发送失败';
            setBusy(false);
            setStatus('就绪');
            return;
        }
        poll();
    }

    async function poll() {
        try {
            const d = await api('/api/stream?since=' + lastCount);
            lastCount = d.total;
            d.chunks.forEach(c => appendStream(c));
            if (d.done) {
                setBusy(false);
                endStream();
                setStatus(d.error ? '失败' : '就绪', d.error ? 'err' : '');
                if (d.error) addMsg('AI', d.error, 'err');
                loadHistory();
                return;
            }
            setTimeout(poll, 250);
        } catch (e) { setTimeout(poll, 800); }
    }

    async function stop() {
        if (!busy) return;
        await api('/api/stop');
        setBusy(false);
        endStream(); setStatus('已停止');
    }

    async function refreshFiles() {
        const d = await api('/api/files');
        $('#fileList').innerHTML = d.files.length
            ? d.files.map(n => `<button class="list-item">${esc(n)}</button>`).join('')
            : '<div class="empty">暂无文件</div>';
        $('#filePath').textContent = '';
        $('#fileList').querySelectorAll('.list-item').forEach(b => {
            b.onclick = () => { $('#filePath').textContent = d.dir + '/' + b.textContent; };
        });
    }

    // ---- 事件 ----
    $('#newBtn').onclick = newChat;
    $('#sideNew').onclick = newChat;
    $('#refreshBtn').onclick = refreshFiles;
    $('#fileSecToggle').onclick = () => $('#fileSec').classList.toggle('collapsed');
    $('#hClearBtn').onclick = async () => {
        if (!confirm('清空全部历史记录？')) return;
        await api('/api/history/clear', { method: 'POST' });
        await loadHistory();
        toastMsg('历史已清空');
    };
    sendBtn.onclick = () => busy ? stop() : send();
    entry.onkeydown = e => { if (e.key === 'Enter') send(); };
    document.querySelectorAll('.sugg-chip').forEach(b => {
        b.onclick = () => { entry.value = b.dataset.q; send(); };
    });

    refreshFiles();
    loadHistory();
    entry.focus();
})();
