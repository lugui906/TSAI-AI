(() => {
    const $ = s => document.querySelector(s);
    const tbody = $('#taskBody'), statusText = $('#statusText'), statusDot = $('#statusDot');
    const toast = $('#toast'), schedBtn = $('#schedBtn');
    const modalBack = $('#modalBack'), detailBack = $('#detailBack');

    let tasks = [], selected = null, editingId = null;
    let toastTimer = null;

    function toastMsg(t) {
        toast.textContent = t;
        toast.classList.add('show');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toast.classList.remove('show'), 1800);
    }
    function setStatus(t, cls = '') { statusText.textContent = t; statusDot.className = 'dot' + (cls ? ' ' + cls : ''); }
    async function api(url, opts = {}) {
        const r = await fetch(url, opts);
        return r.json();
    }
    function esc(s) {
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    async function loadTasks() {
        tasks = await api('/api/tasks');
        $('#taskEmpty').classList.toggle('hidden', tasks.length > 0);
        tbody.innerHTML = tasks.map(t => `
            <tr data-id="${t.id}" class="${selected === t.id ? 'selected' : ''}">
                <td style="font-family:var(--mono);font-size:12px;">${esc(t.id)}</td>
                <td>${esc(t.time)}</td>
                <td>${esc(t.period)}</td>
                <td><div class="cell-wrap" title="${esc(t.prompt)}">${esc(t.prompt)}</div></td>
                <td><span class="tag ${t.enabled ? 'on' : 'off'}">${t.enabled ? '启用' : '禁用'}</span></td>
                <td>${esc(t.last_run)}</td>
                <td><div class="cell-wrap" title="${esc(t.last_result)}">${esc(t.last_result || '')}</div></td>
            </tr>`).join('');
        tbody.querySelectorAll('tr').forEach(tr => {
            tr.onclick = () => { selected = tr.dataset.id; renderSel(); };
            tr.ondblclick = () => showDetail(tr.dataset.id);
        });
        renderSel();
    }
    function renderSel() {
        const has = !!selected;
        $('#editBtn').disabled = !has;
        $('#toggleBtn').disabled = !has;
        $('#runBtn').disabled = !has;
        $('#delBtn').disabled = !has;
    }

    function openModal(id) {
        const t = id ? tasks.find(x => x.id === id) : {};
        editingId = id || null;
        $('#f_prompt').value = t.prompt || '';
        $('#f_time').value = t.time || '';
        $('#f_period').value = t.period || 'daily';
        modalBack.classList.remove('hidden');
    }
    function closeModal() { modalBack.classList.add('hidden'); }
    function showDetail(id) {
        const t = tasks.find(x => x.id === id);
        if (!t) return;
        $('#d_id').textContent = t.id;
        $('#d_prompt').textContent = t.prompt;
        $('#d_result').textContent = t.last_result || '(无结果)';
        detailBack.classList.remove('hidden');
    }

    async function saveTask() {
        const body = { prompt: $('#f_prompt').value.trim(), time: $('#f_time').value.trim(), period: $('#f_period').value };
        if (!body.prompt || !body.time) { toastMsg('提示词与时间必填'); return; }
        const url = editingId ? '/api/tasks/' + editingId : '/api/tasks';
        const r = await api(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        toastMsg(r.ok ? '已保存' : (r.error || '保存失败'));
        closeModal();
        await loadTasks();
    }

    async function toggle() {
        if (!selected) return;
        const r = await api('/api/tasks/' + selected + '/toggle', { method: 'POST' });
        if (!r.ok) toastMsg(r.error || '操作失败');
        await loadTasks();
    }
    async function del() {
        if (!selected) return;
        if (!confirm('确认删除任务？')) return;
        const r = await api('/api/tasks/' + selected + '/delete', { method: 'POST' });
        toastMsg(r.ok ? '已删除' : (r.error || '删除失败'));
        selected = null;
        await loadTasks();
    }
    async function runNow() {
        if (!selected) return;
        await api('/api/tasks/' + selected + '/run', { method: 'POST' });
        toastMsg('已开始执行，稍后刷新查看结果');
    }

    async function toggleSched() {
        const r = await api('/api/scheduler', { method: 'POST' });
        if (r.running) {
            schedBtn.textContent = '停止调度器';
            schedBtn.classList.remove('primary');
            schedBtn.classList.add('danger');
            setStatus('调度器: 运行中', 'run');
        } else {
            schedBtn.textContent = '启动调度器';
            schedBtn.classList.add('primary');
            schedBtn.classList.remove('danger');
            setStatus('调度器: 已停止');
        }
    }

    async function init() {
        const s = await api('/api/status');
        if (s.running) {
            schedBtn.textContent = '停止调度器';
            schedBtn.classList.remove('primary');
            schedBtn.classList.add('danger');
            setStatus('调度器: 运行中', 'run');
        }
        await loadTasks();
    }

    $('#addBtn').onclick = () => openModal(null);
    $('#editBtn').onclick = () => selected && openModal(selected);
    $('#toggleBtn').onclick = toggle;
    $('#runBtn').onclick = runNow;
    $('#delBtn').onclick = del;
    $('#refreshBtn').onclick = loadTasks;
    $('#schedBtn').onclick = toggleSched;
    $('#modalClose').onclick = closeModal;
    $('#modalCancel').onclick = closeModal;
    $('#modalSave').onclick = saveTask;
    modalBack.onclick = e => { if (e.target === modalBack) closeModal(); };
    $('#detailClose').onclick = () => detailBack.classList.add('hidden');
    $('#detailOk').onclick = () => detailBack.classList.add('hidden');
    detailBack.onclick = e => { if (e.target === detailBack) detailBack.classList.add('hidden'); };

    init();
    setInterval(() => { if (!document.hidden) loadTasks(); }, 8000);
})();
