import { api, post, esc, h, ICON, prefs, savePrefs, state, setOrb, toast, on, $, wsSend, emit } from './core.js';
import { audioCtx, meter, stopSpeaking } from './chatview.js';

const MODES = [['', 'Ум: авто'], ['low', 'Ум: низкий'], ['medium', 'Ум: средний'], ['high', 'Ум: высокий']];
const PERMS = [['manual', 'Спрашивать', 'спрашивает перед изменениями'], ['auto', 'Без вопросов', 'сам решает; удаление всё равно спросит']];

export class Composer {
  constructor(root, { onSubmit, compact = false, placeholder = 'Напиши Renard…', getProject = null, setProject = null } = {}) {
    this.onSubmit = onSubmit; this.getProject = getProject; this.setProject = setProject; this.files = [];
    this.el = h(`<div class="composer ${compact ? 'compact' : ''}">
      <div class="atts"></div>
      <div class="row">
        ${compact ? `<button class="ic plusb" title="Добавить">${ICON('plus')}</button>` : ''}
        <textarea rows="1" placeholder="${esc(placeholder)}"></textarea>
        ${compact ? `<button class="ic clipb" title="Файл">${ICON('clip')}</button><button class="ic micb" title="Голос (Ctrl+Alt+V)">${ICON('mic')}</button>` : ''}
        ${compact ? `<button class="ic sendb primary" title="Отправить">${ICON('send')}</button>` : ''}
      </div>
      ${compact ? '' : `<div class="bar">
        <button class="ic plusb" title="Добавить (файл, папка, навыки…)">${ICON('plus')}</button>
        <button class="ic micb" title="Голос (Ctrl+Alt+V)">${ICON('mic')}</button>
        <span class="grow"></span>
        <button class="pick modeb" title="Режим ИИ"></button>
        <button class="pick permb" title="Подтверждения"></button>
        <button class="ic sendb primary" title="Отправить (Enter)">${ICON('send')}</button>
      </div>`}
      <input type="file" multiple hidden>
    </div>`);
    root.appendChild(this.el);
    this.t = this.el.querySelector('textarea');
    this.t.addEventListener('input', () => this.autosize());
    this.t.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.submit(); }
      if (e.key === 'u' && e.ctrlKey) { e.preventDefault(); this.pickFiles(); }
    });
    this.el.querySelector('.sendb').onclick = () => state.busy ? this.stop() : this.submit();
    this.el.querySelector('.plusb').onclick = (e) => this.menu(e.currentTarget);
    const clip = this.el.querySelector('.clipb'); if (clip) clip.onclick = () => this.pickFiles();
    this.el.querySelector('.micb').onclick = () => this.mic();
    this.fileInput = this.el.querySelector('input[type=file]');
    this.fileInput.onchange = () => { this.upload([...this.fileInput.files]); this.fileInput.value = ''; };
    this.el.addEventListener('dragover', e => { e.preventDefault(); this.el.classList.add('drop'); });
    this.el.addEventListener('dragleave', () => this.el.classList.remove('drop'));
    this.el.addEventListener('drop', e => { e.preventDefault(); this.el.classList.remove('drop'); this.upload([...e.dataTransfer.files]); });
    this.t.addEventListener('paste', e => {
      const items = [...(e.clipboardData && e.clipboardData.items || [])].filter(i => i.kind === 'file');
      if (!items.length) return;
      e.preventDefault();
      const files = items.map((i, n) => { const f = i.getAsFile(); if (!f) return null;
        return f.name && f.name !== 'image.png' ? f : new File([f], `screenshot_${Date.now()}_${n}.png`, { type: f.type || 'image/png' }); }).filter(Boolean);
      this.upload(files);
    });
    const mb = this.el.querySelector('.modeb'), pb = this.el.querySelector('.permb');
    if (mb) { mb.onclick = (e) => this.pickMenu(e.currentTarget, MODES.map(m => [m[0], m[1], '']), (prefs.chat || {}).mode || '', v => savePrefs({ chat: { mode: v } }).then(() => this.paint())); }
    if (pb) { pb.onclick = (e) => this.pickMenu(e.currentTarget, PERMS, (prefs.chat || {}).permission || 'manual', v => savePrefs({ chat: { permission: v } }).then(() => this.paint())); }
    on('prefs', () => this.paint()); on('busy', () => this.paint());
    this.paint();
  }
  paint() {
    const c = prefs.chat || {};
    const mb = this.el.querySelector('.modeb'), pb = this.el.querySelector('.permb');
    if (mb) mb.innerHTML = `${(MODES.find(m => m[0] === (c.mode || '')) || MODES[0])[1]} ${ICON('down', 'sm')}`;
    if (pb) { const p = PERMS.find(m => m[0] === (c.permission || 'manual')); pb.innerHTML = `${p[1]} ${ICON('down', 'sm')}`; pb.classList.toggle('auto', p[0] === 'auto'); }
    const sb = this.el.querySelector('.sendb'); sb.innerHTML = state.busy ? ICON('stop') : ICON('send'); sb.classList.toggle('busy', state.busy);
  }
  autosize() { this.t.style.height = 'auto'; this.t.style.height = Math.min(this.t.scrollHeight, 220) + 'px'; }
  focus() { this.t.focus(); }
  setText(s) { this.t.value = s; this.autosize(); this.t.focus(); }
  submit(voice = false) {
    const text = (this.files.map(f => `[${f.kind}: ${f.path}]`).join(' ') + ' ' + this.t.value).trim();
    if (!text || state.busy) return;
    const c = prefs.chat || {};
    if (this.onSubmit({ text, mode: c.mode || '', perm: c.permission || 'manual', voice }) !== false) {
      this.t.value = ''; this.files = []; this.paintAtts(); this.autosize();
    }
  }
  stop() { stopSpeaking(); wsSend({ type: 'stop' }); emit('note', 'останавливаю…'); }
  paintAtts() {
    const box = this.el.querySelector('.atts');
    box.innerHTML = this.files.map((f, i) => f.preview
      ? `<span class="chip img"><img src="${f.preview}" alt=""> ${esc(f.name)} <b data-i="${i}">×</b></span>`
      : `<span class="chip">${f.kind === 'папка' ? '📁' : '📄'} ${esc(f.name)} <b data-i="${i}">×</b></span>`).join('');
    box.querySelectorAll('b').forEach(b => b.onclick = () => { this.files.splice(+b.dataset.i, 1); this.paintAtts(); });
  }
  pickFiles() { this.fileInput.click(); }
  async upload(files) {
    for (const f of files) {
      try {
        const r = await fetch('/api/upload?name=' + encodeURIComponent(f.name), { method: 'POST', body: f }).then(x => {
          if (!x.ok) throw new Error('HTTP ' + x.status); return x.json(); });
        const preview = /^image\//.test(f.type || '') ? URL.createObjectURL(f) : '';
        this.files.push({ kind: 'файл', name: f.name, path: r.path, preview });
      } catch (e) { toast('Не удалось загрузить ' + f.name + ': ' + e.message, 'err'); }
    }
    this.paintAtts();
  }
  async addFolder() {
    const p = prompt('Путь к папке (например D:\\Projects\\site):');
    if (!p) return;
    const r = await post('/api/settings', { folder: p });
    if (r.error) { toast(r.error, 'err'); return; }
    this.files.push({ kind: 'папка', name: p.split(/[\\/]/).filter(Boolean).pop(), path: r.folder }); this.paintAtts();
  }
  closeMenus() { document.querySelectorAll('.popmenu').forEach(m => m.remove()); }
  pop(anchor, html, up = true) {
    this.closeMenus();
    const m = h(`<div class="popmenu">${html}</div>`); document.body.appendChild(m);
    const r = anchor.getBoundingClientRect();
    m.style.left = Math.min(r.left, innerWidth - m.offsetWidth - 10) + 'px';
    m.style.top = (up ? r.top - m.offsetHeight - 8 : r.bottom + 8) + 'px';
    setTimeout(() => document.addEventListener('click', (e) => { if (!m.contains(e.target)) m.remove(); }, { once: true }), 0);
    return m;
  }
  pickMenu(anchor, items, cur, cb) {
    const m = this.pop(anchor, items.map(([v, t, d]) => `<div class="mi ${v === cur ? 'on' : ''}" data-v="${v}"><div>${t}${d ? `<small>${d}</small>` : ''}</div>${v === cur ? ICON('check', 'sm') : ''}</div>`).join(''));
    m.querySelectorAll('.mi').forEach(el => el.onclick = () => { m.remove(); cb(el.dataset.v); });
  }
  async menu(anchor) {
    const m = this.pop(anchor, `
      <div class="mi" data-a="file">${ICON('clip')}<div>Загрузить файл</div><kbd>Ctrl+U</kbd></div>
      <div class="mi" data-a="folder">${ICON('folder')}<div>Добавить папку</div></div>
      <div class="sep"></div>
      <div class="mi sub" data-a="skills">${ICON('book')}<div>Навыки</div>${ICON('chev', 'sm')}</div>
      <div class="mi sub" data-a="mcp">${ICON('link')}<div>Коннекторы</div>${ICON('chev', 'sm')}</div>
      <div class="mi sub" data-a="plugins">${ICON('plug')}<div>Плагины</div>${ICON('chev', 'sm')}</div>
      ${this.setProject ? `<div class="mi sub" data-a="project">${ICON('box')}<div>Проект</div>${ICON('chev', 'sm')}</div>` : ''}`);
    m.querySelector('[data-a=file]').onclick = () => { m.remove(); this.pickFiles(); };
    m.querySelector('[data-a=folder]').onclick = () => { m.remove(); this.addFolder(); };
    const subOpen = async (el, fn) => {
      document.querySelectorAll('.popmenu.second').forEach(x => x.remove());
      const items = await fn(); const r = el.getBoundingClientRect();
      const s = h(`<div class="popmenu second">${items}</div>`); document.body.appendChild(s);
      s.style.left = (r.right + 6) + 'px'; s.style.top = Math.max(10, Math.min(r.top, innerHeight - s.offsetHeight - 10)) + 'px';
      s.querySelectorAll('[data-go]').forEach(x => x.onclick = () => { this.closeMenus(); location.hash = x.dataset.go; });
      s.querySelectorAll('[data-skill]').forEach(x => x.onclick = () => { this.closeMenus(); this.setText(`Используй навык ${x.dataset.skill}: ` + this.t.value); });
      s.querySelectorAll('[data-mcp]').forEach(x => x.onclick = () => { this.closeMenus(); this.setText(`Через коннектор ${x.dataset.mcp}: ` + this.t.value); });
      s.querySelectorAll('[data-proj]').forEach(x => x.onclick = () => { this.closeMenus(); this.setProject(x.dataset.proj); });
      document.addEventListener('click', (e) => { if (!s.contains(e.target) && !m.contains(e.target)) s.remove(); }, { once: true });
    };
    m.querySelector('[data-a=skills]').onmouseenter = (e) => subOpen(e.currentTarget, async () => {
      const r = await api('/api/skills');
      return r.skills.filter(s => s.enabled).map(s => `<div class="mi" data-skill="${esc(s.name)}"><div>${esc(s.name)}<small>${esc(s.description.slice(0, 70))}</small></div></div>`).join('') +
        `<div class="sep"></div><div class="mi" data-go="#/plugins/skills">${ICON('plus')}<div>Создать / найти навык</div></div>`;
    });
    m.querySelector('[data-a=mcp]').onmouseenter = (e) => subOpen(e.currentTarget, async () => {
      const r = await api('/api/mcp');
      return (r.servers.map(s => `<div class="mi" data-mcp="${esc(s.name)}"><div>${esc(s.name)}<small>${s.status === 'ready' ? s.tools.length + ' инструм.' : s.status}</small></div><span class="dot ${s.status}"></span></div>`).join('') || '<div class="mi dim">нет подключённых</div>') +
        `<div class="sep"></div><div class="mi" data-go="#/plugins/connectors">${ICON('plus')}<div>Подключить сервис</div></div>`;
    });
    m.querySelector('[data-a=plugins]').onmouseenter = (e) => subOpen(e.currentTarget, async () => {
      const r = await api('/api/plugins');
      return (r.plugins.map(p => `<div class="mi" data-go="#/plugins/plugins"><div>${esc(p.title || p.name)}<small>${esc(p.status)}</small></div></div>`).join('') || '<div class="mi dim">своих плагинов пока нет</div>') +
        `<div class="sep"></div><div class="mi" data-go="#/plugins/plugins">${ICON('plus')}<div>Создать плагин</div></div>`;
    });
    const pj = m.querySelector('[data-a=project]');
    if (pj) pj.onmouseenter = (e) => subOpen(e.currentTarget, async () => {
      const r = await api('/api/projects'); const cur = this.getProject ? this.getProject() : '';
      return `<div class="mi ${!cur ? 'on' : ''}" data-proj=""><div>Без проекта</div></div>` +
        r.projects.map(p => `<div class="mi ${p.id === cur ? 'on' : ''}" data-proj="${p.id}"><div>${esc(p.name)}</div></div>`).join('') +
        `<div class="sep"></div><div class="mi" data-go="#/chats/projects">${ICON('plus')}<div>Новый проект</div></div>`;
    });
  }
  async mic() {
    const btn = this.el.querySelector('.micb');
    if (this.rec && this.rec.state === 'recording') { this.rec.stop(); return; }
    try {
      stopSpeaking();
      fetch('/api/voice/warmup', { method: 'POST' });
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true,
        autoGainControl: true, channelCount: 1 } });
      const mm = meter(audioCtx().createMediaStreamSource(stream));
      this.rec = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' }); const chunks = [];
      this.rec.ondataavailable = e => chunks.push(e.data);
      this.rec.onstop = async () => {
        stream.getTracks().forEach(tr => tr.stop()); mm.stop(); btn.classList.remove('rec'); setOrb('thinking');
        try {
          const j = await (await fetch('/api/voice/stt', { method: 'POST', body: new Blob(chunks, { type: 'audio/webm' }) })).json();
          if (j.text) { this.t.value = j.text; this.submit(true); } else { toast('Не расслышал: ' + (j.error || 'пусто')); setOrb('idle'); }
        } catch (e) { toast('Ошибка распознавания: ' + e, 'err'); setOrb('error'); }
      };
      this.rec.start(); btn.classList.add('rec'); setOrb('listening');
      const an = audioCtx().createAnalyser(); an.fftSize = 1024; audioCtx().createMediaStreamSource(stream).connect(an);
      const buf = new Float32Array(an.fftSize), rec = this.rec, t0 = performance.now();
      let floor = 0.01, spoke = 0, quietSince = 0;
      const tick = () => {
        if (rec.state !== 'recording') return;
        an.getFloatTimeDomainData(buf); let s = 0; for (const v of buf) s += v * v;
        const rms = Math.sqrt(s / buf.length), now = performance.now(), loud = rms > Math.max(floor * 3, 0.012);
        if (!loud) floor = floor * 0.97 + rms * 0.03;
        if (loud) { spoke += 1; quietSince = 0; } else if (!quietSince) quietSince = now;
        if ((spoke > 8 && quietSince && now - quietSince > 1600) || now - t0 > 30000) { rec.stop(); return; }
        setTimeout(tick, 50);
      };
      setTimeout(tick, 300);
    } catch (e) { toast('Нет доступа к микрофону: ' + e, 'err'); }
  }
}
