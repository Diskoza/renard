import { api, post, esc, h, ICON, toast, md } from '../core.js';

let root;
const NAMES = { low: ['Низкий', 'разговор и простые команды'], medium: ['Средний', 'файлы, анализ, небольшой код'], high: ['Высокий', 'сложный код, долгие задачи'] };
const SUGGEST = [['gemma4:e4b', 'быстрая, зрение, 4.9 ГБ'], ['qwen3.6:35b-a3b', 'сильная MoE, ~10 ГБ VRAM + RAM'], ['qwen2.5-coder:14b', 'код'], ['llama3.2:3b', 'очень лёгкая']];

export async function mount(el) { root = el; await paint(); }
export function show() { paint(); }

async function paint() {
  const [a, mem, pv] = await Promise.all([api('/api/ai'), api('/api/memory').catch(() => ({ index: '', notes: {} })),
    api('/api/providers').catch(() => ({ providers: [] }))]);
  root.innerHTML = '';
  const ext = pv.providers.filter(p => p.enabled && p.ok);
  const all = [...a.models.map(m => m.name), ...ext.flatMap(p => p.models.map(n => `@${p.id}:${n}`))];
  const opts = (cur) => `<optgroup label="Ollama (на этом ПК)">${a.models.map(m => `<option ${m.name === cur ? 'selected' : ''}>${esc(m.name)}</option>`).join('')}</optgroup>`
    + ext.map(p => `<optgroup label="${esc(p.name)}">${p.models.map(n => `<option value="@${esc(p.id)}:${esc(n)}" ${`@${p.id}:${n}` === cur ? 'selected' : ''}>${esc(n)}</option>`).join('')}</optgroup>`).join('')
    + (all.includes(cur) ? '' : `<option selected>${esc(cur)}</option>`);
  const provRow = (p) => `<div class="row prov" data-pid="${esc(p.id)}"><span class="lbl"><b>${esc(p.name)} ${p.cloud ? '<span class="chip">облако</span>' : ''}</b>
      <small>${p.enabled ? (p.ok ? `✓ работает · моделей: ${p.models.length}` : '✗ ' + esc(p.error || 'не отвечает')) : esc(p.help || '')}</small></span>
      <input class="txt" data-url value="${esc(p.base_url)}" style="width:240px">
      ${p.cloud ? `<span class="chip ${p.has_key ? '' : 'warn'}">${p.has_key ? 'ключ есть' : 'нет ключа'}</span>` : ''}
      <div class="tog ${p.enabled ? 'on' : ''}" data-pon></div>${p.builtin ? '' : `<button class="ic" data-pdel title="Убрать">${ICON('trash', 'sm')}</button>`}</div>`;
  root.appendChild(h(`<div class="page-pad"><div class="narrow">
    <h1>ИИ</h1>
    <div class="card"><h3><span class="dot ${a.ollama ? 'on' : 'error'}"></span> Ollama ${a.ollama ? 'работает' : 'не отвечает'}</h3>
      <div class="sub">${esc(a.url)} · в видеопамяти: ${a.loaded.length ? a.loaded.map(esc).join(', ') : 'ничего'} · в одной видеопамяти держится одна модель</div></div>
    <div class="card" id="provCard"><h3>${ICON('cpu')} Другие серверы моделей <span class="sub">— необязательно, Ollama остаётся главной</span></h3>
      <div class="sub">Включи сервер — его модели появятся в выборе модели для режимов ниже. Если сервер выключен или нет интернета, Renard ответит локальной моделью Ollama. Ключи — только в файлах data\\accounts\\&lt;сервер&gt;.json.</div>
      ${pv.providers.map(provRow).join('')}
      <div class="row"><input class="txt" id="pvName" placeholder="Свой сервер: название" style="width:180px"><input class="txt" id="pvUrl" placeholder="http://127.0.0.1:5000/v1 (OpenAI-совместимый)" style="flex:1"><button class="btn" id="pvAdd">Добавить</button></div></div>
    <div class="card" id="cloudCard"><h3>${ICON('cloud')} Облачные модели <span class="sub">— для трудных задач, по твоему разрешению</span></h3><div id="cloudBody" class="sub">загружаю…</div></div>
    ${Object.entries(a.modes).map(([k, m]) => `<div class="card" data-mode="${k}"><h3>${NAMES[k] ? NAMES[k][0] : k} <span class="sub">— ${NAMES[k] ? NAMES[k][1] : ''}</span></h3>
      <div class="row"><span class="lbl"><b>Модель</b></span><select class="txt" style="width:280px" data-k="model">${opts(m.model)}</select></div>
      <div class="row"><span class="lbl"><b>Температура</b><small>ниже — точнее, выше — креативнее</small></span><input type="range" min="0" max="1.2" step="0.05" value="${m.temperature ?? .3}" data-k="temperature" style="width:200px"><span class="dim" style="width:34px">${m.temperature ?? .3}</span></div>
      <div class="row"><span class="lbl"><b>Шагов с инструментами</b><small>сколько раз подряд можно вызвать инструменты в одном ответе</small></span><input class="txt" type="number" min="1" max="30" value="${m.max_steps ?? 6}" data-k="max_steps" style="width:90px"></div>
      <div class="row"><span class="lbl"><b>Держать в памяти</b><small>после ответа модель выгружается через это время</small></span><input class="txt" value="${esc(m.keep_alive ?? '5m')}" data-k="keep_alive" style="width:90px"></div>
      <div class="row"><span class="lbl"><b>Контекст</b><small>токенов (больше = больше памяти)</small></span><input class="txt" type="number" step="1024" value="${m.num_ctx ?? 8192}" data-k="num_ctx" style="width:110px"></div>
    </div>`).join('')}
    <div class="card"><h3>${ICON('download')} Модели на диске</h3>
      ${a.models.map(m => `<div class="row"><span class="lbl"><b>${esc(m.name)}</b><small>${esc(m.family)} ${esc(m.params)} · ${m.size_gb} ГБ</small></span>${a.loaded.includes(m.name) ? '<span class="chip">в VRAM</span>' : ''}</div>`).join('')}
      <div class="row"><input class="txt" id="pullName" placeholder="имя модели из ollama.com/library, например llama3.2:3b"><button class="btn primary" id="pull">Скачать</button></div>
      <div class="sub" style="margin-top:8px">Подходят: ${SUGGEST.map(([n, d]) => `<a class="sg" style="cursor:pointer">${n}</a> (${d})`).join(' · ')}</div></div>
    <div class="card"><h3>${ICON('brain')} Память агента</h3><div class="md" style="max-height:300px;overflow:auto">${md((mem.index || '') + '\n\n' + Object.values(mem.notes || {}).join('\n'))}</div></div>
    <div class="card" id="arcCard"><h3>${ICON('archive')} Старые чаты с других ИИ</h3><div id="arcBody" class="sub">загружаю…</div></div>
  </div></div>`));
  archiveCard();
  cloudCard();
  root.querySelectorAll('[data-mode]').forEach(card => card.querySelectorAll('[data-k]').forEach(inp => {
    inp.onchange = async () => {
      let v = inp.value; if (['temperature'].includes(inp.dataset.k)) v = parseFloat(v); if (['max_steps', 'num_ctx'].includes(inp.dataset.k)) v = parseInt(v);
      await post('/api/ai', { mode: card.dataset.mode, [inp.dataset.k]: v }); toast('Сохранено');
    };
    if (inp.type === 'range') inp.oninput = () => inp.nextElementSibling.textContent = inp.value;
  }));
  root.querySelectorAll('.prov').forEach(row => {
    const pid = row.dataset.pid;
    row.querySelector('[data-pon]').onclick = async (e) => {
      const on = !e.target.classList.contains('on');
      const r = await post('/api/providers/' + pid, { enabled: on, base_url: row.querySelector('[data-url]').value });
      toast(on ? (r.ok ? `${r.name}: работает, моделей ${r.models.length}` : `${r.name}: ${r.error || 'не отвечает'}`) : `${r.name} выключен`, on && !r.ok ? 'err' : undefined);
      paint();
    };
    row.querySelector('[data-url]').onchange = async (e) => { await post('/api/providers/' + pid, { base_url: e.target.value }); paint(); };
    row.querySelector('[data-pdel]')?.addEventListener('click', async () => { await fetch('/api/providers/' + pid, { method: 'DELETE' }); paint(); });
  });
  root.querySelector('#pvAdd').onclick = async () => {
    const name = root.querySelector('#pvName').value.trim(), url = root.querySelector('#pvUrl').value.trim();
    if (!name || !/^https?:\/\//.test(url)) { toast('Нужны название и адрес http(s)://…/v1', 'err'); return; }
    const pid = name.toLowerCase().replace(/[^\w-]+/g, '') || 'custom' + (Date.now() % 1000);
    const r = await post('/api/providers/' + encodeURIComponent(pid), { name, base_url: url, enabled: true });
    toast(r.ok ? `${r.name}: работает, моделей ${r.models.length}` : `${r.name}: ${r.error || 'не отвечает'}`, r.ok ? undefined : 'err'); paint();
  };
  root.querySelector('#pull').onclick = async () => { const n = root.querySelector('#pullName').value.trim(); if (!n) return; await post('/api/ai/pull', { name: n }); toast('Скачиваю ' + n + ' — прогресс внизу'); };
  root.querySelectorAll('.sg').forEach(a => a.onclick = () => root.querySelector('#pullName').value = a.textContent);
}

const PERM = [['off', 'Выкл', 'никогда не обращаться'], ['ask', 'Спрашивать', 'Renard спросит «спросить у облака?»'], ['auto', 'Авто', 'сам отправит трудную задачу']];
const EFFORT = [['low', 'быстро'], ['medium', 'средне'], ['high', 'тщательно'], ['xhigh', 'очень тщательно'], ['max', 'максимум']];
async function cloudCard() {
  const box = root.querySelector('#cloudBody'); if (!box) return;
  let c; try { c = await api('/api/cloud'); } catch (e) { box.textContent = 'не загрузилось'; return; }
  const cur = c.clouds.find(x => x.id === c.provider);
  box.className = '';
  box.innerHTML = `<div class="sub" style="margin-bottom:8px">Когда задача слишком сложная для локальной модели (большой код, архитектура, длинный разбор),
      Renard может передать её сильной облачной модели. Уходит только текст задачи и твоя последняя фраза — без памяти и файлов.
      Ключ хранится только в data\\accounts на этом ПК и в окно больше не показывается.</div>
    <div class="row"><span class="lbl"><b>Разрешение</b><small>${esc((PERM.find(p => p[0] === c.permission) || PERM[0])[2])}</small></span>
      <div style="display:flex;gap:4px">${PERM.map(([v, t]) => `<button class="btn ${c.permission === v ? 'primary' : ''}" data-perm="${v}">${t}</button>`).join('')}</div></div>
    <div class="row"><span class="lbl"><b>Сервис</b></span>
      <select class="txt" id="clProv" style="width:240px"><option value="">— выбери —</option>${c.clouds.map(x => `<option value="${esc(x.id)}" ${x.id === c.provider ? 'selected' : ''}>${esc(x.name)}${x.has_key ? ' ✓' : ''}</option>`).join('')}</select></div>
    ${c.provider ? `<div class="row"><span class="lbl"><b>Ключ API</b><small>${esc(cur ? cur.help : '')}</small></span>
      <input class="txt" type="password" id="clKey" autocomplete="off" placeholder="${c.has_key ? 'ключ сохранён — вставь новый, чтобы заменить' : 'вставь ключ'}" style="width:240px">
      <span class="chip ${c.has_key ? '' : 'warn'}">${c.has_key ? 'ключ есть' : 'нет ключа'}</span></div>
    <div class="row"><span class="lbl"><b>Модель</b></span><select class="txt" id="clModel" style="width:min(380px,100%)"><option>${esc(c.model || 'загружаю список…')}</option></select></div>
    ${c.provider === 'anthropic' ? `<div class="row"><span class="lbl"><b>Глубина</b><small>тщательнее — дольше и дороже</small></span>
      <select class="txt" id="clEffort" style="width:180px">${EFFORT.map(([v, t]) => `<option value="${v}" ${c.effort === v ? 'selected' : ''}>${t}</option>`).join('')}</select></div>` : ''}
    <div class="row"><button class="btn" id="clTest" ${c.has_key && c.model ? '' : 'disabled'}>Проверить связь</button><span class="sub" id="clRes"></span></div>` : ''}`;
  const save = async (d) => { const r = await post('/api/cloud', d); if (r.ok === false) toast(r.error, 'err'); return r; };
  box.querySelectorAll('[data-perm]').forEach(b => b.onclick = async () => { await save({ permission: b.dataset.perm }); toast('Сохранено'); cloudCard(); });
  box.querySelector('#clProv').onchange = async (e) => { await save({ provider: e.target.value, model: '' }); cloudCard(); };
  const key = box.querySelector('#clKey');
  if (key) key.onchange = async () => { const v = key.value.trim(); if (!v) return; await save({ provider: c.provider, key: v }); key.value = ''; toast('Ключ сохранён'); cloudCard(); };
  box.querySelector('#clEffort')?.addEventListener('change', async (e) => { await save({ effort: e.target.value }); toast('Сохранено'); });
  const sel = box.querySelector('#clModel');
  if (sel) {
    const m = (await api('/api/cloud/models?provider=' + encodeURIComponent(c.provider)).catch(() => ({ models: [] }))).models;
    const ids = m.filter(x => x.id).map(x => x.id);
    sel.innerHTML = (c.model && !ids.includes(c.model) ? `<option selected>${esc(c.model)}</option>` : (c.model ? '' : '<option value="" selected>— выбери модель —</option>'))
      + m.map(x => x.id ? `<option value="${esc(x.id)}" ${x.id === c.model ? 'selected' : ''}>${esc(x.id)}${x.note ? ' — ' + esc(x.note) : ''}</option>` : `<option disabled>${esc(x.note)}</option>`).join('');
    sel.onchange = async () => { await save({ model: sel.value }); toast('Сохранено'); cloudCard(); };
  }
  box.querySelector('#clTest')?.addEventListener('click', async (e) => {
    const res = box.querySelector('#clRes'); e.target.disabled = true; res.textContent = 'спрашиваю…';
    const r = await post('/api/cloud/test', {}, { timeout: 0 }).catch(err => ({ ok: false, error: err.message }));
    res.textContent = r.ok ? '✓ ' + r.answer : '✗ ' + r.error; e.target.disabled = false;
  });
}

const SRC = { chatgpt: 'ChatGPT', claude: 'Claude' };
async function archiveCard() {
  const box = root.querySelector('#arcBody'); if (!box) return;
  let a; try { a = await api('/api/archive'); } catch (e) { box.textContent = 'не загрузилось'; return; }
  const todo = (a.found || []).filter(f => !f.imported);
  box.className = '';
  box.innerHTML = `<div class="sub" style="margin-bottom:8px">Экспорт из ChatGPT (Настройки → Управление данными → Экспорт) или Claude (Settings → Privacy → Export data) —
      агент ищет в этих чатах, когда спрашиваешь «что мне раньше советовали про…», «как я настраивал…». Всё хранится только на этом ПК.</div>
    ${(a.sources || []).length ? a.sources.map(s => `<div class="row"><span class="lbl"><b>${SRC[s.source] || esc(s.source)}</b><small>аккаунт ${esc(s.account)} · ${s.conversations} чатов · ${esc(s.first)} — ${esc(s.last)}</small></span>
        <button class="btn" data-forget="${esc(s.source)}|${esc(s.account)}">Забыть</button></div>`).join('')
      : '<div class="sub">Пока ничего не импортировано.</div>'}
    ${(a.sources || []).length ? `<div class="sub" style="margin:4px 0 8px">Всего сообщений: ${a.messages}</div>` : ''}
    ${todo.length ? `<div class="row"><span class="lbl"><b>Нашёл в «Загрузках»</b><small>${todo.map(f => `${SRC[f.kind]} · ${f.size_mb} МБ · ${esc(f.date)}`).join('<br>')}</small></span>
        <button class="btn primary" id="arcAll">Импортировать (${todo.length})</button></div>` : ''}
    <div class="row"><span class="lbl"><b>Свой файл</b><small>.zip экспорта целиком, распаковывать не надо</small></span>
      <input type="file" accept=".zip" id="arcFile" style="max-width:230px"></div>
    <div class="row"><input class="txt" id="arcQ" placeholder="проверить поиск: например samba или моды 1.21.1"><button class="btn" id="arcFind">Найти</button></div>
    <div id="arcHits" class="sub"></div>`;
  const run = async (path) => {
    try { return await post('/api/archive/import', { path }, { timeout: 0 }); } catch (e) { toast(e.message, 'error'); return null; }
  };
  box.querySelector('#arcAll')?.addEventListener('click', async (e) => {
    e.target.disabled = true; e.target.textContent = 'импортирую…';
    let n = 0; for (const f of todo) { const r = await run(f.path); if (r) n += r.new_conversations; }
    toast(`Готово: ${n} чатов`); archiveCard();
  });
  box.querySelector('#arcFile').onchange = async (e) => {
    const f = e.target.files[0]; if (!f) return;
    toast('Загружаю ' + f.name + '…');
    const up = await (await fetch('/api/upload?name=' + encodeURIComponent(f.name), { method: 'POST', body: f })).json();
    const r = await run(up.path); if (r) toast(`Готово: ${r.new_conversations} новых чатов`); archiveCard();
  };
  box.querySelectorAll('[data-forget]').forEach(b => b.onclick = async () => {
    const [source, account] = b.dataset.forget.split('|');
    if (!confirm(`Удалить из памяти агента импортированные чаты ${SRC[source] || source} (${account})? Сам файл экспорта останется.`)) return;
    await post('/api/archive/forget', { source, account }); toast('Забыл'); archiveCard();
  });
  const find = async () => {
    const q = box.querySelector('#arcQ').value.trim(); if (!q) return;
    const r = await api('/api/archive/search?q=' + encodeURIComponent(q));
    box.querySelector('#arcHits').innerHTML = r.hits.length ? r.hits.map(x => `<div style="margin-top:8px"><b>${esc(x.date)} · ${SRC[x.source] || ''} · ${esc(x.title)}</b><br>
      ты: ${esc(x.question.slice(0, 180))}<br><span class="dim">ответ: ${esc(x.answer.slice(0, 220))}</span></div>`).join('') : 'ничего не нашёл';
  };
  box.querySelector('#arcFind').onclick = find;
  box.querySelector('#arcQ').onkeydown = (e) => { if (e.key === 'Enter') find(); };
}
