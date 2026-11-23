import { api, post, del, esc, h, ICON, toast } from '../core.js';
import { lessonsPanel } from '../feedback.js';

let root, tab = 'skills';
const TABS = [['skills', 'Навыки'], ['lessons', 'Уроки'], ['connectors', 'Коннекторы'], ['plugins', 'Свои плагины'], ['runtimes', 'Среды выполнения']];

export async function mount(el) { root = el; }
export function show(params = []) { tab = params[0] || tab; paint(); }

async function paint() {
  root.innerHTML = '';
  const wrap = h(`<div class="page-pad"><div class="narrow" style="max-width:980px">
    <h1>Плагины</h1>
    <div class="seg2" style="margin-bottom:16px">${TABS.map(([k, t]) => `<button data-t="${k}" class="${k === tab ? 'on' : ''}">${t}</button>`).join('')}</div>
    <div id="pbody"></div></div></div>`);
  root.appendChild(wrap);
  wrap.querySelectorAll('[data-t]').forEach(b => b.onclick = () => { location.hash = '#/plugins/' + b.dataset.t; });
  const body = wrap.querySelector('#pbody');
  if (tab === 'skills') await skills(body);
  if (tab === 'lessons') {
    const card = h(`<div class="card"><h3>${ICON('grad')} Уроки из 👎</h3><div class="sub">Поставь 👎 под ответом и напиши, что не так, —
      Renard сделает из этого правило и будет сам применять его в похожих запросах. Неудачный урок можно удалить.</div><div id="lsn"></div></div>`);
    body.appendChild(card); await lessonsPanel(card.querySelector('#lsn'));
  }
  if (tab === 'connectors') await connectors(body);
  if (tab === 'plugins') { await builtinPlugins(body); await ownPlugins(body); }
  if (tab === 'runtimes') await runtimes(body);
}

async function builtinPlugins(body) {
  const b = await api('/api/builtin_plugins').catch(() => null); if (!b) return;
  const STATUS = { running: '⏳ работает', done: '✓ готово', stopped: '■ остановлен', timeout: '⌛ время вышло' };
  body.appendChild(h(`<div class="card"><h3>Встроенные плагины</h3>
    <div class="row"><span class="lbl"><b>♞ Шахматы с Renard</b><small>Движок: ${esc(b.chess.engine)}, 5 уровней, Renard комментирует партию и реагирует аватаром. Голосом: «сыграем в шахматы».</small></span>
      <button class="btn ok" onclick="location.hash='#/chess'">Играть</button></div>
    <div class="row"><span class="lbl"><b>⌨ Агенты-программисты</b><small>Renard поручает задачу по коду агенту на ПК и сообщает, когда он закончит: «пусть Claude Code допишет тесты в проекте …». Запуск — только после «да».</small></span></div>
    <div class="chips" style="margin:-4px 0 6px">${b.coders.map(c => `<span class="chip ${c.installed ? 'on' : 'ghost'}">${c.installed ? '✓' : '·'} ${esc(c.name)}</span>`).join('')}</div>
    ${b.jobs.length ? `<div class="sub">Последние задачи:</div>` + b.jobs.reverse().map(j => `<div class="row"><span class="lbl"><b>${esc(j.task.slice(0, 80))}</b><small>${esc(j.agent)} · ${esc(j.folder)}</small></span><span class="chip">${STATUS[j.status] || esc(j.status)}</span></div>`).join('') : ''}
  </div>`));
}

async function skills(body) {
  const r = await api('/api/skills');
  body.appendChild(h(`<div>
    <div class="card"><h3>${ICON('book')} Навыки <span class="grow"></span><button class="btn primary" id="sNew">${ICON('plus')} Создать навык</button></h3>
      <div class="sub">Навык — инструкция в формате SKILL.md (как у Claude, Hermes, OpenClaw). 1–2 навыка, подходящих к запросу, Renard подставляет сам (по описанию и полю triggers) — вызывать вручную не нужно.</div>
      ${r.skills.map(s => `<div class="row"><span class="lbl"><b>${esc(s.name)} <span class="dim">${esc(s.source)}</span></b><small>${esc(s.description)}</small></span>
        <button class="btn sm" data-ed="${esc(s.name)}">${ICON('edit', 'sm')}</button><button class="btn sm" data-rm="${esc(s.name)}">${ICON('trash', 'sm')}</button><div class="tog ${s.enabled ? 'on' : ''}" data-tg="${esc(s.name)}"></div></div>`).join('')}</div>
    <div class="card"><h3>${ICON('search')} Найти и установить</h3>
      <div class="row"><input class="txt" id="sQ" placeholder="например: pdf, git, обзор кода, minecraft"><div class="seg2" id="sSrc"><button data-v="clawhub" class="on">ClawHub</button><button data-v="hermes">Hermes</button></div><button class="btn primary" id="sGo">Найти</button></div>
      <div id="sRes"></div></div></div>`));
  body.querySelector('#sNew').onclick = () => editSkill({});
  body.querySelectorAll('[data-ed]').forEach(b => b.onclick = async () => editSkill(await api('/api/skills/' + encodeURIComponent(b.dataset.ed))));
  body.querySelectorAll('[data-rm]').forEach(b => b.onclick = async () => { if (!confirm(`Удалить навык ${b.dataset.rm}? (в корзину)`)) return; const x = await del('/api/skills/' + encodeURIComponent(b.dataset.rm)); toast(x.result); paint(); });
  body.querySelectorAll('[data-tg]').forEach(t => t.onclick = async () => { const on = !t.classList.contains('on'); t.classList.toggle('on', on); await post('/api/skills', { name: t.dataset.tg, toggle: on }); });
  let src = 'clawhub';
  body.querySelectorAll('#sSrc button').forEach(b => b.onclick = () => { src = b.dataset.v; body.querySelectorAll('#sSrc button').forEach(x => x.classList.toggle('on', x === b)); });
  const go = async () => {
    const res = body.querySelector('#sRes'); res.innerHTML = '<div class="sub" style="padding:8px">ищу…</div>';
    const x = await api(`/api/skills_search?source=${src}&q=` + encodeURIComponent(body.querySelector('#sQ').value));
    res.innerHTML = x.results.map(s => `<div class="row"><span class="lbl"><b>${esc(s.title)}</b><small>${esc(s.description)}</small></span><button class="btn sm primary" data-in="${esc(s.id)}">Установить</button></div>`).join('') || `<div class="sub" style="padding:8px">${esc(x.error || 'ничего не нашлось')}</div>`;
    res.querySelectorAll('[data-in]').forEach(b => b.onclick = async () => { b.textContent = '…'; const y = await post('/api/skills_install', { id: b.dataset.in }); toast(y.result.slice(0, 220)); paint(); });
  };
  body.querySelector('#sGo').onclick = go; body.querySelector('#sQ').onkeydown = (e) => e.key === 'Enter' && go();
}
function editSkill(s) {
  const m = h(`<div class="modal-bg"><div class="modal" style="width:min(820px,94vw)"><h2>${s.name ? 'Навык ' + esc(s.name) : 'Новый навык'}</h2>
    <label>Название (латиницей, через дефис)</label><input class="txt" id="kn" value="${esc(s.name || '')}" placeholder="weekly-report">
    <label>Описание — когда использовать (это видит агент)</label><input class="txt" id="kd" value="${esc(s.description || '')}" placeholder="Когда пользователь просит недельный отчёт по проекту…">
    <label>Инструкция (Markdown)</label><textarea class="txt" id="kb" rows="16" placeholder="# Как делать\n1. Сначала…\n2. Потом…">${esc(s.body || '')}</textarea>
    <div class="actions"><button class="btn" id="kx">Отмена</button><button class="btn primary" id="ks">Сохранить</button></div></div></div>`);
  document.body.appendChild(m);
  m.querySelector('#kx').onclick = () => m.remove();
  m.querySelector('#ks').onclick = async () => { await post('/api/skills', { name: m.querySelector('#kn').value, description: m.querySelector('#kd').value, body: m.querySelector('#kb').value }); m.remove(); toast('Навык сохранён'); paint(); };
}

async function connectors(body) {
  const r = await api('/api/mcp');
  body.appendChild(h(`<div>
    <div class="card"><h3>${ICON('link')} Подключённые сервисы</h3>
      <div class="sub">Коннекторы — это MCP-серверы: стандарт, через который ИИ подключают к GitHub, Supabase, YouTube, почте и сотням других сервисов. Код Renard менять не нужно.</div>
      ${r.servers.map(s => `<div class="row"><span class="dot ${s.status}"></span><span class="lbl"><b>${esc(s.name)}</b><small>${s.status === 'ready' ? s.tools.length + ' инструментов: ' + esc(s.tools.slice(0, 8).join(', ')) : s.status === 'needs_key' ? '🔑 ждёт ключ — ' + esc(s.error) : esc(s.status + (s.error ? ': ' + s.error : ''))}</small></span>
        <button class="btn sm" data-rs="${esc(s.name)}">${ICON('refresh', 'sm')}</button><button class="btn sm" data-del="${esc(s.name)}">${ICON('trash', 'sm')}</button><div class="tog ${s.enabled ? 'on' : ''}" data-en="${esc(s.name)}"></div></div>`).join('') || '<div class="sub" style="margin-top:8px">Пока ничего не подключено.</div>'}</div>
    <div class="card"><h3>${ICON('plus')} Добавить</h3><div class="grid3" style="margin-top:8px">
      ${r.presets.map(p => `<div class="pcard" data-pre="${p.id}"><b>${esc(p.title)}</b><small>${esc(p.desc)}</small><div class="dim" style="margin-top:6px">${esc(p.command)} ${esc(p.args[p.args.length - 1])}</div></div>`).join('')}
      <div class="pcard" data-pre="custom"><b>Свой сервер</b><small>любой MCP-сервер: команда + аргументы + переменные</small></div></div></div></div>`));
  body.querySelectorAll('[data-pre]').forEach(c => c.onclick = () => editMcp(r.presets.find(p => p.id === c.dataset.pre) || { id: '', title: 'Свой сервер', command: 'npx', args: [], env: {} }, r.runtimes));
  body.querySelectorAll('[data-rs]').forEach(b => b.onclick = async () => { await post(`/api/mcp/${b.dataset.rs}/restart`); toast('Перезапускаю…'); setTimeout(paint, 2500); });
  body.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => { if (confirm('Отключить ' + b.dataset.del + '?')) { await del('/api/mcp/' + b.dataset.del); paint(); } });
  body.querySelectorAll('[data-en]').forEach(t => t.onclick = async () => { const s = r.servers.find(x => x.name === t.dataset.en); await post('/api/mcp', { name: s.name, enabled: !s.enabled, command: s.command, args: s.args }); paint(); });
}
function editMcp(p, rt) {
  const need = p.command === 'uvx' ? 'uvx' : p.command === 'npx' ? 'npx' : null;
  const m = h(`<div class="modal-bg"><div class="modal"><h2>${esc(p.title)}</h2>
    ${p.help ? `<div class="sub">${esc(p.help)}</div>` : ''}
    ${need && !rt[need] ? `<div class="confirm">⚠ Не найден ${need}. Установи ${need === 'npx' ? 'Node.js (winget install OpenJS.NodeJS.LTS)' : 'uv (winget install astral-sh.uv)'} — вкладка «Среды выполнения».</div>` : ''}
    <label>Имя</label><input class="txt" id="mn" value="${esc(p.id || '')}" placeholder="github">
    <label>Команда</label><input class="txt" id="mc" value="${esc(p.command || 'npx')}">
    <label>Аргументы (по одному в строке)</label><textarea class="txt" id="ma" rows="4">${esc((p.args || []).join('\n'))}</textarea>
    <label>Переменные окружения (КЛЮЧ=значение, токены хранятся только на этом ПК)</label><textarea class="txt" id="me" rows="3">${esc(Object.entries(p.env || {}).map(([k, v]) => `${k}=${v}`).join('\n'))}</textarea>
    <div class="actions"><button class="btn" id="mx">Отмена</button><button class="btn primary" id="ms">Подключить</button></div></div></div>`);
  document.body.appendChild(m);
  m.querySelector('#mx').onclick = () => m.remove();
  m.querySelector('#ms').onclick = async () => {
    const env = Object.fromEntries(m.querySelector('#me').value.split('\n').map(l => l.trim()).filter(l => l.includes('=')).map(l => [l.slice(0, l.indexOf('=')).trim(), l.slice(l.indexOf('=') + 1).trim()]));
    const r = await post('/api/mcp', { name: m.querySelector('#mn').value || 'server', command: m.querySelector('#mc').value, args: m.querySelector('#ma').value.split('\n').map(s => s.trim()).filter(Boolean), env, enabled: true });
    m.remove(); toast(`Запускаю ${r.name}… первый запуск скачивает пакет (до минуты)`); setTimeout(paint, 4000); setTimeout(paint, 15000);
  };
}

async function ownPlugins(body) {
  const r = await api('/api/plugins');
  body.appendChild(h(`<div><div class="card"><h3>${ICON('plug')} Свои плагины <span class="grow"></span><button class="btn primary" id="plNew">${ICON('plus')} Создать плагин</button></h3>
    <div class="sub">Плагин — папка в <code>${esc(r.dir)}</code>: <code>tools.py</code> (новые инструменты на Python), <code>skills/</code> (навыки), <code>plugin.json</code>. Можно попросить Renard в режиме «высокий» написать плагин за тебя.</div>
    ${r.plugins.map(p => `<div class="row"><span class="lbl"><b>${esc(p.title || p.name)}</b><small>${esc(p.description || '')} · ${esc(p.status)}${p.skills.length ? ' · навыки: ' + esc(p.skills.join(', ')) : ''}</small></span>
      <button class="btn sm" data-open="${esc(p.dir)}">${ICON('folder', 'sm')} открыть</button><div class="tog ${p.enabled !== false ? 'on' : ''}" data-en="${esc(p.name)}"></div></div>`).join('') || '<div class="sub" style="margin-top:8px">Пока нет своих плагинов.</div>'}
    <div class="row"><span class="lbl"><b>Применить изменения</b><small>новые инструменты подхватываются после перезапуска сервера (~5 с)</small></span><button class="btn" id="plRestart">${ICON('refresh')} Перезапустить сервер</button></div></div></div>`));
  body.querySelector('#plNew').onclick = async () => { const n = prompt('Название плагина (латиницей):', 'my-tools'); if (!n) return; const x = await post('/api/plugins', { name: n, create: true }); toast('Создан ' + x.dir); post('/api/open_folder', { path: x.dir }); paint(); };
  body.querySelectorAll('[data-open]').forEach(b => b.onclick = () => post('/api/open_folder', { path: b.dataset.open }).catch(e => toast(e.message, 'err')));
  body.querySelectorAll('[data-en]').forEach(t => t.onclick = async () => { const on = !t.classList.contains('on'); t.classList.toggle('on', on); await post('/api/plugins', { name: t.dataset.en, enabled: on }); toast('Включится после перезапуска сервера'); });
  body.querySelector('#plRestart').onclick = async () => { await post('/api/restart').catch(() => {}); toast('Перезапускаю сервер…'); setTimeout(() => location.reload(), 6000); };
}

async function runtimes(body) {
  const r = await api('/api/mcp');
  const INFO = { node: ['Node.js', 'OpenJS.NodeJS.LTS', 'коннекторы на npx (GitHub, Supabase, YouTube…)'], npx: ['npx', null, 'идёт вместе с Node.js'],
    uv: ['uv', 'astral-sh.uv', 'Python-коннекторы (uvx)'], uvx: ['uvx', null, 'идёт вместе с uv'], python: ['Python', 'Python.Python.3.11', 'скрипты и навыки'],
    git: ['Git', 'Git.Git', 'установка навыков Hermes'], docker: ['Docker', 'Docker.DockerDesktop', 'некоторые коннекторы в контейнерах'] };
  body.appendChild(h(`<div class="card"><h3>Среды выполнения</h3><div class="sub">Нужны, чтобы запускать коннекторы и навыки. Установка — командой в PowerShell (winget).</div>
    ${Object.entries(r.runtimes).map(([k, ok]) => `<div class="row"><span class="dot ${ok ? 'on' : 'error'}"></span><span class="lbl"><b>${INFO[k][0]}</b><small>${INFO[k][2]}</small></span>
      ${ok ? '<span class="chip">установлено</span>' : INFO[k][1] ? `<code class="dim">winget install ${INFO[k][1]}</code>` : '<span class="sub">—</span>'}</div>`).join('')}</div>`));
}
