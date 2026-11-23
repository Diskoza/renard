export const bus = new EventTarget();
export const on = (type, fn) => bus.addEventListener(type, (e) => fn(e.detail));
export const emit = (type, detail) => bus.dispatchEvent(new CustomEvent(type, { detail }));

const logq = [], seenMsg = new Map(); let logT = 0;
export function report(level, kind, msg, extra = {}) {
  msg = String(msg ?? '').slice(0, 1500);
  const key = kind + msg, now = Date.now();
  if (now - (seenMsg.get(key) || 0) < 60000) return;
  seenMsg.set(key, now);
  logq.push({ level, kind, msg, page: location.hash, ...extra });
  if (logq.length > 60) logq.splice(0, logq.length - 60);
  clearTimeout(logT); logT = setTimeout(flushLog, 1200);
}
function flushLog() {
  if (!logq.length) return;
  const body = JSON.stringify(logq.splice(0));
  fetch('/api/clientlog', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true }).catch(() => {});
}
addEventListener('error', (e) => report('error', 'js', e.message, { src: `${(e.filename || '').replace(location.origin, '')}:${e.lineno}:${e.colno}` }));
addEventListener('error', (e) => {
  const t = e.target; if (t && t !== window && (t.src || t.href)) report('warn', 'resource', 'не загрузилось', { url: t.src || t.href });
}, true);
addEventListener('unhandledrejection', (e) => report('error', 'promise', (e.reason && (e.reason.stack || e.reason.message)) || String(e.reason)));
const foreignSeen = new Set();
addEventListener('securitypolicyviolation', (e) => {
  const u = e.blockedURI || 'inline'; let host = u;
  try { host = new URL(u).host; } catch {}
  if (foreignSeen.has(host)) return; foreignSeen.add(host);
  report('warn', 'foreign', `заблокирован чужой ${e.effectiveDirective}`, { url: u.slice(0, 200), sample: (e.sample || '').slice(0, 80) });
  emit('foreign', host);
});

export async function api(path, opts = {}) {
  const o = { ...opts };
  if (o.body && typeof o.body !== 'string' && !(o.body instanceof Blob) && !(o.body instanceof File) && !(o.body instanceof FormData)) {
    o.body = JSON.stringify(o.body); o.headers = { 'Content-Type': 'application/json', ...(o.headers || {}) };
  }
  const ms = o.timeout ?? ((o.method || 'GET') === 'GET' ? 20000 : 180000); delete o.timeout;
  const ctl = new AbortController(), outer = o.signal;
  if (outer) outer.addEventListener('abort', () => ctl.abort());
  o.signal = ctl.signal;
  const tm = ms ? setTimeout(() => ctl.abort(), ms) : 0, t0 = performance.now();
  try {
    const r = await fetch(path, o);
    const ct = r.headers.get('content-type') || '';
    const data = ct.includes('json') ? await r.json() : await r.text();
    const dt = performance.now() - t0;
    if (dt > 5000 && path !== '/api/clientlog') report('warn', 'slow', `${o.method || 'GET'} ${path} ${Math.round(dt)} мс`);
    if (!r.ok) {
      if (r.status >= 500) report('error', 'http', `${o.method || 'GET'} ${path} → ${r.status}`, { body: JSON.stringify(data).slice(0, 300) });
      throw new Error((data && (data.error || data.detail)) || r.statusText);
    }
    return data;
  } catch (e) {
    if (outer && outer.aborted) throw e;
    if (e.name === 'AbortError' || e instanceof TypeError) {
      const why = e.name === 'AbortError' ? `нет ответа ${Math.round(ms / 1000)} с` : 'нет связи';
      if (path !== '/api/status') report('warn', 'net', `${o.method || 'GET'} ${path}: ${why}`);
      throw new Error(`Renard: ${why}`);
    }
    throw e;
  } finally { if (tm) clearTimeout(tm); }
}
export const post = (path, body, opts = {}) => api(path, { method: 'POST', body: body ?? {}, ...opts });
export const del = (path) => api(path, { method: 'DELETE' });

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export function h(html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.childElementCount > 1 ? t.content : t.content.firstElementChild; }
export const sleep = (ms) => new Promise(r => setTimeout(r, ms));
export const uid = () => Math.random().toString(36).slice(2, 10);
export function debounce(fn, ms = 400) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

function inline(s) {
  s = s.replace(/!\[([^\]]*)\]\((https:\/\/[^)\s]+)\)/g, '<img class="att-img web-img" src="$2" alt="" title="$1" loading="lazy" referrerpolicy="no-referrer">');
  return s.replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|[\s(«])(https?:\/\/[^\s<)»]+[^\s<)».,;:!?])/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
}
document.addEventListener('error', (e) => { const t = e.target; if (t && t.classList && t.classList.contains('web-img')) t.remove(); }, true);
const SUBS = '₀₁₂₃₄₅₆₇₈₉', SUPS = '⁰¹²³⁴⁵⁶⁷⁸⁹';
const TEX = { '\\times': '×', '\\cdot': '·', '\\div': ':', '\\le': '≤', '\\ge': '≥', '\\neq': '≠', '\\approx': '≈',
  '\\rightarrow': '→', '\\to': '→', '\\pm': '±', '\\infty': '∞', '\\pi': 'π', '\\alpha': 'α', '\\beta': 'β', '\\Delta': 'Δ' };
function tex(s) {
  s = s.replace(/\\(?:text|mathrm|mathbf|textbf|operatorname)\{([^{}]*)\}/g, '$1')
    .replace(/\\frac\{([^{}]*)\}\{([^{}]*)\}/g, '($1)/($2)').replace(/\\sqrt\{([^{}]*)\}/g, '√($1)');
  for (const [k, v] of Object.entries(TEX)) s = s.split(k).join(v);
  s = s.replace(/_\{([0-9]+)\}|_([0-9])/g, (m, a, b) => [...(a || b)].map(d => SUBS[d]).join(''))
    .replace(/\^\{([0-9]+)\}|\^([0-9])/g, (m, a, b) => [...(a || b)].map(d => SUPS[d]).join(''));
  return s.replace(/[{}\\]/g, '');
}
export function delatex(t) {
  return (t || '').replace(/\$\$([\s\S]+?)\$\$/g, (m, a) => tex(a)).replace(/\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)/g, (m, a, b) => tex(a || b))
    .replace(/\$([^$\n]{1,200}?)\$/g, (m, a) => /[\\_^]/.test(a) ? tex(a) : m);
}
const MATH_RX = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|\$([^$\n]{1,300}?)\$/g;
function mathHtml(src, display) {
  if (window.katex) {
    try { return window.katex.renderToString(src, { throwOnError: false, displayMode: display, output: 'html', strict: 'ignore' }); } catch (e) {  }
  }
  return esc(tex(src));
}
function pullMath(text, store) {
  return text.split(/(`[^`\n]+`)/).map((part, k) => (k % 2 ? part : pullMathPart(part, store))).join('');
}
function pullMathPart(text, store) {
  return text.replace(MATH_RX, (m, d1, d2, i1, i2) => {
    const inl = i1 ?? i2, src = d1 ?? d2 ?? inl, display = inl === undefined;
    if (i2 !== undefined && (/^\s|\s$/.test(i2) || !/[\\_^=+\-*/<>]|^[a-zA-Z]$|\d[a-zA-Z]|[a-zA-Z]\d/.test(i2))) return m;
    store.push(display ? `<div class="math-block">${mathHtml(src.trim(), true)}</div>` : mathHtml(src.trim(), false));
    return `\u0000M${store.length - 1}\u0000`;
  });
}
export function md(src) {
  const math = [];
  const raw = String(src || '').split(/(```[\w+-]*\n?)/);
  let inCode = false, joined = '';
  for (const chunk of raw) {
    if (/^```/.test(chunk)) { inCode = !inCode; joined += chunk; continue; }
    joined += inCode ? chunk : pullMath(chunk, math);
  }
  const out = mdCore(joined);
  return math.length ? out.replace(/\u0000M(\d+)\u0000/g, (m, n) => math[+n] ?? '') : out;
}
function mdCore(src) {
  const parts = esc(delatex(src || '')).split(/```[\w+-]*\n?/); let html = '';
  parts.forEach((p, i) => {
    if (i % 2) { html += `<pre><code>${p.replace(/\n$/, '')}</code></pre>`; return; }
    let list = null, table = [];
    const flushTable = () => {
      if (!table.length) return;
      const rows = table.filter(r => !/^\s*\|?\s*:?-{2,}/.test(r)).map(r => r.replace(/^\s*\||\|\s*$/g, '').split('|'));
      html += '<table>' + rows.map((r, j) => '<tr>' + r.map(c => `<${j ? 'td' : 'th'}>${inline(c.trim())}</${j ? 'td' : 'th'}>`).join('') + '</tr>').join('') + '</table>';
      table = [];
    };
    for (const l of p.split('\n')) {
      if (/^\s*\|.*\|\s*$/.test(l)) { if (list) { html += `</${list}>`; list = null; } table.push(l); continue; }
      flushTable();
      const li = l.match(/^\s*([*-]|\d+\.)\s+(.*)/);
      if (li) { const tag = /\d/.test(li[1]) ? 'ol' : 'ul'; if (list !== tag) { if (list) html += `</${list}>`; html += `<${tag}>`; list = tag; } html += `<li>${inline(li[2])}</li>`; continue; }
      if (list) { html += `</${list}>`; list = null; }
      const hd = l.match(/^(#{1,3})\s+(.*)/);
      if (hd) html += `<h${hd[1].length + 2}>${inline(hd[2])}</h${hd[1].length + 2}>`; else if (l.trim()) html += `<p>${inline(l)}</p>`;
    }
    flushTable(); if (list) html += `</${list}>`;
  });
  return html;
}

export function toast(text, kind = '') {
  let box = $('#toasts'); if (!box) { box = h('<div id="toasts"></div>'); document.body.appendChild(box); }
  const t = h(`<div class="toast ${kind}">${esc(text)}</div>`); box.appendChild(t);
  setTimeout(() => t.classList.add('out'), 4200); setTimeout(() => t.remove(), 4700);
}

export let prefs = {};
export async function loadPrefs() { prefs = await api('/api/prefs'); applyTheme(); emit('prefs', prefs); return prefs; }
export async function savePrefs(patch) { prefs = await post('/api/prefs', patch); applyTheme(); emit('prefs', prefs); return prefs; }
function hexRgb(hx) { const n = parseInt(hx.replace('#', ''), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
export function accentRgb() { return hexRgb((prefs.ui && prefs.ui.accent) || '#D97757'); }
export function applyTheme() {
  const ui = prefs.ui || {}, r = document.documentElement.style;
  const [a, b, c] = hexRgb(ui.accent || '#D97757');
  r.setProperty('--acc', ui.accent || '#D97757'); r.setProperty('--acc-rgb', `${a},${b},${c}`);
  r.setProperty('--acc2', `rgb(${a * .85 | 0},${b * .78 | 0},${c * .7 | 0})`);
  document.body.classList.toggle('no-anim', ui.animations === false);
  document.body.classList.toggle('no-glass', ui.glass === false);
  document.body.dataset.bg = ui.background || 'smoke';
}

const I = (p) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
export const icon = {
  ear: I('<path d="M6 9a6 6 0 1 1 12 0c0 3-2 4-3 5.5S14 19 11.5 20 8 19 8 17"/><path d="M9.5 9.5a2.5 2.5 0 0 1 5 0c0 1.5-1.5 2-1.5 3"/>'),
  talk: I('<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/><path d="M8.5 12h.01M12 12h.01M15.5 12h.01"/>'),
  brain: I('<path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V5a2 2 0 0 0-3-1z"/><path d="M15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1"/>'),
  archive: I('<rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8M10 12h4"/>'),
  power: I('<path d="M12 3v9"/><path d="M6.3 6.3a8 8 0 1 0 11.4 0"/>'),
  pulse: I('<path d="M3 12h4l2-5 4 10 2-5h6"/>'),
  grad: I('<path d="M2 9l10-5 10 5-10 5z"/><path d="M6 11v5c3 2 9 2 12 0v-5"/>'),
  home: I('<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>'),
  chat: I('<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>'),
  cmd: I('<path d="m4 17 6-6-6-6"/><path d="M12 19h8"/>'),
  model: I('<path d="M12 2 3 7v10l9 5 9-5V7z"/><path d="M3 7l9 5 9-5M12 12v10"/>'),
  mic: I('<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5"/>'),
  ai: I('<rect x="5" y="5" width="14" height="14" rx="2"/><path d="M9 9h6v6H9zM9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>'),
  plug: I('<path d="M12 2 2 7l10 5 10-5z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/>'),
  gear: I('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'),
  plus: I('<path d="M12 5v14M5 12h14"/>'),
  send: I('<path d="M12 19V5M5 12l7-7 7 7"/>'),
  stop: I('<rect x="6" y="6" width="12" height="12" rx="2"/>'),
  clip: I('<path d="m21 11-8.6 8.6a5 5 0 0 1-7-7l8.6-8.6a3.3 3.3 0 0 1 4.7 4.7l-8.6 8.6a1.7 1.7 0 0 1-2.4-2.4l7.9-7.9"/>'),
  folder: I('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
  book: I('<path d="M4 4h11a3 3 0 0 1 3 3v13H7a3 3 0 0 1-3-3z"/><path d="M4 17a3 3 0 0 1 3-3h11"/>'),
  link: I('<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>'),
  search: I('<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>'),
  clock: I('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
  box: I('<path d="M3 7h18v13H3zM3 7l2-4h14l2 4M10 11h4"/>'),
  pin: I('<path d="M12 17v5M5 17h14l-2-5V4H7v8z"/>'),
  trash: I('<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/>'),
  edit: I('<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>'),
  play: I('<path d="M7 4v16l13-8z"/>'),
  pause: I('<path d="M7 4h4v16H7zM13 4h4v16h-4z"/>'),
  next: I('<path d="M5 4v16l10-8zM19 4v16"/>'),
  prev: I('<path d="M19 20V4L9 12zM5 4v16"/>'),
  grid: I('<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>'),
  x: I('<path d="M18 6 6 18M6 6l12 12"/>'),
  chev: I('<path d="m9 18 6-6-6-6"/>'),
  down: I('<path d="m6 9 6 6 6-6"/>'),
  bell: I('<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.9 1.9 0 0 0 3.4 0"/>'),
  cal: I('<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>'),
  note: I('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/>'),
  check: I('<path d="M20 6 9 17l-5-5"/>'),
  cpu: I('<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>'),
  temp: I('<path d="M14 14.8V4a2 2 0 0 0-4 0v10.8a4 4 0 1 0 4 0z"/>'),
  sun: I('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
  cloud: I('<path d="M17.5 19a4.5 4.5 0 1 0-1.4-8.8A6 6 0 1 0 6 18.9"/><path d="M6 19h11.5"/>'),
  rain: I('<path d="M17.5 15a4.5 4.5 0 1 0-1.4-8.8A6 6 0 1 0 6 14.9"/><path d="M8 19v2M12 18v3M16 19v2"/>'),
  menu: I('<path d="M4 6h16M4 12h16M4 18h16"/>'),
  eject: I('<path d="M5 17h14M12 5l7 8H5z"/>'),
  user: I('<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>'),
  sparkle: I('<path d="M12 3l1.8 5.4L19 10l-5.2 1.6L12 17l-1.8-5.4L5 10l5.2-1.6z"/>'),
  refresh: I('<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8M21 3v5h-5"/>'),
  expand: I('<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>'),
  download: I('<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>'),
  upload: I('<path d="M12 21V9M7 14l5-5 5 5M5 3h14"/>'),
  wave: I('<path d="M2 12h2M6 8v8M10 5v14M14 8v8M18 10v4M22 12h0"/>'),
  tg: I('<path d="m22 3-20 8 7 2 2 7 4-5 5 4z"/><path d="m9 13 13-10"/>'),
};
export const ICON = (name, cls = '') => `<span class="ico ${cls}">${icon[name] || ''}</span>`;

let ws = null, wsReady = false, queue = [], webBuild = null;
export let activeView = null;
export const setActiveView = (v) => { activeView = v; };
export function wsSend(obj) { if (wsReady) ws.send(JSON.stringify(obj)); else queue.push(obj); }
export function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = async () => {
    wsReady = true; emit('ws', true); queue.splice(0).forEach(o => ws.send(JSON.stringify(o)));
    try {
      const b = await (await fetch('/api/build')).json();
      if (webBuild === null) webBuild = b.web; else if (b.web !== webBuild && !state.busy) location.reload();
    } catch (e) {}
  };
  ws.onclose = () => { wsReady = false; emit('ws', false); setTimeout(connect, 1500); };
  ws.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (['activity', 'alert', 'memory', 'task', 'prefs', 'commands_changed', 'avatar', 'beat', 'open_page'].includes(ev.type)) { emit(ev.type, ev); return; }
    if (activeView) activeView.onEvent(ev); emit('agent', ev);
  };
}

export const state = { orb: 'idle', level: 0, load: { cpu: 0, gpu: 0 }, busy: false, status: null };
export function setOrb(s) { state.orb = s; emit('orb', s); }
