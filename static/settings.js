function collectData() {
  const form = document.getElementById('settingsForm');
  const fd = new FormData(form);
  const data = Object.fromEntries(fd.entries());
  // Чекбоксы: FormData не включает unchecked
  const bools = ['create_launcher','enable_ai_optimization','strip_debug_symbols',
                 'run_sanity_check','enable_compression','git_shallow_clone',
                 'verify_ssl','use_proxy','log_to_file','enable_telemetry'];
  bools.forEach(k => { data[k] = form.querySelector(`[name="${k}"]`).checked; });
  return data;
}

async function saveSettings() {
  const msg = document.getElementById('statusMsg');
  msg.textContent = '⏳ Сохраняем...'; msg.style.color = '#64748b';
  try {
    const resp = await fetch('/settings/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(collectData())
    });
    const res = await resp.json();
    if (res.success) {
      msg.style.color = '#4ade80'; msg.textContent = '✅ Сохранено!';
      setTimeout(() => { msg.textContent = ''; }, 3000);
    } else {
      msg.style.color = '#f87171';
      msg.textContent = '❌ ' + (res.error || 'Ошибка сохранения');
    }
  } catch(e) {
    msg.style.color = '#f87171'; msg.textContent = '❌ Сеть недоступна';
  }
}

async function validatePaths() {
  const msg = document.getElementById('statusMsg');
  msg.textContent = '⏳ Проверяем...'; msg.style.color = '#64748b';
  await saveSettings();
  const resp = await fetch('/api/validate_paths', { method: 'POST' });
  const res = await resp.json();
  if (res.errors && res.errors.length) {
    msg.style.color = '#f87171';
    msg.textContent = '❌ ' + res.errors.join(' | ');
  } else {
    msg.style.color = '#4ade80'; msg.textContent = '✅ Все папки доступны';
    setTimeout(() => { msg.textContent = ''; }, 3000);
  }
}

async function resetSettings() {
  if (!confirm('Сбросить все настройки к заводским значениям?')) return;
  const resp = await fetch('/settings/reset', { method: 'POST' });
  if ((await resp.json()).success) location.reload();
}
