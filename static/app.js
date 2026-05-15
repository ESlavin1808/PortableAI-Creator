/* ── Tab switching ── */
function showTab(name, btn) {
    ['build', 'dashboard', 'diagnostics'].forEach(t => {
        const el = document.getElementById('tab-' + t);
        if (el) el.classList.add('hidden');
    });
    document.querySelectorAll('.nav-tabs .btn').forEach(b => {
        b.className = 'btn btn-secondary';
    });
    document.getElementById('tab-' + name).classList.remove('hidden');
    if (btn) btn.className = 'btn btn-primary';
    if (name === 'dashboard') refreshDashboard();
    if (name === 'diagnostics') runPreflight();
}

/* ── Build workflow ── */
function startBuild() {
    const url = document.getElementById('repoUrl').value.trim();
    if (!url) { alert('Введите URL репозитория'); return; }
    document.getElementById('loading').classList.remove('hidden');
    document.getElementById('statusText').textContent = 'Анализирую репозиторий...';
    window.location.href = '/analyze?repo=' + encodeURIComponent(url);
}

async function confirmBuild() {
    if (!confirm('Начать сборку? Это может занять 10-30 минут.')) return;
    document.getElementById('loading').classList.remove('hidden');
    document.getElementById('statusText').textContent = '🔄 Сборка...';
    const logDiv = document.getElementById('buildLog');
    logDiv.style.display = 'block';
    logDiv.innerHTML = '<span class="step">▶ Запуск сборки...</span>';
    logDiv.scrollTop = logDiv.scrollHeight;

    const url = document.getElementById('repoUrl').value.trim();

    // Используем SSE для получения логов в реальном времени
    const repoName = url.split('/').pop().replace('.git', '') || 'repo';
    const eventSource = new EventSource('/build/sse?repo=' + encodeURIComponent(url));

    eventSource.onmessage = function(e) {
        if (e.data === '"__DONE__"') {
            logDiv.innerHTML += '\n<span class="ok">✅ Сборка завершена!</span>';
            document.getElementById('loading').classList.add('hidden');
            eventSource.close();
            refreshDashboard();
        } else {
            let msg;
            try { msg = JSON.parse(e.data); } catch(_) { msg = e.data; }
            const cls = msg.startsWith('✅') ? 'ok'
                     : msg.startsWith('⚠') ? 'warn'
                     : msg.startsWith('❌') ? 'err'
                     : msg.startsWith('▶') ? 'step'
                     : msg.startsWith(' ⬇') ? 'info'
                     : 'info';
            logDiv.innerHTML += '\n<span class="' + cls + '">' + escHtml(msg) + '</span>';
            logDiv.scrollTop = logDiv.scrollHeight;
        }
    };

    eventSource.onerror = function() {
        logDiv.innerHTML += '\n<span class="err">⚠️ Соединение потеряно</span>';
        document.getElementById('loading').classList.add('hidden');
        eventSource.close();
    };
}

function escHtml(s) {
    if (!s) return '';
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

/* ── Preflight / Diagnostics ── */
async function runPreflight() {
    const div = document.getElementById('preflightResult');
    div.innerHTML = '<span class="step">⏳ Проверяем систему...</span>';
    try {
        const resp = await fetch('/api/preflight', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: '{}'
        });
        const data = await resp.json();
        div.innerHTML = data.html || '<span class="warn">Нет результатов</span>';
    } catch(e) {
        div.innerHTML = '<span class="err">Ошибка сети: ' + e.message + '</span>';
    }
}

async function runSanity() {
    const div = document.getElementById('preflightResult');
    div.innerHTML = '<span class="step">🧪 Запуск sanity check...</span>';
    try {
        const resp = await fetch('/api/sanity', { method: 'POST' });
        const data = await resp.json();
        let html = '<span class="' + (data.success ? 'ok' : 'err') + '">' + (data.success ? '✅' : '❌') + ' Результат</span>';
        if (data.logs) {
            html += '\n' + data.logs.map(l => '  ' + l).join('\n');
        }
        div.innerHTML = html;
    } catch(e) {
        div.innerHTML = '<span class="err">Ошибка: ' + e.message + '</span>';
    }
}

/* ── Dashboard ── */
async function refreshDashboard() {
    try {
        const resp = await fetch('/api/apps');
        const apps = await resp.json();
        document.getElementById('appCount').textContent = apps.length;

        let totalSize = 0;
        let container = document.getElementById('appListContainer');

        if (!apps.length) {
            container.innerHTML = '<p style="text-align:center;padding:20px;color:#64748b">Пока нет собранных приложений.</p>';
            document.getElementById('appSize').textContent = '0';
            return;
        }

        let html = '<table class="app-table"><thead><tr>';
        html += '<th>Имя</th><th>Размер</th><th>Статус</th><th>Действия</th>';
        html += '</tr></thead><tbody>';

        apps.forEach(app => {
            totalSize += app.size_mb;
            const statusClass = app.is_running ? 'status-ok' : 'status-warn';
            const statusText = app.is_running ? 'Running' : 'Stopped';
            const runBtn = app.is_running
                ? `<button onclick="controlApp('${app.path}','stop')" class="btn btn-danger btn-sm">Стоп</button>`
                : `<button onclick="controlApp('${app.path}','run')" class="btn btn-success btn-sm">Запуск</button>`;

            html += `<tr>
                <td><b>${escHtml(app.name)}</b><br><small style="color:#64748b">${escHtml(app.path)}</small></td>
                <td>${app.size_mb} МБ</td>
                <td><span class="status-badge ${statusClass}">${statusText}</span></td>
                <td class="app-actions">
                    ${runBtn}
                    <button onclick="openFolder('${app.path}')" class="btn btn-secondary btn-sm">📁</button>
                    <button onclick="deleteApp('${escHtml(app.name)}','${app.path}')" class="btn btn-sm" style="background:#7f1d1d;color:#fca5a5;">🗑️</button>
                </td></tr>`;
        });

        html += '</tbody></table>';
        container.innerHTML = html;
        document.getElementById('appSize').textContent = totalSize.toFixed(1);
    } catch(e) {
        document.getElementById('appListContainer').innerHTML = '<span class="err">Ошибка загрузки: ' + e.message + '</span>';
    }
}

async function controlApp(path, action) {
    const resp = await fetch('/api/app_control', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path, action})
    });
    setTimeout(refreshDashboard, 1000);
}

function openFolder(path) {
    fetch('/api/open_folder', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path})
    });
}

async function deleteApp(name, path) {
    if (!confirm(`Удалить ${name}? Это действие необратимо.`)) return;
    const resp = await fetch('/api/delete_app', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path})
    });
    const res = await resp.json();
    refreshDashboard();
}

/* ── Auto-refresh dashboard ── */
setInterval(() => {
    const tab = document.getElementById('tab-dashboard');
    if (tab && !tab.classList.contains('hidden')) refreshDashboard();
}, 5000);

/* ── Init on page load ── */
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('loading')?.classList.add('hidden');
});
