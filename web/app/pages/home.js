import { api, post, on, esc, h, ICON, $, state, prefs, savePrefs, uid, debounce } from '../core.js';
import { Orb, ORB_LABELS } from '../orb.js';
import { Composer } from '../composer.js';
import { ChatView } from '../chatview.js';
import { renderAvatar, companionCfg, applyAvatarEvent } from '../avatar.js';
on('avatar', (ev) => applyAvatarEvent(avatarView, ev));

let view, comp, root;
const WICON = (c) => c === 0 || c === 1 ? 'sun' : (c >= 51 && c <= 82) || c >= 95 ? 'rain' : 'cloud';

function greeting() {
  const hr = new Date().getHours(), n = prefs.user_name ? ', ' + prefs.user_name : '';
  return hr < 5 ? `Не спится${n}?` : hr < 12 ? `Доброе утро${n}!` : hr < 18 ? `Что затеем${n}?` : `Добрый вечер${n}!`;
}

export async function mount(el) {
  root = el;
  el.appendChild(h(`<div class="home-main">
      <canvas class="home-orb"></canvas>
      <img class="sleep-fox" src="/assets/renard_sleep.svg" alt="">
      <div class="home-center">
        <div class="glass home-answer"><span class="open">открыть в чатах →</span><div class="msgs"></div></div>
        <div class="orb-state">…</div>
        <div class="greet"></div>
        <div class="cbox" style="width:100%"></div>
        <div class="suggest"><a data-s="last">→ Последний чат</a><a data-s="weather">Какая погода?</a><a data-s="cmd">Создай команду</a><a data-s="pc">Что грузит ПК?</a></div>
      </div>
      <img class="corner-fox" src="/assets/renard_corner.svg" alt="" title="Renard">
    </div>
    <aside class="widgets"></aside>`));
  new Orb(el.querySelector('.home-orb'));
  const ans = el.querySelector('.home-answer');
  view = new ChatView(ans.querySelector('.msgs'), { compact: true });
  ans.querySelector('.open').onclick = () => { location.hash = '#/chats/c/' + view.session; };
  comp = new Composer(el.querySelector('.cbox'), {
    compact: true, placeholder: 'Спроси о чём угодно…',
    onSubmit: ({ text, mode, perm, voice }) => {
      if (!view.session) view.newSession();
      ans.querySelector('.msgs').innerHTML = ''; ans.classList.add('on');
      return view.send(text, { mode, perm, voice });
    },
  });
  on('confirm-answer', (a) => { if (location.hash.startsWith('#/home') || !location.hash) view.send(a, { perm: (prefs.chat || {}).permission }); });
  el.querySelector('.greet').textContent = greeting();
  el.querySelectorAll('.suggest a').forEach(a => a.onclick = async () => {
    const s = a.dataset.s;
    if (s === 'last') { const r = await api('/api/chats'); location.hash = r.chats.length ? '#/chats/c/' + r.chats[0].id : '#/chats'; }
    if (s === 'weather') comp.setText('Какая погода на завтра?'), comp.submit();
    if (s === 'cmd') location.hash = '#/commands/new';
    if (s === 'pc') comp.setText('Что сейчас грузит компьютер?'), comp.submit();
  });
  el.querySelector('.corner-fox').onclick = () => { location.hash = '#/model'; };
  on('orb', paintOrbState); paintOrbState(state.orb);
  let wkey = '';
  on('prefs', () => {
    el.querySelector('.greet').textContent = greeting(); applyLook();
    const k = JSON.stringify((prefs.widgets || {}).items) + (prefs.home_city || '');
    if (k !== wkey) { wkey = k; paintWidgets(); }
  });
  wkey = JSON.stringify((prefs.widgets || {}).items) + (prefs.home_city || '');
  on('toggle-widgets', () => { const w = el.querySelector('.widgets'); w.classList.toggle('hidden'); savePrefs({ widgets: { show: !w.classList.contains('hidden') } }); });
  applyLook();
  paintWidgets();
}
let avatarKey = '', avatarView = null;
function applyLook() {
  const c = companionCfg(), custom = c.enabled && c.kind !== 'fox2d' && c.file && c.on_home !== false;
  root.querySelector('.corner-fox').style.display = (prefs.ui || {}).corner_fox === false || custom ? 'none' : '';
  const key = custom ? c.kind + ':' + c.file : '';
  if (key !== avatarKey) {
    avatarKey = key; const old = root.querySelector('.corner-avatar'); if (old) old.remove();
    if (avatarView) { avatarView.stop(); avatarView = null; }
    if (key) {
      const box = h(`<div class="corner-avatar"></div>`);
      root.querySelector('.home-main').appendChild(box);
      avatarView = renderAvatar(box, { cfg: c });
    }
  }
  root.querySelector('.home-main').classList.toggle('has-avatar', !!key);
  root.querySelector('.widgets').classList.toggle('hidden', (prefs.widgets || {}).show === false);
}
function paintOrbState(s) {
  const l = root.querySelector('.orb-state'); l.textContent = ORB_LABELS[s] || s;
  l.className = 'orb-state ' + (s === 'sleep' ? 'sleep' : s !== 'idle' ? 'active' : '');
  root.querySelector('.sleep-fox').classList.toggle('on', s === 'sleep');
}
export function show() { setTimeout(() => comp && comp.focus(), 50); }

const W = {
  today: () => `<div class="wcard" data-w="today"><div class="wh">${ICON('check')} Сегодня<span class="grow"></span><span class="dim" id="w-today-date"></span></div>
    <div id="w-today" class="todaylist"></div>
    <form class="today-add" id="w-today-add"><input placeholder="Добавить дело… («купить хлеб завтра в 18:00»)" maxlength="200"><button class="ic" title="Добавить">${ICON('plus')}</button></form></div>`,
  system: () => `<div class="wcard" data-w="system"><div class="wh">${ICON('cpu')} Система</div>
    ${['cpu|ЦП', 'ram|ОЗУ', 'gpu|Видеокарта', 'vram|VRAM', 'temp|GPU темп.'].map(x => { const [k, t] = x.split('|');
      return `<div class="meterrow">${ICON(k === 'temp' ? 'temp' : 'cpu', 'sm')}<span>${t}</span><span class="v" id="w-${k}">–</span><i class="mbar"><u id="wb-${k}"></u></i></div>`; }).join('')}</div>`,
  weather: () => `<div class="wcard" data-w="weather"><div class="wh">${ICON('sun')} Погода<span class="grow"></span><span class="dim" id="w-city"></span></div><div id="w-weather" class="sub">загружаю…</div></div>`,
  media: () => `<div class="wcard" data-w="media"><div class="wh">${ICON('wave')} Сейчас играет</div><div id="w-media" class="sub">ничего не играет</div></div>`,
  calendar: () => `<div class="wcard" data-w="calendar"><div class="wh">${ICON('cal')} <span id="w-month"></span></div><div class="cal" id="w-cal"></div></div>`,
  tasks: () => `<div class="wcard" data-w="tasks"><div class="wh">${ICON('clock')} Задачи и напоминания<span class="grow"></span><a href="#/chats/tasks" class="dim">все</a></div><div class="tasklist" id="w-tasks"></div></div>`,
  activity: () => `<div class="wcard" data-w="activity"><div class="wh">${ICON('clock')} Сегодня за компьютером<span class="grow"></span><span class="dim" id="w-act-total"></span></div><div id="w-act" class="sub">журнал собирается…</div></div>`,
  notes: () => `<div class="wcard" data-w="notes"><div class="wh">${ICON('note')} Заметки</div><textarea class="wnotes" placeholder="Быстрые заметки…"></textarea></div>`,
};
let timers = [], sysBound = false;
function paintWidgets() {
  const box = root.querySelector('.widgets'); timers.forEach(clearInterval); timers = [];
  let items = (prefs.widgets || {}).items || Object.keys(W);
  if (!items.includes('today') && !(prefs.widgets || {}).today_seen) {
    items = ['today', ...items]; savePrefs({ widgets: { ...(prefs.widgets || {}), items, today_seen: true } });
  }
  box.innerHTML = items.filter(k => W[k]).map(k => W[k]()).join('');
  if (items.includes('today')) { todayW(); timers.push(setInterval(todayW, 60000)); }
  if (items.includes('system')) { if (!sysBound) { on('status', sysW); sysBound = true; } if (state.status) sysW(state.status); }
  if (items.includes('weather')) { weatherW(); timers.push(setInterval(weatherW, 20 * 60000)); }
  if (items.includes('media')) { mediaW(); timers.push(setInterval(mediaW, 2500)); }
  if (items.includes('calendar') || items.includes('tasks')) { tasksW(); timers.push(setInterval(tasksW, 60000)); }
  if (items.includes('activity')) { activityW(); timers.push(setInterval(activityW, 60000)); }
  const n = box.querySelector('.wnotes');
  if (n) { n.value = prefs.notes || ''; n.oninput = debounce(() => savePrefs({ notes: n.value }), 700); }
}
function setBar(k, pct, txt) { const b = document.getElementById('wb-' + k), t = document.getElementById('w-' + k); if (b) b.style.width = Math.min(100, pct || 0) + '%'; if (t) t.textContent = txt; }
function sysW(s) {
  const g = s.gpu || {};
  setBar('cpu', s.cpu_pct, Math.round(s.cpu_pct) + '%');
  setBar('ram', s.ram_pct, `${Math.round(s.ram_pct)}% (${s.ram_used_gb} ГБ)`);
  setBar('gpu', g['load_%'], (g['load_%'] ?? '–') + '%');
  setBar('vram', g.vram_used_gb / g.vram_total_gb * 100, `${g.vram_used_gb}/${g.vram_total_gb} ГБ`);
  setBar('temp', g.temp_c, g.temp_c != null ? g.temp_c + '°C' : '–');
}
async function weatherW() {
  const el = document.getElementById('w-weather'); if (!el) return;
  try {
    const w = await api('/api/widgets/weather');
    if (w.error) { el.textContent = w.error; return; }
    document.getElementById('w-city').textContent = w.city;
    el.innerHTML = `<div class="weather-now">${ICON(WICON(w.code))}<span class="t">${Math.round(w.temp)}°</span><div><b>${esc(w.text)}</b><br><small class="sub">ощущается ${Math.round(w.feels)}° · ветер ${Math.round(w.wind)} м/с</small></div></div>
      <div class="weather-days">${w.days.map(d => `<div>${esc(d.label)}<b>${Math.round(d.min)}…${Math.round(d.max)}°</b>${d.rain_pct ?? 0}% ☂</div>`).join('')}</div>`;
  } catch (e) { el.textContent = 'нет данных'; }
}
async function activityW() {
  const el = document.getElementById('w-act'); if (!el) return;
  const r = await api('/api/widgets/activity').catch(() => ({ apps: [] }));
  const apps = (r.apps || []).filter(a => a.app !== 'Renard'), max = Math.max(1, ...apps.map(a => a.sec));
  const fmt = (s) => s >= 3600 ? `${Math.floor(s / 3600)} ч ${Math.floor(s % 3600 / 60)} м` : `${Math.max(1, Math.round(s / 60))} мин`;
  document.getElementById('w-act-total').textContent = r.total ? fmt(r.total) : '';
  el.innerHTML = apps.length ? apps.map(a => `<div class="meterrow noicon"><span class="nm" title="${esc(a.app)}">${esc(a.app)}</span><span class="v">${fmt(a.sec)}</span><i class="mbar"><u style="width:${a.sec / max * 100}%"></u></i></div>`).join('')
    : '<span class="sub">пока пусто — журнал ведётся, пока Renard запущен</span>';
}
async function mediaW() {
  const el = document.getElementById('w-media'); if (!el || !el.offsetParent) return;
  const m = await api('/api/widgets/media').catch(() => ({}));
  if (!m.title) { el.innerHTML = '<span class="sub">ничего не играет</span>'; return; }
  const app = (m.app || '').split(/[!.]/)[0];
  el.innerHTML = `<div class="media">${m.thumb ? `<img src="${m.thumb}">` : `<div class="noart">${ICON('wave')}</div>`}<div class="tt"><b>${esc(m.title)}</b><small>${esc(m.artist)}</small><small class="dim">${esc(app)}</small></div></div>
    <div class="media-ctl"><button class="ic" data-a="prev">${ICON('prev')}</button><button class="ic big" data-a="play_pause">${ICON(m.playing ? 'pause' : 'play')}</button><button class="ic" data-a="next">${ICON('next')}</button></div>`;
  el.querySelectorAll('[data-a]').forEach(b => b.onclick = async () => { await post('/api/widgets/media/' + b.dataset.a); setTimeout(mediaW, 300); });
}
async function todayW() {
  const el = document.getElementById('w-today'); if (!el) return;
  const r = await api('/api/planner').catch(() => null);
  if (!r) { el.innerHTML = '<span class="sub">планировщик недоступен</span>'; return; }
  const now = new Date(), today = now.toDateString();
  document.getElementById('w-today-date').textContent = now.toLocaleDateString('ru', { weekday: 'short', day: 'numeric', month: 'short' });
  const evs = r.events.filter(e => new Date(e.start).toDateString() === today);
  const when = (t) => { if (!t.due) return ''; const d = new Date(t.due), late = d < now && d.toDateString() !== today;
    return `<small class="${late ? 'late' : ''}">${d.toDateString() === today ? (t.due_time ? d.toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' }) : 'сегодня')
      : (d.toDateString() === new Date(Date.now() + 864e5).toDateString() ? 'завтра' : d.toLocaleDateString('ru', { day: 'numeric', month: 'short' })) + (t.due_time ? ' ' + d.toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' }) : '')}</small>`; };
  el.innerHTML = evs.map(e => `<div class="ev">${ICON('cal', 'sm')}<span>${esc(e.title)}</span><small>${e.all_day ? 'весь день' : new Date(e.start).toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' })}</small></div>`).join('')
    + r.tasks.slice(0, 8).map(t => `<label class="td"><input type="checkbox" data-id="${t.id}"><span>${esc(t.text)}</span>${when(t)}<button class="x" data-del="${t.id}" title="Удалить">${ICON('x', 'sm')}</button></label>`).join('')
    + (r.tasks.length > 8 ? `<div class="sub">ещё ${r.tasks.length - 8}…</div>` : '')
    + (!evs.length && !r.tasks.length ? '<div class="sub">Дел нет. Напиши ниже или скажи: «добавь в дела …»</div>' : '');
  el.querySelectorAll('input[data-id]').forEach(c => c.onchange = async () => {
    c.closest('.td').classList.add('done'); await post('/api/planner/done', { id: c.dataset.id, done: true }); setTimeout(todayW, 600); });
  el.querySelectorAll('[data-del]').forEach(b => b.onclick = async (e) => { e.preventDefault(); await post('/api/planner/delete', { kind: 'tasks', id: b.dataset.del }); todayW(); });
  const f = document.getElementById('w-today-add');
  if (f && !f.dataset.bound) {
    f.dataset.bound = '1';
    f.onsubmit = async (e) => { e.preventDefault(); const i = f.querySelector('input'); const v = i.value.trim(); if (!v) return;
      i.value = ''; await post('/api/planner/task', { text: v }); todayW(); tasksW(); };
  }
}
async function tasksW() {
  const r = await api('/api/tasks').catch(() => ({ tasks: [] }));
  const pl = await api('/api/planner').catch(() => ({ events: [], tasks: [] }));
  const now = new Date(), y = now.getFullYear(), mo = now.getMonth();
  const days = new Set(r.tasks.filter(t => t.enabled && t.next_run).map(t => new Date(t.next_run * 1000).toDateString()));
  pl.events.forEach(e => days.add(new Date(e.start).toDateString()));
  pl.tasks.filter(t => t.due).forEach(t => days.add(new Date(t.due).toDateString()));
  const cal = document.getElementById('w-cal');
  if (cal) {
    document.getElementById('w-month').textContent = now.toLocaleDateString('ru', { month: 'long', year: 'numeric' });
    const first = new Date(y, mo, 1), start = (first.getDay() + 6) % 7; let html = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'].map(d => `<div class="dn">${d}</div>`).join('');
    for (let i = 0; i < 42; i++) {
      const d = new Date(y, mo, 1 - start + i);
      if (i >= 35 && d.getMonth() !== mo) break;
      html += `<div class="d ${d.getMonth() !== mo ? 'other' : ''} ${d.toDateString() === now.toDateString() ? 'today' : ''} ${days.has(d.toDateString()) ? 'has' : ''}">${d.getDate()}</div>`;
    }
    cal.innerHTML = html;
  }
  const tl = document.getElementById('w-tasks');
  if (tl) {
    const up = r.tasks.filter(t => t.enabled && t.next_run).sort((a, b) => a.next_run - b.next_run).slice(0, 5);
    tl.innerHTML = up.map(t => `<div class="ti">${t.kind === 'reminder' ? '🔔' : t.kind === 'command' ? '⚙' : '✻'} ${esc(t.name)}<small>${new Date(t.next_run * 1000).toLocaleString('ru', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</small></div>`).join('')
      || '<div class="sub">Пусто. Скажи: «напомни через 20 минут выпить воды»</div>';
  }
}
