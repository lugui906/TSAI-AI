(() => {
    const $ = s => document.querySelector(s);
    const msgList = $('#msgList'), welcome = $('#welcome'), entry = $('#entry');
    const sendBtn = $('#sendBtn');
    function setBusy(b) { busy = b; sendBtn.textContent = b ? '停止' : '发送'; sendBtn.classList.toggle('stop', b); sendBtn.disabled = false; }
    const statusText = $('#statusText'), statusDot = $('#statusDot');
    const toast = $('#toast'), agentList = $('#agentList'), historyList = $('#historyList');
    const modalBack = $('#modalBack');

    let lastCount = 0, busy = false, agents = [], histRecords = [];
    let currentAgent = null, editingName = null;
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
        for (const m of messages) addMsg(m.role === 'user' ? '你' : 'AI', m.content || '');
        if (messages.length) showChat();
    }

    async function api(url, opts = {}) {
        const r = await fetch(url, opts);
        return r.json();
    }

    // ---- 角色 ----
    async function loadAgents() {
        agents = await api('/api/agents');
        agentList.innerHTML = agents.length
            ? agents.map(a => `<button class="list-item ${a.name === currentAgent ? 'active' : ''}" data-n="${a.name}">${esc(a.name)}<span class="sub">${esc(a.description || a.role || '')}</span></button>`).join('')
            : '<div class="empty">暂无角色</div>';
        agentList.querySelectorAll('.list-item').forEach(b => {
            b.onclick = () => selectAgent(b.dataset.n);
        });
        const has = !!currentAgent;
        $('#editAgentBtn').disabled = !has;
        $('#delAgentBtn').disabled = !has;
    }
    async function selectAgent(name) {
        currentAgent = name;
        await loadAgents();
        await api('/api/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ agent: currentAgent }) });
        msgList.innerHTML = '';
        showChat();
        addMsg('AI', `已选择角色「${currentAgent}」，开始新对话。`, 'sys');
        setStatus(`当前角色: ${currentAgent}`);
        entry.focus();
    }
    async function newChat() {
        if (!currentAgent) { toastMsg('请先选择或创建一个角色'); return; }
        await api('/api/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ agent: currentAgent }) });
        msgList.innerHTML = '';
        streamBubble = null;
        msgList.classList.add('hidden');
        welcome.classList.remove('hidden');
        await loadHistory();
        toastMsg('已开启新对话');
        entry.focus();
    }

    // ---- 历史 ----
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

    // ---- 角色弹窗 ----
    function openModal(name) {
        const a = name ? agents.find(x => x.name === name) : {};
        editingName = name || null;
        $('#f_name').value = name || '';
        $('#f_role').value = (a && a.role) || '';
        $('#f_description').value = (a && a.description) || '';
        $('#f_prompt').value = (a && a.prompt) || '';
        $('#f_personality').value = (a && a.personality) || '';
        $('#f_background').value = (a && a.background) || '';
        $('#f_rules').value = (a && a.rules) || '';
        $('#f_name').disabled = !!name;
        modalBack.classList.remove('hidden');
    }
    function closeModal() { modalBack.classList.add('hidden'); }
    async function saveAgent() {
        const body = {
            name: $('#f_name').value.trim(), role: $('#f_role').value.trim(),
            description: $('#f_description').value.trim(), prompt: $('#f_prompt').value.trim(),
            personality: $('#f_personality').value.trim(), background: $('#f_background').value.trim(),
            rules: $('#f_rules').value.trim(),
        };
        if (!body.name) { toastMsg('名称必填'); return; }
        const r = await api('/api/agents', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        toastMsg(r.ok ? `已保存 ${body.name}` : (r.error || '保存失败'));
        closeModal();
        await loadAgents();
    }
    async function delAgent() {
        if (!currentAgent) return;
        if (!confirm(`删除角色「${currentAgent}」？`)) return;
        await api('/api/agents/' + encodeURIComponent(currentAgent) + '/delete', { method: 'POST' });
        currentAgent = null;
        await loadAgents();
        toastMsg('已删除');
    }

    // ---- 发送/流式 ----
    async function send() {
        const msg = entry.value.trim();
        if (busy) { stop(); return; }
        if (!msg) return;
        if (!currentAgent) { toastMsg('请先选择角色'); return; }
        entry.value = '';
        addMsg('你', msg);
        setBusy(true);
        setStatus('AI 思考中…', 'run');
        beginStream(); lastCount = 0;
        const r = await api('/api/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: msg }) });
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

    // ---- 事件 ----
    $('#newBtn').onclick = newChat;
    $('#sideNew').onclick = newChat;
    $('#addAgentBtn').onclick = () => openModal(null);
    $('#editAgentBtn').onclick = () => currentAgent && openModal(currentAgent);
    $('#delAgentBtn').onclick = delAgent;
    $('#modalClose').onclick = closeModal;
    $('#modalCancel').onclick = closeModal;
    $('#modalSave').onclick = saveAgent;
    modalBack.onclick = e => { if (e.target === modalBack) closeModal(); };
    $('#hClearBtn').onclick = async () => {
        if (!confirm('清空全部历史记录？')) return;
        await api('/api/history/clear', { method: 'POST' });
        await loadHistory();
        toastMsg('历史已清空');
    };
    sendBtn.onclick = () => busy ? stop() : send();
    entry.onkeydown = e => { if (e.key === 'Enter') send(); };
    $('#suggCreate').onclick = () => openModal(null);

    loadAgents();
    loadHistory();
    entry.focus();
})();
