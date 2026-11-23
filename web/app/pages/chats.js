import { api, post, del, on, esc, h, ICON, $, prefs, toast, uid, state } from '../core.js';
import { Composer } from '../composer.js';
const plural = (n, one, few, many) => `${n} ${n % 10 === 1 && n % 100 !== 11 ? one : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? few : many}`;
import { ChatView } from '../chatview.js';

let root, side, main, view, comp, chats = [], projects = [], current = { kind: 'chat', id: null };
let pendingFirst = null;
const SRC = { telegram: '✈', voice: '🎙', task: '⏰', command: '⚙', window: '' };

export async function mount(el) {
  root = el;
  el.appendChild(h(`<aside class="side">
      <div class="nav">
        <a class="newchat" data-go="new">${ICON('plus')} Новый чат</a>
        <a data-go="search">${ICON('search')} Поиск</a>
        <a data-go="projects">${ICON('box')} Проекты</a>
        <a data-go="tasks">${ICON('clock')} Запланированные задачи</a>
        <a data-go="files">${ICON('folder')} Файлы</a>
      </div>
      <div class="search" style="display:none"><input class="txt" placeholder="Поиск по чатам…"></div>
      <div class="list"></div>
    </aside>
    <div class="chat-main"></div>`));
  side = el.querySelector('.side'); main = el.querySelector('.chat-main');
  side.querySelectorAll('[data-go]').forEach(a => a.onclick = () => {
    const g = a.dataset.go;
    if (g === 'new') location.hash = '#/chats/new';
    else if (g === 'search') { const s = side.querySelector('.search'); s.style.display = s.style.display ? '' : 'none'; s.querySelector('input').focus(); }
    else location.hash = '#/chats/' + g;
  });
  let st; side.querySelector('.search input').oninput = (e) => { clearTimeout(st); st = setTimeout(() => loadList(e.target.value), 250); };
  on('chat-done', async () => { await loadList(); if (view && main.querySelector('.chat-head')) paintHead(); });
  on('confirm-answer', (a) => { if (location.hash.startsWith('#/chats') && view) view.send(a, { perm: (prefs.chat || {}).permission }); });
  on('task', () => { if (current.kind === 'tasks') showTasks(); });
  await loadList();
}

export function show(params = []) {
  const [kind, id] = params;
  if (kind === 'c' && id) openChat(id);
  else if (kind === 'projects') showProjects();
  else if (kind === 'p' && id) showProject(id);
  else if (kind === 'tasks') showTasks();
  else if (kind === 'files') showFiles();
  else if (kind === 'new') newChat(id || '');
  else if (current.kind === 'chat' && view && view.session) {  }
  else newChat('');
  side.querySelectorAll('.nav a').forEach(a => a.classList.toggle('on', a.dataset.go === kind));
}

async function loadList(q = '') {
  [{ chats }, { projects }] = await Promise.all([api('/api/chats?q=' + encodeURIComponent(q)), api('/api/projects')]);
  const list = side.querySelector('.list');
  const pinned = chats.filter(c => c.pinned), recent = chats.filter(c => !c.pinned);
  const pinnedProjects = projects.filter(p => p.pinned);
  const item = (c) => `<div class="it ${current.kind === 'chat' && current.id === c.id ? 'on' : ''}" data-c="${esc(c.id)}">
      ${SRC[c.src] ? `<span>${SRC[c.src]}</span>` : ''}<span class="t">${esc(c.title)}</span><span class="badge">${c.when.split(' ')[0]}</span></div>`;
  list.innerHTML =
    (pinnedProjects.length || pinned.length ? `<div class="sec">Закреплённые</div>` : '') +
    pinnedProjects.map(p => `<div class="it ${current.kind === 'project' && current.id === p.id ? 'on' : ''}" data-p="${p.id}">${ICON('box', 'proj')}<span class="t">${esc(p.name)}</span></div>` +
      chats.filter(c => c.project === p.id).slice(0, 4).map(c => `<div class="it" style="padding-left:30px" data-c="${esc(c.id)}"><span class="t">${esc(c.title)}</span></div>`).join('')).join('') +
    pinned.map(item).join('') +
    `<div class="sec">${q ? 'Найдено' : 'Недавние'}</div>` + (recent.map(item).join('') || '<div class="sub" style="padding:6px 10px">пусто</div>');
  list.querySelectorAll('[data-c]').forEach(e => e.onclick = () => location.hash = '#/chats/c/' + e.dataset.c);
  list.querySelectorAll('[data-p]').forEach(e => e.onclick = () => location.hash = '#/chats/p/' + e.dataset.p);
}

function chatShell() {
  main.innerHTML = '';
  main.appendChild(h(`<div class="chat-head"><span class="crumb"></span><span class="title"></span><span class="grow"></span>
    <button class="ic" data-a="pin" title="Закрепить">${ICON('pin')}</button>
    <button class="ic" data-a="rename" title="Переименовать">${ICON('edit')}</button>
    <button class="ic" data-a="delete" title="Удалить чат">${ICON('trash')}</button></div>`));
  const scroll = h(`<div class="chat-scroll scroll"><div class="msgs"></div></div>`); main.appendChild(scroll);
  const foot = h(`<div class="chat-foot"></div>`); main.appendChild(foot);
  view = new ChatView(scroll.querySelector('.msgs'), { onTitle: () => setTimeout(async () => { await loadList(); paintHead(); }, 400) });
  comp = new Composer(foot, {
    placeholder: 'Напиши Renard… (Enter — отправить, Shift+Enter — новая строка)',
    onSubmit: ({ text, mode, perm, voice }) => {
      const empty = main.querySelector('.chat-empty'); if (empty) empty.remove();
      const ok = view.send(text, { mode, perm, voice });
      if (ok && current.id !== view.session) { current = { kind: 'chat', id: view.session }; history.replaceState(null, '', '#/chats/c/' + view.session); if (view.project) post('/api/chats/' + view.session, { project: view.project }); }
      return ok;
    },
    getProject: () => view.project,
    setProject: async (pid) => { view.project = pid; if (view.session) await post('/api/chats/' + view.session, { project: pid }); paintHead(); loadList(); },
  });
  main.querySelector('[data-a=pin]').onclick = async () => { const c = chats.find(x => x.id === view.session); await post('/api/chats/' + view.session, { pinned: !(c && c.pinned) }); loadList(); };
  main.querySelector('[data-a=rename]').onclick = async () => { const t = prompt('Название чата:', main.querySelector('.title').textContent); if (t) { await post('/api/chats/' + view.session, { title: t }); paintHead(t); loadList(); } };
  main.querySelector('[data-a=delete]').onclick = () => deleteChat(view.session);
}

async function deleteChat(sid) {
  if (!sid) return;
  let items = [];
  try { items = (await api('/api/chats/' + encodeURIComponent(sid) + '/memory')).items || []; } catch (e) {  }
  const clean = (l) => esc(l.replace(/^- /, '').replace(/\s*\(\d{4}-\d{2}-\d{2}\)\s*$/, ''));
  const m = h(`<div class="modal-bg"><div class="modal"><h2>Удалить чат?</h2>
    <p class="muted" style="margin:0 0 10px">Переписка исчезнет из истории.</p>
    <label class="chk" style="display:flex;gap:8px;align-items:center;color:inherit;font-size:14px">
      <input type="checkbox" id="dforget" ${items.length ? '' : 'disabled'}> Забыть и то, что Renard запомнил из этого чата
    </label>
    ${items.length ? `<div id="dlist" class="forget-list" style="display:none;margin:8px 0 0 26px;max-height:240px;overflow:auto">
      ${items.map((it, i) => `<label style="display:flex;gap:8px;align-items:flex-start;color:inherit;font-size:13px;margin:6px 0">
        <input type="checkbox" data-i="${i}" checked><span>${clean(it.line)} <span class="muted">· ${esc(it.note)}${it.how === 'match' ? ' · похоже' : ''}</span></span></label>`).join('')}
      <p class="muted" style="font-size:12px;margin:6px 0 0">Сними галочку с того, что нужно оставить в памяти.</p></div>`
      : '<p class="muted" style="font-size:12.5px;margin:6px 0 0 26px">Из этого чата в память ничего не попало.</p>'}
    <div class="actions"><button class="btn" id="dc">Отмена</button><button class="btn danger" id="dd">Удалить</button></div></div></div>`);
  document.body.appendChild(m);
  const box = m.querySelector('#dforget'), list = m.querySelector('#dlist');
  box.onchange = () => { if (list) list.style.display = box.checked ? '' : 'none'; };
  m.querySelector('#dc').onclick = () => m.remove();
  m.onclick = (e) => { if (e.target === m) m.remove(); };
  m.querySelector('#dd').onclick = async () => {
    let forgotten = 0;
    if (box.checked && list) {
      const pick = [...list.querySelectorAll('input[data-i]')].filter(x => x.checked).map(x => items[+x.dataset.i]);
      if (pick.length) forgotten = (await post('/api/chats/' + encodeURIComponent(sid) + '/forget', { items: pick })).forgotten || 0;
    }
    await del('/api/chats/' + encodeURIComponent(sid));
    m.remove();
    toast(forgotten ? `Чат удалён, забыто фактов: ${forgotten}` : 'Чат удалён');
    location.hash = '#/chats/new'; loadList();
  };
}
function paintHead(title) {
  const p = projects.find(x => x.id === view.project);
  main.querySelector('.crumb').innerHTML = p ? `<a href="#/chats/p/${p.id}">${esc(p.name)}</a> /` : '';
  const c = chats.find(x => x.id === view.session);
  main.querySelector('.title').textContent = title || (c && c.title) || 'Новый чат';
}
async function openChat(id) {
  current = { kind: 'chat', id };
  if (!view || !main.querySelector('.chat-scroll')) chatShell();
  if (view.session !== id || !view.root.children.length) await view.load(id);
  paintHead(); loadList(side.querySelector('.search input').value);
  setTimeout(() => comp.focus(), 50);
}
function newChat(project = '') {
  current = { kind: 'chat', id: null }; chatShell(); view.newSession(project);
  const p = projects.find(x => x.id === project);
  view.root.appendChild(h(`<div class="chat-empty"><img src="/assets/renard_icon.svg" alt=""><div class="greet">${p ? esc(p.name) : 'Чем займёмся' + (prefs.user_name ? ', ' + esc(prefs.user_name) : '') + '?'}</div>
    <div class="sub">${p ? esc((p.instructions || 'Проект').slice(0, 200)) : 'Файлы — 📎 или перетащи в поле ввода. Режим «Авто» — без лишних вопросов.'}</div></div>`));
  paintHead(); loadList(); setTimeout(() => comp.focus(), 50);
  if (pendingFirst) { const m = pendingFirst; pendingFirst = null; setTimeout(() => comp.onSubmit(m), 80); }
}

async function showProjects() {
  current = { kind: 'projects', id: null }; await loadList();
  main.innerHTML = '';
  const el = h(`<div class="page-pad"><div class="narrow" style="max-width:1000px">
    <div style="display:flex;align-items:center;gap:12px"><h1 style="flex:1">Проекты</h1><button class="btn primary" id="np">${ICON('plus')} Новый проект</button></div>
    <div class="sub" style="margin:-10px 0 16px">Проект = инструкции + папки и файлы, с которыми агент работает в каждом чате проекта.</div>
    <div class="grid3">${projects.map(p => `<div class="pcard" data-p="${p.id}"><b>${esc(p.name)}</b><small>${esc((p.instructions || '').slice(0, 110)) || 'без инструкций'}</small>
      <div class="dim" style="margin-top:8px">${p.folders.length} папок · ${p.chats} чатов</div></div>`).join('') || '<div class="sub">Пока нет проектов.</div>'}</div></div></div>`);
  main.appendChild(el);
  el.querySelector('#np').onclick = () => editProject({});
  el.querySelectorAll('[data-p]').forEach(c => c.onclick = () => location.hash = '#/chats/p/' + c.dataset.p);
}
async function showProject(id) {
  current = { kind: 'project', id }; await loadList();
  let p;
  try { p = await api('/api/projects/' + id); } catch (e) { return showProjects(); }
  const pc = chats.filter(c => c.project === id);
  const kb = (n) => n > 1048576 ? (n / 1048576).toFixed(1) + ' МБ' : Math.max(1, Math.round(n / 1024)) + ' КБ';
  main.innerHTML = '';
  const el = h(`<div class="page-pad"><div class="narrow">
    <div class="sub"><a href="#/chats/projects">Проекты</a> /</div>
    <div style="display:flex;align-items:center;gap:10px"><h1 style="flex:1">${esc(p.name)}</h1>
      <button class="btn" id="ed">${ICON('edit')} Изменить</button><button class="btn primary" id="nc">${ICON('plus')} Чат в проекте</button></div>
    <div id="quick"></div>
    <div class="card"><h3>Инструкции</h3><div class="md">${p.instructions ? esc(p.instructions).replace(/\n/g, '<br>') : '<span class="sub">нет — агент работает как обычно. Нажми «Изменить», чтобы задать роль, стек, стиль ответов.</span>'}</div></div>
    <div class="card"><h3>${ICON('box')} Знания проекта</h3>
      <div class="sub" style="margin-bottom:6px">Файлы, которые агент знает в каждом чате этого проекта: задания, конспекты, документация, код, таблицы.
        ${p.index.chunks ? `Сейчас в индексе ${plural(p.index.files, 'файл', 'файла', 'файлов')} (${p.index.chars >= 1000 ? Math.round(p.index.chars / 1000) + ' тыс.' : p.index.chars} символов).` : 'Пока пусто.'}</div>
      <div id="kn">${p.knowledge.map(k => `<div class="kn-row"><span class="nm">📄 ${esc(k.name)}</span><small>${kb(k.size)}</small>
        <button class="ic" data-rm="${esc(k.name)}" title="Убрать из проекта">${ICON('trash')}</button></div>`).join('') || ''}</div>
      <label class="kn-drop" id="kdrop">${ICON('upload')} Перетащи файлы сюда или нажми, чтобы выбрать<input type="file" multiple hidden id="kfile"></label></div>
    <div class="card"><h3>${ICON('folder')} Папки и файлы на диске</h3>
      ${p.folders.map(f => `<div class="kn-row"><span class="nm">📁 ${esc(f)}</span><button class="btn sm" data-open="${esc(f)}">открыть</button></div>`).join('')}
      ${p.files.map(f => `<div class="kn-row"><span class="nm">📄 ${esc(f)}</span></div>`).join('')}
      ${!p.folders.length && !p.files.length ? '<div class="sub">Привяжи папку проекта (кнопка «Изменить») — агент будет видеть её файлы, искать по ним и править код прямо в ней.</div>' : ''}
      ${p.folders.length ? `<div style="margin-top:8px"><button class="btn sm" id="reidx">${ICON('refresh')} Обновить индекс папок</button></div>` : ''}</div>
    <div class="card"><h3>${ICON('sparkle')} Память проекта</h3>
      <div class="sub" style="margin-bottom:6px">Что агент запомнил внутри этого проекта (решения, договорённости). Можно править.</div>
      <textarea class="txt" id="pmem" rows="5" placeholder="пока пусто">${esc(p.memory || '')}</textarea>
      <div style="margin-top:6px"><button class="btn sm" id="pmsave">Сохранить память</button></div></div>
    <div class="card"><h3>${ICON('chat')} Чаты проекта</h3>${pc.map(c => `<div class="row" style="cursor:pointer" data-c="${esc(c.id)}"><span class="lbl"><b>${esc(c.title)}</b><small>${c.when} · ${c.n} сообщ.</small></span>${ICON('chev')}</div>`).join('') || '<div class="sub">пока нет — начни с поля ниже</div>'}</div>
  </div></div>`);
  main.appendChild(el);
  const qc = new Composer(el.querySelector('#quick'), { placeholder: `Спроси что-нибудь в проекте «${p.name}»…`,
    onSubmit: ({ text, mode, perm, voice }) => { pendingFirst = { text, mode, perm, voice }; location.hash = '#/chats/new/' + id; return true; } });
  el.querySelector('#ed').onclick = () => editProject(p);
  el.querySelector('#nc').onclick = () => location.hash = '#/chats/new/' + id;
  el.querySelectorAll('[data-c]').forEach(c => c.onclick = () => location.hash = '#/chats/c/' + c.dataset.c);
  el.querySelectorAll('[data-open]').forEach(b => b.onclick = () => post('/api/open_folder', { path: b.dataset.open }).catch(e => toast(e.message, 'err')));
  el.querySelectorAll('[data-rm]').forEach(b => b.onclick = async () => { await del(`/api/projects/${id}/files/${encodeURIComponent(b.dataset.rm)}`); showProject(id); });
  const upload = async (files) => {
    for (const f of files) {
      toast('Добавляю в проект: ' + f.name);
      const r = await fetch(`/api/projects/${id}/files?name=${encodeURIComponent(f.name)}`, { method: 'POST', body: f });
      if (!r.ok) toast('Не удалось добавить ' + f.name, 'err');
    }
    showProject(id);
  };
  const drop = el.querySelector('#kdrop'), inp = el.querySelector('#kfile');
  inp.onchange = () => upload([...inp.files]);
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drop'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('drop'));
  drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('drop'); upload([...e.dataTransfer.files]); });
  const ri = el.querySelector('#reidx');
  if (ri) ri.onclick = async () => { ri.disabled = true; const r = await post(`/api/projects/${id}/reindex`, {}); toast(`В индексе ${r.files} файлов`); showProject(id); };
  el.querySelector('#pmsave').onclick = async () => { await post(`/api/projects/${id}/memory`, { memory: el.querySelector('#pmem').value }); toast('Память проекта сохранена'); };
}
function editProject(p) {
  const m = h(`<div class="modal-bg"><div class="modal"><h2>${p.id ? 'Проект' : 'Новый проект'}</h2>
    <label>Название</label><input class="txt" id="pn" value="${esc(p.name || '')}" placeholder="Например: Мой сайт">
    <label>Инструкции для агента</label><textarea class="txt" id="pi" rows="6" placeholder="Что это за проект, стек, правила, стиль ответов…">${esc(p.instructions || '')}</textarea>
    <label>Папки (по одной в строке)</label><textarea class="txt" id="pf" rows="3" placeholder="D:\\Projects\\site">${esc((p.folders || []).join('\n'))}</textarea>
    <label>Отдельные файлы (по одному в строке)</label><textarea class="txt" id="pfi" rows="2">${esc((p.files || []).join('\n'))}</textarea>
    <div class="actions">${p.id ? `<button class="btn danger" id="pd">Удалить проект</button><span class="grow"></span>` : ''}<button class="btn" id="pc">Отмена</button><button class="btn primary" id="ps">Сохранить</button></div></div></div>`);
  document.body.appendChild(m);
  const lines = (id) => m.querySelector(id).value.split('\n').map(s => s.trim()).filter(Boolean);
  m.querySelector('#pc').onclick = () => m.remove();
  m.querySelector('#ps').onclick = async () => {
    const r = await post('/api/projects', { id: p.id, name: m.querySelector('#pn').value || 'Проект', instructions: m.querySelector('#pi').value, folders: lines('#pf'), files: lines('#pfi'), pinned: true });
    m.remove(); toast('Проект сохранён'); location.hash = '#/chats/p/' + r.id; showProject(r.id);
  };
  const d = m.querySelector('#pd'); if (d) d.onclick = async () => { if (!confirm('Удалить проект? Чаты останутся.')) return; await del('/api/projects/' + p.id); m.remove(); location.hash = '#/chats/projects'; };
}

async function showTasks() {
  current = { kind: 'tasks', id: null };
  const [{ tasks }, { commands }] = await Promise.all([api('/api/tasks'), api('/api/commands')]);
  main.innerHTML = '';
  const el = h(`<div class="page-pad"><div class="narrow" style="max-width:980px">
    <div style="display:flex;align-items:center;gap:12px"><h1 style="flex:1">Запланированные задачи</h1><button class="btn primary" id="nt">${ICON('plus')} Новая задача</button></div>
    <div class="sub" style="margin:-10px 0 16px">Напоминания, регулярные запросы к ИИ (сводка погоды по утрам, проверка ПК) и запуск команд по расписанию. Можно и голосом: «напомни через 15 минут…».</div>
    <div class="tasktable">${tasks.map(t => `<div class="trow" data-t="${t.id}">
      <div class="tog ${t.enabled ? 'on' : ''}" data-tog></div>
      <div><b>${esc(t.name)}</b><small>${t.kind === 'reminder' ? '🔔 напоминание' : t.kind === 'command' ? '⚙ команда' : '✻ запрос к ИИ'}${t.prompt && t.kind !== 'reminder' ? ': ' + esc(t.prompt.slice(0, 60)) : ''}</small></div>
      <div>${esc(t.describe || '')}<small>${t.next_run ? 'след.: ' + new Date(t.next_run * 1000).toLocaleString('ru', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'}</small></div>
      <div><small>${t.last_run ? 'был: ' + new Date(t.last_run * 1000).toLocaleString('ru', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : 'ещё не запускалась'}</small><small title="${esc(t.last_result || '')}">${esc((t.last_result || '').slice(0, 50))}</small></div>
      <div style="display:flex;gap:4px"><button class="ic" data-run title="Запустить сейчас">${ICON('play')}</button><button class="ic" data-ed title="Изменить">${ICON('edit')}</button><button class="ic" data-del title="Удалить">${ICON('trash')}</button></div>
    </div>`).join('') || '<div class="sub">Задач нет.</div>'}</div></div></div>`);
  main.appendChild(el);
  el.querySelector('#nt').onclick = () => editTask({}, commands);
  el.querySelectorAll('[data-t]').forEach(r => {
    const t = tasks.find(x => x.id === r.dataset.t);
    r.querySelector('[data-tog]').onclick = async () => { await post('/api/tasks', { id: t.id, enabled: !t.enabled }); showTasks(); };
    r.querySelector('[data-run]').onclick = async () => { toast('Запускаю «' + t.name + '»…'); const x = await post(`/api/tasks/${t.id}/run`); toast((x.result || '').slice(0, 200)); showTasks(); };
    r.querySelector('[data-ed]').onclick = () => editTask(t, commands);
    r.querySelector('[data-del]').onclick = async () => { if (confirm('Удалить задачу?')) { await del('/api/tasks/' + t.id); showTasks(); } };
  });
}
function editTask(t, commands) {
  const m = h(`<div class="modal-bg"><div class="modal"><h2>${t.id ? 'Задача' : 'Новая задача'}</h2>
    <label>Тип</label><div class="seg2" id="tk">${[['reminder', '🔔 Напоминание'], ['agent', '✻ Запрос к ИИ'], ['command', '⚙ Команда']].map(([v, n]) => `<button data-v="${v}" class="${(t.kind || 'reminder') === v ? 'on' : ''}">${n}</button>`).join('')}</div>
    <label>Название</label><input class="txt" id="tn" value="${esc(t.name || '')}" placeholder="Например: Утренняя сводка">
    <div id="tpw"><label id="tpl">Текст</label><textarea class="txt" id="tp" rows="3">${esc(t.prompt || '')}</textarea></div>
    <div id="tcw" style="display:none"><label>Команда</label><select class="txt" id="tc">${commands.map(c => `<option value="${c.id}" ${t.command === c.id ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select></div>
    <label>Когда</label><input class="txt" id="tw" value="${esc(t.when || '')}" placeholder="daily 08:00 · weekdays 07:30 · in 15m · every 30m · 18:30 · once 2026-10-26 09:00">
    <div class="sub" style="margin-top:6px">${['in 15m', 'daily 08:00', 'weekdays 07:30', 'every 60m', 'weekly sat 10:00'].map(x => `<a class="ex" style="margin-right:10px;cursor:pointer">${x}</a>`).join('')}</div>
    <div class="row"><span class="lbl"><b>Произнести вслух</b><small>результат озвучивается голосом</small></span><div class="tog ${t.speak ? 'on' : ''}" id="tsp"></div></div>
    <div class="row"><span class="lbl"><b>Прислать в Telegram</b></span><div class="tog ${t.telegram !== false ? 'on' : ''}" id="ttg"></div></div>
    <div class="actions"><button class="btn" id="tx">Отмена</button><button class="btn primary" id="ts">Сохранить</button></div></div></div>`);
  document.body.appendChild(m);
  let kind = t.kind || 'reminder';
  const paint = () => { m.querySelector('#tpw').style.display = kind === 'command' ? 'none' : ''; m.querySelector('#tcw').style.display = kind === 'command' ? '' : 'none';
    m.querySelector('#tpl').textContent = kind === 'agent' ? 'Что сделать (запрос к Renard)' : 'Что напомнить'; };
  m.querySelectorAll('#tk button').forEach(b => b.onclick = () => { kind = b.dataset.v; m.querySelectorAll('#tk button').forEach(x => x.classList.toggle('on', x === b)); paint(); });
  paint();
  m.querySelectorAll('.ex').forEach(a => a.onclick = () => m.querySelector('#tw').value = a.textContent);
  m.querySelectorAll('.tog').forEach(x => x.onclick = () => x.classList.toggle('on'));
  m.querySelector('#tx').onclick = () => m.remove();
  m.querySelector('#ts').onclick = async () => {
    try {
      await post('/api/tasks', { id: t.id, kind, name: m.querySelector('#tn').value, prompt: m.querySelector('#tp').value, command: m.querySelector('#tc').value,
        when: m.querySelector('#tw').value || t.when, speak: m.querySelector('#tsp').classList.contains('on'), telegram: m.querySelector('#ttg').classList.contains('on'), enabled: true });
      m.remove(); showTasks();
    } catch (e) { toast(e.message, 'err'); }
  };
}

async function showFiles() {
  current = { kind: 'files', id: null };
  const s = await api('/api/settings');
  main.innerHTML = '';
  const el = h(`<div class="page-pad"><div class="narrow">
    <h1>Файлы и папки</h1>
    <div class="sub" style="margin:-10px 0 16px">Папки, с которыми агенту разрешено работать. Загрузки из чата лежат в workspace\\uploads.</div>
    <div class="card"><h3>${ICON('folder')} Разрешённые папки</h3>${s.folders.map(f => `<div class="row"><span class="lbl">📁 ${esc(f)}</span><button class="btn sm" data-open="${esc(f)}">открыть</button></div>`).join('')}
      <div class="row"><input class="txt" id="nf" placeholder="C:\\путь\\к\\папке"><button class="btn primary" id="af">Разрешить</button></div></div></div></div>`);
  main.appendChild(el);
  el.querySelector('#af').onclick = async () => { const r = await post('/api/settings', { folder: el.querySelector('#nf').value }); if (r.error) toast(r.error, 'err'); else { toast('Папка разрешена'); showFiles(); } };
  el.querySelectorAll('[data-open]').forEach(b => b.onclick = () => post('/api/open_folder', { path: b.dataset.open }).catch(e => toast(e.message, 'err')));
}
