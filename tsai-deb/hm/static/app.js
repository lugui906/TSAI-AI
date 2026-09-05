(() => {
    const $ = s => document.querySelector(s);
    const statusText = $('#statusText'), statusDot = $('#statusDot');
    const durText = $('#durText'), aimText = $('#aimText'), minutesBox = $('#minutesBox');
    const toast = $('#toast');
    const startInternal = $('#startInternal'), startMic = $('#startMic'), stopBtn = $('#stopBtn');
    const histBtn = $('#histBtn'), histPane = $('#histPane'), histList = $('#histList');

    let recording = false, lastMinutes = '', histVisible = false, hasHistory = false;
    let toastTimer = null;

    function toastMsg(t) {
        toast.textContent = t;
        toast.classList.add('show');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toast.classList.remove('show'), 1800);
    }
    function fmtDur(sec) {
        sec = Math.floor(sec || 0);
        const m = Math.floor(sec / 60), s = sec % 60;
        return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }
    async function api(url, opts = {}) {
        try {
            const r = await fetch(url, opts);
            if (r.status === 404) return { _404: true };
            return await r.json();
        } catch (e) { return {}; }
    }
    function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

    async function start(source) {
        const r = await api('/api/start', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source }),
        });
        if (!r.ok) { toastMsg(r.error || '启动失败'); return; }
        toastMsg('已开始录制');
    }
    async function stop() {
        const r = await api('/api/stop', { method: 'POST' });
        if (!r.ok) { toastMsg(r.error || '停止失败'); return; }
        toastMsg('正在停止并生成纪要…');
    }

    async function loadHistory() {
        const d = await api('/api/history');
        if (d._404) return;
        hasHistory = true;
        histBtn.style.display = '';
        histList.innerHTML = d.length
            ? d.map((r, i) => `<button class="list-item" data-i="${i}">${esc(r.time || '')}  ${esc(r.title || '对话')}</button>`).join('')
            : '<div class="empty">暂无历史记录</div>';
        histList.querySelectorAll('.list-item').forEach(b => {
            b.onclick = () => {
                const rec = d[Number(b.dataset.i)];
                if (!rec) return;
                lastMinutes = rec.text || '';
                minutesBox.textContent = rec.text || '';
                minutesBox.scrollTop = 0;
                toastMsg(`已加载: ${rec.title || ''}`);
            };
        });
    }
    async function clearHistory() {
        await api('/api/history/clear', { method: 'POST' });
        await loadHistory();
        toastMsg('历史已清空');
    }

    async function poll() {
        const s = await api('/api/status');
        if (s._404) { setTimeout(poll, 1000); return; }
        recording = s.recording;
        statusText.textContent = s.status;
        statusDot.className = 'dot' + (s.recording ? ' run' : (s.aim === '失败' ? ' err' : ''));
        durText.textContent = '录音时长: ' + fmtDur(s.duration);
        aimText.textContent = 'AIM: ' + s.aim;
        startInternal.disabled = s.recording;
        startMic.disabled = s.recording;
        stopBtn.disabled = !s.recording;
        if (s.minutes !== lastMinutes && !histVisible) {
            lastMinutes = s.minutes;
            minutesBox.textContent = s.minutes || '尚未生成纪要。开始录制并点击「停止并生成纪要」后，此处将显示 AI 生成的会议纪要。';
            minutesBox.scrollTop = minutesBox.scrollHeight;
        }
    }

    startInternal.onclick = () => start('internal');
    startMic.onclick = () => start('mic');
    stopBtn.onclick = stop;
    histBtn.onclick = () => {
        histVisible = !histVisible;
        histPane.style.display = histVisible ? '' : 'none';
        if (histVisible) loadHistory();
    };
    histClear.onclick = clearHistory;

    setInterval(poll, 1000);
    poll();
    loadHistory();
})();
