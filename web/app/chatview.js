import { api, esc, md, h, state, setOrb, setActiveView, wsSend, prefs, emit, uid, post, toast } from './core.js';
import { feedbackBar, codeCopy } from './feedback.js';

const FILE_RX = /[A-Za-z]:\\(?:[^\\\n\r"'`<>|*?:]+\\)*[^\\\n\r"'`<>|*?:]+?\.(png|jpe?g|webp|gif|bmp|pdf|docx?|xlsx?|pptx?|odt|ods|odp|txt|md|csv|zip|rar|7z|mp3|wav|ogg|m4a|mp4|mkv|webm|html?|svg|py|js|json)(?=$|[\s`'")\]»,;.!?])/gi;
const IMG_RX = /\.(png|jpe?g|webp|gif|bmp)$/i;
const ICON = { pdf: '📕', doc: '📝', docx: '📝', odt: '📝', xls: '📊', xlsx: '📊', ods: '📊', csv: '📊', ppt: '📽', pptx: '📽', odp: '📽',
  zip: '🗜', rar: '🗜', '7z': '🗜', mp3: '🎵', wav: '🎵', ogg: '🎵', m4a: '🎵', mp4: '🎬', mkv: '🎬', webm: '🎬' };
export function filesHtml(text, extra = '') {
  const all = [...new Set([...(text || '').matchAll(FILE_RX), ...((extra || '').match(/(?:Сохранил|сохранил|Saved|Создал|создал|записал|Записал)[^\n]*/g) || []).flatMap(l => [...l.matchAll(FILE_RX)])].map(m => m[0].replace(/[.,;]$/, '')))].slice(0, 8);
  if (!all.length) return '';
  const imgs = all.filter(p => IMG_RX.test(p)), docs = all.filter(p => !IMG_RX.test(p));
  const name = (p) => esc(p.split(/[\\/]/).pop());
  return `<div class="files-out">${imgs.map(p => `<figure class="file-img"><img class="att-img" src="/api/file?path=${encodeURIComponent(p)}" alt="" title="${name(p)}" onerror="this.closest('figure').remove()">
      <figcaption><span title="${esc(p)}">${name(p)}</span><button class="mini" data-open="${esc(p)}">Открыть</button><button class="mini" data-reveal="${esc(p)}">В папке</button></figcaption></figure>`).join('')}
    ${docs.map(p => { const ext = (p.split('.').pop() || '').toLowerCase();
      return `<div class="file-card">${ICON[ext] || '📄'} <span>${name(p)}</span><button class="mini" data-open="${esc(p)}">Открыть</button><button class="mini" data-reveal="${esc(p)}">В папке</button></div>`; }).join('')}</div>`;
}
document.addEventListener('click', (e) => {
  const b = e.target.closest && e.target.closest('[data-open],[data-reveal]');
  if (!b || !b.closest('.files-out')) return;
  post('/api/open_path', { path: b.dataset.open || b.dataset.reveal, reveal: !!b.dataset.reveal })
    .then(r => { if (r && r.error) toast(r.error); }).catch(err => toast('Не открылось: ' + err.message));
});

export function learnCard(ev) {
  const c = h(`<div class="learn">
    <div class="lh">💾 Сохранить как команду? <small>в следующий раз сделаю это сразу, без нейросети</small></div>
    <div class="lsteps">${ev.steps.map(s => `<span class="chip">${esc(s.label)}</span>`).join('<span class="arr">→</span>')}</div>
    <div class="lrow"><label>Название<input class="ln" value="${esc(ev.name || '')}"></label>
      <label>Фразы (через запятую)<input class="lp" value="${esc(ev.phrase || '')}"></label></div>
    <div class="lrow"><button class="btn sm primary ls">Сохранить команду</button><button class="btn sm lx">Не надо</button></div></div>`);
  c.querySelector('.lx').onclick = () => c.remove();
  c.querySelector('.ls').onclick = async () => {
    const name = c.querySelector('.ln').value.trim(), phrases = c.querySelector('.lp').value.trim();
    if (!phrases) { toast('Нужна хотя бы одна фраза'); return; }
    try {
      const r = await post('/api/commands/learn', { name, phrases, steps: ev.steps });
      if (r.error) { toast(r.error); return; }
      c.innerHTML = `<div class="lh ok">✓ Команда «${esc(r.name)}» сохранена. Скажи или напиши «${esc(phrases.split(',')[0])}» — выполню сразу. <a href="#/commands">Открыть в «Командах»</a></div>`;
    } catch (e) { toast('Не удалось сохранить: ' + e.message); }
  };
  return c;
}

const MODE_NAMES = { low: 'низкий', medium: 'средний', high: 'высокий', router: '⚡ без LLM' };

let actx = null;
export function audioCtx() { if (!actx) actx = new (window.AudioContext || window.webkitAudioContext)(); return actx; }
const speechBus = 'BroadcastChannel' in window ? new BroadcastChannel('nx-speech') : null;
export function meter(node) {
  const an = audioCtx().createAnalyser(); an.fftSize = 512; node.connect(an);
  const buf = new Uint8Array(an.fftSize); let alive = true;
  (function tick() {
    if (!alive) return; an.getByteTimeDomainData(buf);
    let s = 0; for (const v of buf) { const x = (v - 128) / 128; s += x * x; }
    const lv = Math.min(1, Math.sqrt(s / buf.length) * 4);
    state.level = Math.max(state.level, lv); speechBus?.postMessage({ level: lv }); requestAnimationFrame(tick);
  })();
  return { stop: () => { alive = false; speechBus?.postMessage({ level: 0, done: true }); } };
}
const SQ = { q: [], playing: false, gen: 0, src: null, chars: 0, cut: false };
const SPEAK_LIMIT = 650;
export function stopSpeaking() {
  SQ.gen++; SQ.q = []; SQ.chars = 0; SQ.cut = false; SQ.playing = false;
  if (SQ.src) try { SQ.src.stop(); } catch (e) {}
  SQ.src = null;
}
function ttsFetch(text) {
  return fetch('/api/voice/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, limit: 400 }) })
    .then(r => r.ok ? r.arrayBuffer() : null).catch(() => null);
}
export function splitSpeech(text, first = 90, max = 220) {
  const parts = (text || '').replace(/```[\s\S]*?```/g, ' Код на экране. ').split(/(?<=[.!?…])\s+|\n+/).map(s => s.trim()).filter(s => /[\wа-яё]/i.test(s));
  const out = []; let cur = '';
  for (const p of parts) {
    const lim = out.length ? max : first;
    if (cur && cur.length + p.length + 1 > lim) { out.push(cur); cur = p; } else cur = (cur + ' ' + p).trim();
  }
  if (cur) out.push(cur);
  return out;
}
export function enqueueSpeech(text) {
  for (const p of splitSpeech(text)) {
    if (SQ.cut) return;
    if (SQ.chars && SQ.chars + p.length > SPEAK_LIMIT) { SQ.cut = true; SQ.q.push(ttsFetch('Остальное на экране.')); break; }
    SQ.chars += p.length; SQ.q.push(ttsFetch(p));
  }
  if (!SQ.playing) playNext(SQ.gen);
}
async function playNext(gen) {
  if (gen !== SQ.gen) return;
  const next = SQ.q.shift();
  if (!next) { SQ.playing = false; if (!state.busy) setOrb('idle'); return; }
  SQ.playing = true;
  const ab = await next;
  if (gen !== SQ.gen) return;
  if (!ab || !ab.byteLength) return playNext(gen);
  try {
    const ac = audioCtx(); const buf = await ac.decodeAudioData(ab);
    if (gen !== SQ.gen) return;
    const src = SQ.src = ac.createBufferSource(); src.buffer = buf; src.connect(ac.destination);
    const m = meter(src); setOrb('speaking');
    src.onended = () => { m.stop(); if (SQ.src === src) SQ.src = null; playNext(gen); };
    src.start();
  } catch (e) { playNext(gen); }
}
export async function speak(text) {
  stopSpeaking();
  if (!(text || '').trim()) { setOrb('idle'); return; }
  enqueueSpeech(text);
}

document.addEventListener('click', (e) => {
  const img = e.target.closest && e.target.closest('img.att-img');
  if (!img) return;
  const all = [...img.closest('.msg, .chips-in, body').querySelectorAll('img.att-img')];
  let i = all.indexOf(img);
  const ov = h(`<div class="lightbox"><img alt=""><div class="lb-bar"><span class="lb-n"></span>
    <a class="btn sm" target="_blank" download>Сохранить</a><button class="btn sm lb-x">Закрыть ✕</button></div></div>`);
  const show = () => { const s = all[i].src; ov.querySelector('img').src = s; ov.querySelector('a').href = s;
    ov.querySelector('.lb-n').textContent = all.length > 1 ? `${i + 1} / ${all.length} · ${all[i].title || ''}` : (all[i].title || ''); };
  const close = () => { ov.remove(); removeEventListener('keydown', key); };
  const key = (k) => { if (k.key === 'Escape') close(); if (k.key === 'ArrowRight') { i = (i + 1) % all.length; show(); }
    if (k.key === 'ArrowLeft') { i = (i - 1 + all.length) % all.length; show(); } };
  ov.onclick = (ev) => { if (ev.target === ov || ev.target.classList.contains('lb-x')) close(); };
  addEventListener('keydown', key); document.body.appendChild(ov); show();
});

export class ChatView {
  constructor(root, { compact = false, onTitle = null } = {}) {
    this.root = root; this.compact = compact; this.onTitle = onTitle;
    this.session = null; this.project = ''; this.cur = null; this.raw = ''; this.route = false;
    this.speakNext = false; this.renderT = null;
  }
  async load(sid) {
    this.session = sid; this.root.innerHTML = '';
    if (!sid) return;
    let r; try { r = await api('/api/chats/' + encodeURIComponent(sid)); } catch (e) { return; }
    this.project = r.project || this.project;
    let lastUser = '';
    for (const m of r.messages) {
      if (m.role === 'user') { this.userMsg(m.content, m.time); lastUser = m.content; }
      else this.botStatic(m.content, m.mode, m.time, lastUser);
    }
    this.scroll();
    return r;
  }
  newSession(project = '') { this.session = uid(); this.project = project; this.root.innerHTML = ''; return this.session; }
  scroll() { const s = this.root.closest('.scroll') || this.root; s.scrollTop = s.scrollHeight; }
  userMsg(text, time = '') {
    const IMG = /\.(png|jpe?g|webp|gif|bmp)$/i;
    const files = [...text.matchAll(/\[(файл|папка): ([^\]]+)\]/g)].map(m => IMG.test(m[2])
      ? `<img class="att-img" src="/api/file?path=${encodeURIComponent(m[2])}" alt="" title="${esc(m[2].split(/[\\/]/).pop())}">`
      : `<span class="chip">${m[1] === 'папка' ? '📁' : '📄'} ${esc(m[2].split(/[\\/]/).pop())}</span>`).join('');
    const clean = text.split(/\n\n(?=\[Пользователь прислал|Текст голосового сообщения)/)[0].replace(/\[(файл|папка): [^\]]+\]\s*/g, '');
    this.root.appendChild(h(`<div class="msg user">${files ? `<div class="chips-in">${files}</div>` : ''}<div>${esc(clean)}</div>${time ? `<time>${time}</time>` : ''}</div>`));
  }
  botStatic(content, mode, time, user = '') {
    const plain = mode === 'router';
    const el = h(`<div class="msg bot"><div class="meta">${MODE_NAMES[mode] || esc(mode || '')}${time ? ' · ' + time : ''}</div>
      <div class="${plain ? 'plain' : 'md'}">${plain ? esc(content) : md(content)}</div>${filesHtml(content)}</div>`);
    if (!this.compact && user) el.appendChild(feedbackBar({ user, answer: content, session: this.session }));
    codeCopy(el);
    this.root.appendChild(el);
  }
  send(text, { mode = '', perm = 'manual', voice = false } = {}) {
    if (!text.trim() || state.busy) return false;
    if (!this.session) this.newSession(this.project);
    this.userMsg(text); this.bot(); this.scroll(); this.lastUser = text; this.used = [];
    this.speakNext = voice || !!(prefs.voice || {}).speak_answers;
    this.spokenTo = 0; this.speechOverride = false;
    if (this.speakNext) stopSpeaking();
    state.busy = true; setOrb('thinking'); setActiveView(this); emit('busy', true);
    wsSend({ text, session: this.session, mode, perm, project: this.project || '', voice: !!voice, speak: this.speakNext });
    if (this.onTitle) this.onTitle(this.session);
    return true;
  }
  bot() {
    this.cur = h(`<div class="msg bot live"><div class="meta"></div><div class="steps"></div><div class="md"></div></div>`);
    this.root.appendChild(this.cur); this.raw = ''; this.route = false;
  }
  speakStream(final) {
    if (!this.speakNext || this.speechOverride) return;
    if (this.route) {
      if (final && this.raw.trim() && this.raw.length < 240 && !this.raw.includes('\n- ')) enqueueSpeech(this.raw);
      return;
    }
    const rest = this.raw.slice(this.spokenTo);
    if (!final && (rest.split('```').length - 1) % 2) return;
    let cut = rest.length;
    if (!final) {
      const re = /[.!?…](?=\s)|\n/g; let m, last = -1;
      while ((m = re.exec(rest))) last = m.index + 1;
      if (last < (this.spokenTo ? 60 : 25)) return;
      cut = last;
    }
    const chunk = rest.slice(0, cut); this.spokenTo += cut;
    if (chunk.trim()) enqueueSpeech(chunk);
  }
  meta(html) { const m = this.cur.querySelector('.meta'); m.innerHTML += (m.innerHTML ? ' · ' : '') + html; }
  render() { const t = this.cur.querySelector(this.route ? '.plain' : '.md'); if (!t) return; if (this.route) t.textContent = this.raw; else t.innerHTML = md(this.raw); }
  onEvent(ev) {
    if (ev.type === 'timing') return;
    if (!this.cur) this.bot();
    const steps = this.cur.querySelector('.steps');
    if (ev.type === 'token') {
      if (state.orb !== 'speaking') setOrb('speaking');
      this.raw += ev.text; state.level = Math.max(state.level, .25);
      if (!this.renderT) this.renderT = setTimeout(() => { this.renderT = null; this.render(); this.scroll(); }, 50);
      this.speakStream(false);
    } else if (ev.type === 'speech') {
      this.speechOverride = true;
      if (this.speakNext) enqueueSpeech(ev.text);
    } else if (ev.type === 'route') {
      this.route = true; const mdEl = this.cur.querySelector('.md'); if (mdEl) mdEl.className = 'plain';
      this.meta(`<span class="ok">⚡ без LLM · ${esc(ev.tool)} · ${ev.ms} мс</span>`);
    } else if (ev.type === 'mode') {
      setOrb('thinking'); this.meta(`<span class="acc">✻</span> ${MODE_NAMES[ev.mode] || ev.mode} · ${esc(ev.model)}`);
    } else if (ev.type === 'note') {
      emit('note', ev.text);
    } else if (ev.type === 'tool') {
      setOrb('tool');
      this.toolText = (this.toolText || '') + '\n' + (ev.result || '');
      const d = h(`<details class="tool"><summary>● ${esc(ev.name)} <span class="args">${esc(JSON.stringify(ev.args)).slice(0, 120)}</span></summary><pre>${esc(ev.result)}</pre></details>`);
      steps.appendChild(d); this.scroll();
      setTimeout(() => state.orb === 'tool' && setOrb('thinking'), 600);
    } else if (ev.type === 'stats') {
      if ((ev.tokens ?? 0) >= 5) this.meta(`${ev.tps ?? '?'} ток/с · ${ev.wall_s} с`);
    } else if (ev.type === 'confirm') {
      const box = h(`<div class="confirm">⚠ Подтвердить <b>${esc(ev.name)}</b>?
        <button class="btn sm ok" data-a="да">Да</button><button class="btn sm" data-a="нет">Нет</button></div>`);
      box.querySelectorAll('button').forEach(b => b.onclick = () => { box.remove(); emit('confirm-answer', b.dataset.a); });
      this.cur.appendChild(box);
    } else if (ev.type === 'skills') {
      this.used = [...(ev.skills || []), ...(ev.lessons || [])];
      if ((ev.skills || []).length) this.meta(`<span title="навык подобран к запросу">📘 ${esc(ev.skills.join(', '))}</span>`);
      if ((ev.lessons || []).length) this.meta(`<span title="твои уроки из 👎">🎓 уроков: ${ev.lessons.length}</span>`);
    } else if (ev.type === 'sources') {
      this.cur.appendChild(h(`<div class="md sources">${md(ev.md)}</div>`));
    } else if (ev.type === 'suggest_command') {
      this.cur.appendChild(learnCard(ev));
    } else if (ev.type === 'error') {
      setOrb('error'); this.cur.appendChild(h(`<div class="err">${esc(ev.text)}</div>`));
    } else if (ev.type === 'done') {
      clearTimeout(this.renderT); this.renderT = null; this.render(); emit('note', '');
      const fh = filesHtml(this.raw, this.toolText || ''); this.toolText = '';
      if (fh) this.cur.appendChild(h(fh));
      codeCopy(this.cur);
      if (!this.compact && this.raw.trim()) this.cur.appendChild(feedbackBar({ user: this.lastUser || '', answer: this.raw,
        session: this.session, used: this.used || [] }));
      this.cur.classList.remove('live'); const said = this.raw; this.cur = null;
      state.busy = false; emit('busy', false); setActiveView(null);
      if (this.speakNext) { this.speakStream(true); if (!SQ.playing && !SQ.q.length) setOrb('idle'); } else setOrb('idle');
      this.speakNext = false; emit('chat-done', { session: this.session, text: said });
    }
  }
}
