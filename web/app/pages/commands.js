import { api, post, del, esc, h, ICON, toast, debounce, on } from '../core.js';

let root, list, editor = null, NODES = {}, cmds = [], cur = null, q = '';

function loadDrawflow() {
  if (window.Drawflow) return Promise.resolve();
  return new Promise((res, rej) => { const s = document.createElement('script'); s.src = '/vendor/drawflow.min.js'; s.onload = res; s.onerror = rej; document.head.appendChild(s); });
}
function nodeHtml(name) {
  const m = NODES[name] || { title: name, icon: '?', fields: [] };
  return `<div class="nd"><div class="nt"><i>${m.icon}</i>${esc(m.title)}</div>
    ${m.fields.map(([k, label, ph]) => `<label>${esc(label)}</label><input df-${k} placeholder="${esc(ph)}">`).join('')}
    ${m.outs ? `<div class="outs">${m.outs.map(o => `<span>${o}</span>`).join('')}</div>` : ''}</div>`;
}

export async function mount(el) {
  root = el;
  el.appendChild(h(`<div class="glass cmd-list">
      <div class="head"><b>Команды</b>
        <button class="ic" id="cImp" title="Импорт JSON">${ICON('download')}</button>
        <button class="ic" id="cExp" title="Экспорт JSON">${ICON('upload')}</button>
        <button class="ic primary" id="cAdd" title="Новая команда">${ICON('plus')}</button></div>
      <button class="btn gal-btn" id="cGal" title="Галерея готовых автоматизаций">✨ Галерея</button>
      <input class="txt" id="cQ" placeholder="Поиск…">
      <div class="groups"></div>
      <input type="file" id="cFile" accept=".json" hidden>
    </div>
    <div class="glass cmd-edit">
      <div class="head"><input class="txt" id="cName" style="font-size:17px;font-weight:650"><input class="txt" id="cGroup" style="width:180px" placeholder="группа">
        <button class="btn ok" id="cRun">${ICON('play')} Запустить</button><button class="btn danger" id="cDel" title="Удалить">${ICON('trash')}</button></div>
      <div class="tools"><button class="btn" id="cNodes">${ICON('plus')} Узлы</button><button class="btn" id="cLayout">${ICON('grid')} Авто-раскладка</button>
        <span class="grow"></span><span class="sub" id="cSaved"></span><button class="btn" id="cFull">${ICON('expand')} Развернуть</button></div>
      <div id="drawflow"></div>
      <div class="runlog" id="cLog"></div>
    </div>`));
  list = el.querySelector('.groups');
  await loadDrawflow();
  const r = await api('/api/commands'); NODES = r.nodes; cmds = r.commands;
  editor = new window.Drawflow(el.querySelector('#drawflow'));
  editor.reroute = true; editor.zoom_min = .4; editor.start();
  const save = debounce(saveCurrent, 600);
  ['nodeCreated', 'nodeRemoved', 'connectionCreated', 'connectionRemoved', 'nodeMoved', 'nodeDataChanged'].forEach(ev => editor.on(ev, () => { if (!loading) save(); }));
  el.querySelector('#drawflow').addEventListener('input', () => save());
  el.querySelector('#cName').oninput = el.querySelector('#cGroup').oninput = save;
  el.querySelector('#cQ').oninput = (e) => { q = e.target.value.toLowerCase(); paintList(); };
  el.querySelector('#cAdd').onclick = () => newCommand();
  el.querySelector('#cGal').onclick = gallery;
  el.querySelector('#cRun').onclick = runCurrent;
  el.querySelector('#cDel').onclick = async () => { if (!cur || !confirm(`Удалить команду «${cur.name}»?`)) return; await del('/api/commands/' + cur.id); cmds = cmds.filter(c => c.id !== cur.id); cur = null; paintList(); if (cmds[0]) open(cmds[0].id); };
  el.querySelector('#cNodes').onclick = (e) => palette(e.currentTarget);
  el.querySelector('#cLayout').onclick = autoLayout;
  el.querySelector('#cFull').onclick = () => el.querySelector('.cmd-edit').classList.toggle('full');
  el.querySelector('#cExp').onclick = () => { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(cmds, null, 1)], { type: 'application/json' })); a.download = 'renard-commands.json'; a.click(); };
  el.querySelector('#cImp').onclick = () => el.querySelector('#cFile').click();
  el.querySelector('#cFile').onchange = async (e) => {
    try { const arr = JSON.parse(await e.target.files[0].text()); for (const c of [].concat(arr)) { delete c.id; await post('/api/commands', c); }
      cmds = (await api('/api/commands')).commands; paintList(); toast('Импортировано'); } catch (err) { toast('Не удалось импортировать: ' + err.message, 'err'); }
  };
  on('commands_changed', async () => { cmds = (await api('/api/commands')).commands; paintList(); });
  paintList();
  if (cmds[0]) open(cmds[0].id);
}
export function show(params = []) {
  if (params[0] === 'new') { newCommand(); return; }
  if (cur) setTimeout(() => open(cur.id), 30);
}

function paintList() {
  const groups = {};
  cmds.filter(c => !q || c.name.toLowerCase().includes(q)).forEach(c => (groups[c.group || 'Без группы'] ||= []).push(c));
  list.innerHTML = Object.entries(groups).map(([g, items]) => `<div class="grp"><span>${esc(g)}</span><span>${items.length}</span></div>` +
    items.map(c => { const nodes = Object.values(c.graph?.drawflow?.Home?.data || {}); const tr = nodes.filter(n => NODES[n.name]?.group === 'trigger').length;
      return `<div class="cmd-item ${cur && cur.id === c.id ? 'on' : ''} ${c.enabled === false ? 'off' : ''}" data-id="${c.id}"><div class="tt"><b>${esc(c.name)}</b><small>${tr} тригг. / ${nodes.length - tr} действ.</small></div><div class="tog ${c.enabled !== false ? 'on' : ''}" data-tog></div></div>`; }).join('')).join('')
    || '<div class="sub" style="padding:10px">Нет команд</div>';
  list.querySelectorAll('.cmd-item').forEach(it => {
    it.onclick = (e) => { if (!e.target.closest('[data-tog]')) open(it.dataset.id); };
    it.querySelector('[data-tog]').onclick = async () => { const c = cmds.find(x => x.id === it.dataset.id); c.enabled = c.enabled === false; await post('/api/commands', { id: c.id, enabled: c.enabled }); paintList(); };
  });
}
let loading = false;
function open(id) {
  cur = cmds.find(c => c.id === id); if (!cur) return;
  loading = true;
  root.querySelector('#cName').value = cur.name; root.querySelector('#cGroup').value = cur.group || '';
  const g = JSON.parse(JSON.stringify(cur.graph || { drawflow: { Home: { data: {} } } }));
  for (const n of Object.values(g.drawflow.Home.data)) {
    n.html = nodeHtml(n.name); n.class = (NODES[n.name] || {}).group || 'action'; n.typenode = false;
  }
  editor.clear(); editor.import(g);
  root.querySelector('#cLog').textContent = ''; root.querySelector('#cSaved').textContent = '';
  setTimeout(() => { loading = false; }, 50);
  paintList();
}
async function newCommand() {
  const c = await post('/api/commands', { name: 'Новая команда', group: 'Без группы' });
  cmds.push(c); open(c.id);
  addNode('trigger_phrase', 80, 140); addNode('notify', 400, 160);
  editor.addConnection(1, 2, 'output_1', 'input_1');
  root.querySelector('#cName').focus(); root.querySelector('#cName').select();
}
function addNode(name, x, y) {
  const m = NODES[name];
  const data = Object.fromEntries(m.fields.map(([k, , ph]) => [k, ph]));
  return editor.addNode(name, m.in, m.out, x, y, m.group, data, nodeHtml(name));
}
function palette(anchor) {
  document.querySelectorAll('.popmenu').forEach(m => m.remove());
  const groups = { trigger: 'Триггеры', action: 'Действия', logic: 'Логика' };
  const m = h(`<div class="popmenu" style="min-width:420px">${Object.entries(groups).map(([g, t]) => `<div class="sub" style="padding:6px 10px">${t}</div><div class="palette">` +
    Object.entries(NODES).filter(([, n]) => n.group === g).map(([k, n]) => `<div class="mi" data-n="${k}"><span>${n.icon}</span><div>${esc(n.title)}</div></div>`).join('') + '</div>').join('')}</div>`);
  document.body.appendChild(m); const r = anchor.getBoundingClientRect(); m.style.left = r.left + 'px'; m.style.top = (r.bottom + 6) + 'px';
  m.querySelectorAll('[data-n]').forEach(x => x.onclick = () => {
    m.remove(); const z = editor.zoom || 1, box = root.querySelector('#drawflow').getBoundingClientRect();
    addNode(x.dataset.n, (box.width / 2 - editor.canvas_x) / z - 115, (box.height / 2 - editor.canvas_y) / z - 50);
  });
  setTimeout(() => document.addEventListener('click', (e) => { if (!m.contains(e.target)) m.remove(); }, { once: true }), 0);
}
function autoLayout() {
  const data = editor.export().drawflow.Home.data, level = {}, order = {};
  const roots = Object.values(data).filter(n => !Object.values(n.inputs).some(i => i.connections.length));
  const queue = roots.map(n => [String(n.id), 0]);
  while (queue.length) {
    const [id, l] = queue.shift(); if (level[id] !== undefined && level[id] >= l) continue; level[id] = l;
    Object.values(data[id].outputs).forEach(o => o.connections.forEach(c => queue.push([String(c.node), l + 1])));
  }
  Object.keys(data).forEach(id => { const l = level[id] ?? 0; order[l] = (order[l] || 0) + 1;
    const n = data[id], x = 60 + l * 290, y = 60 + (order[l] - 1) * 190;
    editor.drawflow.drawflow.Home.data[id].pos_x = x; editor.drawflow.drawflow.Home.data[id].pos_y = y;
    const el = document.getElementById('node-' + id); if (el) { el.style.left = x + 'px'; el.style.top = y + 'px'; editor.updateConnectionNodes('node-' + id); } });
  saveCurrent();
}
async function saveCurrent() {
  if (!cur) return;
  cur.name = root.querySelector('#cName').value || 'Команда'; cur.group = root.querySelector('#cGroup').value || 'Без группы';
  cur.graph = editor.export();
  for (const n of Object.values(cur.graph.drawflow.Home.data)) n.html = n.name;
  const r = await post('/api/commands', { id: cur.id, name: cur.name, group: cur.group, graph: cur.graph });
  root.querySelector('#cSaved').textContent = (r.schedule_errors || []).length ? '⚠ ' + r.schedule_errors[0]
    : 'сохранено ' + new Date().toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  paintList();
}
async function gallery() {
  document.querySelectorAll('.gal-modal').forEach(m => m.remove());
  const { templates } = await api('/api/commands/gallery');
  const m = h(`<div class="gal-modal"><div class="glass gal-box">
    <div class="head"><b>Галерея автоматизаций</b><span class="sub">одним кликом — потом можно поменять в редакторе</span><span class="grow"></span><button class="ic" data-x>✕</button></div>
    <div class="gal-grid">${templates.map(t => `<div class="gal-card">
      <div class="gal-t"><i>${t.icon}</i><b>${esc(t.title)}</b></div><div class="sub">${esc(t.desc)}</div>
      <div class="gal-flow">${t.blocks.map(esc).join(' → ')}</div>
      <button class="btn ${t.added ? '' : 'ok'}" data-add="${t.id}">${t.added ? 'Добавить ещё раз' : 'Добавить'}</button></div>`).join('')}</div></div></div>`);
  document.body.appendChild(m);
  m.onclick = (e) => { if (e.target === m || e.target.closest('[data-x]')) m.remove(); };
  m.querySelectorAll('[data-add]').forEach(b => b.onclick = async () => {
    try { const c = await post('/api/commands/gallery/' + b.dataset.add); cmds = (await api('/api/commands')).commands;
      m.remove(); open(c.id); toast(`Добавлено: «${c.name}»` + (c.enabled === false ? ' — впиши свои данные и включи' : ''));
    } catch (err) { toast('Не получилось: ' + err.message, 'err'); }
  });
}
async function runCurrent() {
  if (!cur) return; await saveCurrent();
  const logEl = root.querySelector('#cLog'); logEl.textContent = '▶ выполняю…';
  const r = await post(`/api/commands/${cur.id}/run`);
  logEl.textContent = (r.log || []).map(x => '• ' + x).join('\n') || 'готово';
}
