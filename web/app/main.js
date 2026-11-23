import { api, post, on, emit, esc, h, ICON, $, $$, state, setOrb, loadPrefs, prefs, toast, connect, report } from './core.js';
import { startBackground } from './bg.js';

const TABS = [
  ['home', 'Главная', 'home'], ['chats', 'Чаты', 'chat'], ['commands', 'Команды', 'cmd'], ['model', 'Модель', 'model'],
  ['voice', 'Голос', 'mic'], ['ai', 'ИИ', 'ai'], ['plugins', 'Плагины', 'plug'], ['settings', 'Настройки', 'gear'],
];
const HIDDEN = ['chess'];
const pages = {};
let current = null;

let navSeq = 0;
async function show(name, params) {
  if (!TABS.find(t => t[0] === name) && !HIDDEN.includes(name)) name = 'home';
  const my = ++navSeq;
  $$('.tabs a').forEach(a => a.classList.toggle('on', a.dataset.p === name));
  let pg = pages[name];
  if (!pg) {
    const el = h(`<section class="page page-${name}"><div class="page-pad"><div class="sub">загружаю…</div></div></section>`);
    $('#pages').appendChild(el);
    pg = pages[name] = { el, mod: null, ready: null, failed: false };
    mountPage(name, pg, params);
  } else if (pg.failed) mountPage(name, pg, params);
  $$('.page').forEach(p => p.classList.toggle('on', p === pg.el));
  current = name;
  await pg.ready;
  if (my !== navSeq || !pg.mod) return;
  if (pg.mod.show) pg.mod.show(params);
}

function mountPage(name, pg, params, attempt = 0) {
  const el = pg.el; pg.failed = false;
  if (attempt) el.innerHTML = `<div class="page-pad"><div class="sub">загружаю… (попытка ${attempt + 1})</div></div>`;
  const limit = new Promise((_, rej) => setTimeout(() => rej(new Error('вкладка не ответила за 15 секунд')), 15000));
  const work = import(`./pages/${name}.js${attempt ? '?r=' + Date.now() : ''}`)
    .then(async (mod) => { el.innerHTML = ''; pg.mod = mod; await mod.mount(el, params); });
  pg.ready = Promise.race([work, limit]).catch((e) => {
    pg.failed = true; pg.mod = null;
    report('error', 'tab', `вкладка «${name}» не загрузилась (попытка ${attempt + 1}): ${e.message || e}`);
    if (fails || /fetch|network|Failed to fetch/i.test(String(e.message || e))) {
      el.innerHTML = `<div class="page-pad"><div class="card"><h3>Renard перезапускается…</h3>
        <div class="sub">Вкладка откроется сама, как только он снова будет на связи.</div></div></div>`;
      if (attempt < 3) setTimeout(() => { if (pg.failed && el.isConnected) { mountPage(name, pg, params, attempt + 1); pg.ready.then(() => current === name && show(name, params)); } }, 2000 * (attempt + 1));
      return;
    }
    el.innerHTML = `<div class="page-pad"><div class="card"><h3>Вкладка не загрузилась</h3>
      <div class="sub">${esc(e.message || String(e))}</div><div class="sub dim">Ошибка записана в журнал Renard.</div>
      <button class="btn primary" data-retry style="margin-top:10px">Повторить</button></div></div>`;
    el.querySelector('[data-retry]').onclick = () => { mountPage(name, pg, params, attempt + 1); pg.ready.then(() => current === name && show(name, params)); };
    if (attempt < 3) setTimeout(() => { if (pg.failed && el.isConnected) { mountPage(name, pg, params, attempt + 1); pg.ready.then(() => current === name && show(name, params)); } }, 2000 * (attempt + 1));
  });
}
function retryFailedPages() {
  for (const [name, pg] of Object.entries(pages)) if (pg.failed) { mountPage(name, pg, []); if (name === current) pg.ready.then(() => show(name, [])); }
}
function route() {
  const parts = (location.hash || '#/home').replace(/^#\/?/, '').split('/');
  show(parts[0] || 'home', parts.slice(1));
}
window.renardMic = () => {
  const page = pages[current]; const b = page && page.el.querySelector('.micb');
  if (b) b.click(); else { location.hash = '#/home'; setTimeout(() => window.renardMic(), 400); }
};

let bgNote = '', fgNote = '';
function paintActivity() {
  const a = $('#activity'), txt = fgNote || bgNote;
  a.innerHTML = txt ? `<span class="pulse"></span>${esc(txt)}` : '';
  a.classList.toggle('bg', !fgNote && !!bgNote);
}
on('note', (t) => { fgNote = t || ''; paintActivity(); });
on('open_page', (ev) => { if (ev && ev.page) location.hash = '#/' + ev.page; });
on('activity', (ev) => {
  if (ev.note !== undefined) bgNote = ev.note;
  if (ev.source === 'telegram') bgNote = ev.state === 'idle' ? '' : (ev.state === 'thinking' ? 'Telegram: отвечаю…' : bgNote);
  if (ev.source === 'wake') {
    bgNote = { listening: 'слушаю тебя…', thinking: 'думаю над голосовой командой…', speaking: 'отвечаю голосом…', idle: '' }[ev.state] ?? bgNote;
    if (ev.state) setOrb(ev.state);
    if (ev.level != null) state.level = Math.max(state.level, ev.level);
  }
  if (ev.source === 'telegram' && ev.state && !state.busy) setOrb(ev.state === 'idle' ? 'idle' : ev.state);
  paintActivity(); emit('external', ev);
});
on('alert', (ev) => toast('⚠ ' + ev.text, 'warn'));
on('task', (ev) => toast(`⏰ ${ev.name}: ${ev.text.slice(0, 160)}`));
on('memory', (ev) => toast('🧠 ' + ev.saved.join(' · ')));

let fails = 0, downSince = 0, conflictShown = false;
async function refresh() {
  try {
    const s = await api('/api/status', { headers: { 'X-Renard-UI': 'main' }, timeout: 10000 }); state.status = s;
    if (fails) {
      if (fails > 2) { report('info', 'net', `связь с сервером восстановлена через ${Math.round((Date.now() - downSince) / 1000)} с`); toast('Связь с Renard восстановлена'); }
      fails = 0; downSince = 0; retryFailedPages();
    }
    if ((s.conflicts || []).length && !conflictShown) {
      conflictShown = true;
      s.conflicts.forEach(c => toast('⚠ ' + c.text, 'warn'));
    }
    const g = s.gpu || {};
    state.load = { cpu: s.cpu_pct ?? 0, gpu: g['load_%'] ?? 0 };
    const model = s.loaded.length ? s.loaded.map(m => m.name.split(':')[0]).join(', ') : 'выгружена';
    const tg = s.telegram || {};
    $('#pills').innerHTML =
      `<span class="pill ${s.loaded.length ? 'on' : ''}" title="Модель в видеопамяти">${ICON('sparkle', 'sm')} AI <b>${esc(model)}</b></span>` +
      `<span class="pill ${s.stt_loaded ? 'on' : ''}" title="Распознавание речи">${ICON('mic', 'sm')} STT</span>` +
      `<span class="pill ${s.voice ? 'on' : ''}" title="Синтез речи">${ICON('wave', 'sm')} TTS</span>` +
      (s.wake_available ? `<span class="pill click ${s.wake ? 'on' : ''}" id="wakePill" title="Слово «Ренар»">👂 ${s.wake ? 'Ренар' : 'не слушаю'}</span>` : '') +
      (tg.configured ? `<span class="pill ${tg.connected ? 'on' : ''}" title="${tg.pair_code ? 'Отправь боту /pair ' + tg.pair_code : 'Telegram'}">${ICON('tg', 'sm')} ${tg.pair_code ? 'код ' + tg.pair_code : '@' + esc(tg.bot || '')}</span>` : '');
    const wp = $('#wakePill'); if (wp) wp.onclick = () => post('/api/wake/toggle').then(refresh);
    $('#ram').textContent = `${s.agent_ram_mb} МБ`;
    if (!state.busy && !s.loaded.length && !s.stt_loaded && state.orb === 'idle') setOrb('sleep');
    if (!state.busy && (s.loaded.length || s.stt_loaded) && state.orb === 'sleep') setOrb('idle');
    emit('status', s);
  } catch (e) {
    if (!fails++) downSince = Date.now();
    if (fails === 3) report('warn', 'net', `нет ответа от сервера: ${e.message}`);
    $('#pills').innerHTML = `<span class="pill err" title="${esc(e.message)}">нет связи с Renard${fails > 2 ? ' — переподключаюсь…' : ''}</span>`;
  }
}
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') refresh(); });
on('foreign', (host) => toast(`🛡 Заблокировал чужой скрипт (${host}) — его пытается встроить программа на ПК. Подробнее: Настройки → Диагностика`, 'warn'));

async function boot() {
  await loadPrefs();
  document.body.appendChild(h(`<canvas id="bg"></canvas>`));
  const app = h(`<div id="app">
    <header class="top">
      <a class="brand" href="#/home"><img src="/assets/renard_icon.svg" alt=""><span>Renard</span></a>
      <nav class="tabs">${TABS.map(([p, t, i]) => `<a href="#/${p}" data-p="${p}" title="${t}">${ICON(i)}<span>${t}</span></a>`).join('')}</nav>
      <div class="top-right"><button class="ic" id="wBtn" title="Виджеты">${ICON('grid')}</button></div>
    </header>
    <main id="pages"></main>
    <footer class="status">
      <span class="who">${ICON('user', 'sm')} <span id="who"></span></span>
      <div id="pills" class="pills"></div>
      <span id="activity"></span>
      <span class="grow"></span>
      <span class="dim" id="ram"></span>
      <button class="btn sm ghost" id="unload" title="Выгрузить модели из видеопамяти">${ICON('eject', 'sm')} VRAM</button>
    </footer>
  </div>`);
  document.body.appendChild(app);
  $('#who').textContent = prefs.user_name || 'гость';
  on('prefs', p => { $('#who').textContent = p.user_name || 'гость'; });
  $('#unload').onclick = async () => { await post('/api/unload'); toast('Модели выгружены из видеопамяти'); refresh(); };
  $('#wBtn').onclick = () => { location.hash = '#/home'; emit('toggle-widgets'); };
  startBackground($('#bg'));
  connect();
  addEventListener('hashchange', route); route();
  refresh(); setInterval(refresh, 3000);
}
boot();
