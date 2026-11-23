import { api, post, esc, h, ICON, toast, prefs, savePrefs, debounce } from '../core.js';

let root;
const ACCENTS = ['#D97757', '#E0A458', '#7FB069', '#4FB3A9', '#5B9BE6', '#8E7FD0', '#D46BA3', '#E26D5A', '#C9C3BA'];
const BGS = { 'Ночь (из лого)': ['#141224', '#2A2350', '#4A2A35'], 'Графит': ['#151514', '#2A2927', '#3A3532'], 'Дым': ['#101010', '#3A3A3A', '#6A6A6A'],
  'Океан': ['#0B1622', '#123A5A', '#1D5A6A'], 'Неон': ['#120A1F', '#3B1260', '#0E4F6E'], 'Лес': ['#0D1712', '#1F3A28', '#4A3A20'] };
const WIDGETS = [['today', 'Сегодня (дела)'], ['system', 'Система'], ['weather', 'Погода'], ['media', 'Музыка'], ['calendar', 'Календарь'], ['tasks', 'Задачи'], ['notes', 'Заметки'], ['activity', 'Активность']];
const row = (b, s, ctl) => `<div class="row"><span class="lbl"><b>${b}</b>${s ? `<small>${s}</small>` : ''}</span>${ctl}</div>`;
const tog = (on, id) => `<div class="tog ${on ? 'on' : ''}" id="${id}"></div>`;
const rng = (id, min, max, step, val) => `<input type="range" id="${id}" min="${min}" max="${max}" step="${step}" value="${val}" style="width:220px">`;

export async function mount(el) { root = el; }
export function show() { paint(); }

async function paint() {
  const ui = prefs.ui || {}, orb = ui.orb || {}, s = await api('/api/settings');
  const keepScroll = (root.querySelector('.page-pad') || {}).scrollTop || 0;
  root.innerHTML = '';
  root.appendChild(h(`<div class="page-pad"><div class="narrow">
    <h1>Настройки</h1>
    <div class="card"><h3>${ICON('user')} Профиль</h3>
      ${row('Как тебя называть', 'для приветствия на главной', `<input class="txt" id="sName" value="${esc(prefs.user_name || '')}" style="width:220px">`)}
      ${row('Город', 'для погоды', `<input class="txt" id="sCity" value="${esc(prefs.home_city || s.home_city || '')}" style="width:220px">`)}</div>

    <div class="card"><h3>${ICON('wave')} Музыка</h3>
      ${row('Где включать песни', '«включи песню …»: YouTube запускает сразу, Spotify и Яндекс открывают поиск', `<div class="seg2" id="sMus">${[['youtube', 'YouTube'], ['spotify', 'Spotify'], ['yandex', 'Яндекс']].map(([v, t]) => `<button data-v="${v}" class="${((prefs.music || {}).service || 'youtube') === v ? 'on' : ''}">${t}</button>`).join('')}</div>`)}</div>

    <div class="card"><h3>${ICON('sparkle')} Внешний вид</h3>
      ${row('Акцентный цвет', 'кнопки, шар, подсветка', `<div class="swatches">${ACCENTS.map(c => `<button style="background:${c}" data-acc="${c}" class="${(ui.accent || '#D97757').toLowerCase() === c.toLowerCase() ? 'on' : ''}"></button>`).join('')}<input type="color" id="sAcc" value="${ui.accent || '#D97757'}"></div>`)}
      ${row('Фон', 'живой «дым» как у Astra, градиент или однотонный', `<div class="seg2" id="sBg">${[['smoke', 'Дым'], ['gradient', 'Градиент'], ['solid', 'Однотонный']].map(([v, t]) => `<button data-v="${v}" class="${(ui.background || 'smoke') === v ? 'on' : ''}">${t}</button>`).join('')}</div>`)}
      ${row('Палитра фона', '', `<div class="swatches">${Object.entries(BGS).map(([n, c]) => `<button title="${n}" data-bgp="${n}" style="background:linear-gradient(135deg,${c.join(',')})"></button>`).join('')}
        ${(ui.bg_colors || []).map((c, i) => `<input type="color" data-bgc="${i}" value="${c}">`).join('')}</div>`)}
      ${row('Скорость фона', '', rng('sBgSp', 0, 3, .1, ui.bg_speed ?? 1))}
      ${row('Стекло (размытие панелей)', 'выключи на слабом ПК', tog(ui.glass !== false, 'sGlass'))}
      ${row('Анимации', 'появление страниц, пульсации, движение фона', tog(ui.animations !== false, 'sAnim'))}
      ${row('Лиса в углу главной', '', tog(ui.corner_fox !== false, 'sFox'))}</div>

    <div class="card"><h3>◉ Шар</h3>
      ${row('Форма', '', `<div class="seg2" id="sOrbS">${[['sphere', 'Сфера'], ['galaxy', 'Галактика'], ['ring', 'Кольцо']].map(([v, t]) => `<button data-v="${v}" class="${(orb.style || 'sphere') === v ? 'on' : ''}">${t}</button>`).join('')}</div>`)}
      ${row('Частиц', 'больше — красивее, но тяжелее', rng('sOrbN', 300, 5000, 100, orb.particles ?? 1800))}
      ${row('Размер', '', rng('sOrbSz', .5, 1.5, .05, orb.size ?? 1))}
      ${row('Скорость вращения', '', rng('sOrbSp', 0, 3, .1, orb.speed ?? 1))}
      ${row('Свечение', '', rng('sOrbG', 0, 2.5, .1, orb.glow ?? 1))}
      ${row('Орбиты-кольца', '', tog(orb.rings !== false, 'sOrbR'))}</div>

    <div class="card"><h3>${ICON('grid')} Виджеты главной</h3>
      ${row('Показывать панель виджетов', '', tog((prefs.widgets || {}).show !== false, 'sW'))}
      <div class="swatches" style="margin-top:10px">${WIDGETS.map(([k, t]) => `<span class="chip" style="cursor:pointer;${((prefs.widgets || {}).items || []).includes(k) ? '' : 'opacity:.4'}" data-wi="${k}">${t}</span>`).join('')}</div></div>

    <div class="card"><h3>${ICON('tg')} Telegram</h3>
      ${row(s.telegram.configured ? '@' + esc(s.telegram.bot || '?') + (s.telegram.connected ? ' · подключён' : ' · нет связи') : 'Бот не настроен',
        s.telegram.paired ? 'привязано устройств: ' + s.telegram.paired : s.telegram.pair_code ? 'отправь боту: /pair ' + s.telegram.pair_code : '',
        `<div style="display:flex;gap:6px"><button class="btn sm" id="sTgCode">новый код</button><button class="btn sm" id="sTgTok">токен</button></div>`)}</div>

    <div class="card" id="sWol"><h3>${ICON('power')} Включение ПК удалённо</h3>
      <div class="sub" style="margin-bottom:8px">Выключенный ПК не может слушать бота, но сетевая карта остаётся под питанием и просыпается от
        «волшебного пакета». Отправить его можно с телефона через интернет (роутер пропускает пакет домой) или с устройства,
        которое дома всегда включено. Выключать ПК можно как раньше — основному боту: «выключи пк».</div>
      <div id="wolBody" class="sub">проверяю сетевую карту…</div></div>

    <div class="card"><h3>${ICON('gear')} Система</h3>
      ${row('Запускать с Windows', 'в трей, окно не открывается', tog(s.autostart, 'sAuto'))}
      ${row('Перезапустить сервер Renard', 'применить плагины и обновления', `<button class="btn" id="sRestart">${ICON('refresh')} Перезапуск</button>`)}
      ${row('Папки агента', s.folders.length + ' разрешено', `<a class="btn" href="#/chats/files">${ICON('folder')} Управлять</a>`)}</div>

    <div class="card" id="sHealth"><h3>${ICON('pulse')} Здоровье Renard <span class="grow"></span><button class="btn sm" id="hRe">${ICON('refresh', 'sm')} Проверить</button></h3>
      <div id="hBody" class="sub">проверяю…</div></div>

    <div class="card" id="sDiag"><h3>${ICON('pulse')} Диагностика</h3>
      <div class="sub" style="margin-bottom:8px">Все ошибки, зависания и конфликты Renard пишутся в скрытый журнал
        <code>data\\logs\\renard.log</code> — если что-то сломалось, его можно прочитать и найти причину.</div>
      <div id="diagConf" class="sub">проверяю конфликты…</div>
      ${row('Последние ошибки и предупреждения', 'из журнала', `<button class="btn" id="sLogShow">Показать</button>`)}
      <pre id="sLog" class="sub" style="display:none;max-height:320px;overflow:auto;white-space:pre-wrap;font-size:11.5px"></pre></div>
  </div></div>`));
  root.querySelector('.page-pad').scrollTop = keepScroll;
  const $ = (id) => root.querySelector(id);
  const ui2 = (patch) => savePrefs({ ui: patch });
  $('#sName').onchange = (e) => savePrefs({ user_name: e.target.value.trim() });
  $('#sCity').onchange = async (e) => { await savePrefs({ home_city: e.target.value.trim() }); await post('/api/settings', { home_city: e.target.value.trim() }); toast('Город сохранён'); };
  root.querySelectorAll('[data-acc]').forEach(b => b.onclick = () => ui2({ accent: b.dataset.acc }).then(paint));
  $('#sAcc').oninput = debounce((e) => ui2({ accent: e.target.value }), 150);
  root.querySelectorAll('#sMus button').forEach(b => b.onclick = () => savePrefs({ music: { service: b.dataset.v } }).then(paint));
  root.querySelectorAll('#sBg button').forEach(b => b.onclick = () => ui2({ background: b.dataset.v }).then(paint));
  root.querySelectorAll('[data-bgp]').forEach(b => b.onclick = () => ui2({ bg_colors: BGS[b.dataset.bgp], background: 'smoke' }).then(paint));
  root.querySelectorAll('[data-bgc]').forEach(inp => inp.oninput = debounce(() => { const c = [...(ui.bg_colors || [])]; c[+inp.dataset.bgc] = inp.value; ui2({ bg_colors: c }); }, 150));
  $('#sBgSp').oninput = debounce((e) => ui2({ bg_speed: +e.target.value }), 120);
  const t = (id, fn) => $(id).onclick = (e) => { const on = !e.target.classList.contains('on'); e.target.classList.toggle('on', on); fn(on); };
  t('#sGlass', on => ui2({ glass: on })); t('#sAnim', on => ui2({ animations: on })); t('#sFox', on => ui2({ corner_fox: on }));
  root.querySelectorAll('#sOrbS button').forEach(b => b.onclick = () => ui2({ orb: { style: b.dataset.v } }).then(paint));
  const orbR = (id, key) => $(id).oninput = debounce((e) => ui2({ orb: { [key]: +e.target.value } }), 120);
  orbR('#sOrbN', 'particles'); orbR('#sOrbSz', 'size'); orbR('#sOrbSp', 'speed'); orbR('#sOrbG', 'glow');
  t('#sOrbR', on => ui2({ orb: { rings: on } }));
  t('#sW', on => savePrefs({ widgets: { show: on } }));
  root.querySelectorAll('[data-wi]').forEach(c => c.onclick = () => {
    const items = new Set((prefs.widgets || {}).items || []); items.has(c.dataset.wi) ? items.delete(c.dataset.wi) : items.add(c.dataset.wi);
    savePrefs({ widgets: { items: WIDGETS.map(w => w[0]).filter(k => items.has(k)) } }).then(paint);
  });
  $('#sTgCode').onclick = async () => { const r = await post('/api/telegram/paircode'); toast('Новый код: /pair ' + r.pair_code); paint(); };
  $('#sTgTok').onclick = async () => { const tok = prompt('Токен бота от @BotFather:'); if (!tok) return; const r = await post('/api/telegram/token', { token: tok }); toast(r.connected ? 'Бот @' + r.bot + ' подключён' : 'Ошибка: ' + r.error); paint(); };
  t('#sAuto', async on => { const r = await post('/api/settings', { autostart: on }); toast(r.autostart ? 'Renard будет запускаться с Windows' : 'Автозапуск выключен'); });
  $('#sRestart').onclick = async () => { await post('/api/restart').catch(() => {}); toast('Перезапускаю сервер…'); setTimeout(() => location.reload(), 6000); };
  paintWol(); paintDiag(); paintHealth();
  $('#hRe').onclick = paintHealth;
}

const STAGES = { llm: 'модель', route: 'быстрые команды', tool: 'инструменты', study: 'справочники', vram: 'проверка видеопамяти',
  prompt: 'сборка запроса', toolpick: 'подбор инструментов', other: 'прочее' };
const LEVEL = { ok: ['✅', 'var(--ok)'], warn: ['⚠', 'var(--warn)'], bad: ['✖', 'var(--err)'], off: ['○', 'var(--dim, #8a8580)'] };
const sec = (x) => x == null ? '?' : (x < 1 ? Math.round(x * 1000) + ' мс' : x.toFixed(1) + ' с');

async function paintHealth() {
  const box = root.querySelector('#hBody'); if (!box) return;
  box.textContent = 'проверяю…';
  let r;
  try { r = await api('/api/health'); } catch (e) { box.textContent = 'не удалось проверить: ' + e.message; return; }
  if (!box.isConnected) return;
  const items = r.items.map(i => { const [ic, col] = LEVEL[i.level] || LEVEL.off;
    return `<div class="row"><span class="lbl"><b style="color:${col}">${ic} ${esc(i.name)}</b><small>${esc(i.detail)}</small></span></div>`; }).join('');
  const sp = r.speed || {};
  const speed = sp.n ? `<div class="row"><span class="lbl"><b>⏱ Скорость ответов</b><small>последние ${sp.n}: обычно ${sec(sp.median)}, 9 из 10 быстрее ${sec(sp.p90)}.
      В среднем на ответ: ${Object.entries(sp.avg_by || {}).filter(([, v]) => v >= .05).map(([k, v]) => `${STAGES[k] || esc(k)} ${sec(v)}`).join(' · ')}</small></span></div>
    ${(sp.slowest || []).slice(0, 3).map(s => `<div class="row"><span class="lbl"><small>медленно ${sec(s.total)}: «${esc((s.text || '').slice(0, 70))}» — ${Object.entries(s.by || {}).sort((a, b) => b[1] - a[1]).slice(0, 2).map(([k, v]) => `${STAGES[k] || esc(k)} ${sec(v)}`).join(', ')}</small></span></div>`).join('')}`
    : `<div class="row"><span class="lbl"><b>⏱ Скорость ответов</b><small>пока нет замеров — появятся после первых ответов</small></span></div>`;
  const t = r.tests || {};
  const tests = (t.eval || t.replay) ? `<div class="row"><span class="lbl"><b>🧪 Последние проверки</b><small>${[
    t.eval ? `фразы с живой моделью: ${t.eval.ok}/${t.eval.total}` : '',
    t.replay ? `повтор реальных разговоров: ${t.replay.ok}/${t.replay.total} без изменений (${esc(t.replay.ts)})` : ''].filter(Boolean).join(' · ')}</small></span></div>` : '';
  const log = r.log || {};
  const errs = (log.top || []).length ? `<details style="margin-top:6px"><summary class="sub" style="cursor:pointer">Журнал за сутки: ${log.errors} ошибок, ${log.warnings} предупреждений</summary>
    ${log.top.map(g => `<div class="row"><span class="lbl"><small><b style="color:${g.level === 'WARNING' ? 'var(--warn)' : 'var(--err)'}">${g.count}×</b> ${esc(g.text)} <span class="dim">(${esc(g.last.slice(5, 16))})</span></small></span></div>`).join('')}</details>` : '';
  box.innerHTML = items + speed + tests + errs;
}

async function paintDiag() {
  const box = root.querySelector('#diagConf');
  try {
    const r = await post('/api/conflicts/rescan');
    box.innerHTML = r.conflicts.length
      ? r.conflicts.map(c => `<div class="row"><span class="lbl"><b style="color:var(--warn,#E0A458)">⚠ ${esc(c.name)}</b><small>${esc(c.text)}</small></span></div>`).join('')
      : '✅ Конфликтующих программ не найдено.';
  } catch (e) { box.textContent = 'не удалось проверить: ' + e.message; }
  root.querySelector('#sLogShow').onclick = async () => {
    const pre = root.querySelector('#sLog');
    const r = await api('/api/logs?n=4000');
    const bad = r.lines.filter(l => / (ERROR|WARNI|CRITI)/.test(l)).slice(-60);
    pre.textContent = bad.length ? bad.join('\n') : 'Ошибок нет 👍';
    pre.style.display = 'block';
  };
}

async function paintWol() {
  const box = root.querySelector('#wolBody');
  if (!box) return;
  let w;
  try { w = await api('/api/wol'); } catch (e) { box.textContent = 'Не удалось проверить: ' + e.message; return; }
  if (!box.isConnected) return;
  const mark = (ok) => ok === true ? '<span style="color:#7FB069">✓</span>' : ok === false ? '<span style="color:#E26D5A">✗</span>' : '<span style="opacity:.7">•</span>';
  box.innerHTML = `
    ${row('Сетевая карта', w.mac ? `MAC ${esc(w.mac)} · IP ${esc(w.ip || '?')}` : '', w.ok ? '<span class="chip" style="color:#7FB069">готово</span>' : '<span class="chip">нужна настройка</span>')}
    <div class="wol-checks">${(w.checks || []).map(c => `<div class="wol-c">${mark(c.ok)} <b>${esc(c.name)}</b><small>${esc(c.text)}</small></div>`).join('')}</div>
    ${wolNet(w)}
    <h4 class="wol-h">Способ 2 — бот-будильник на устройстве дома</h4>
    <div class="sub">Если дома есть всегда включённый телефон или Raspberry Pi: второй Telegram-бот на нём включит ПК по /on, без настройки роутера.</div>
    ${row('Бот-будильник', w.has_token ? 'токен сохранён на этом ПК' : 'создай второго бота в @BotFather (/newbot) и вставь его токен — основной бот для этого не подходит',
      `<input class="txt" id="wolTok" placeholder="${w.has_token ? 'токен сохранён' : '123456:ABC…'}" style="width:220px">`)}
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
      <button class="btn" id="wolBuild">${ICON('box')} Собрать будильник</button>
      <button class="btn primary" id="wolSend">${ICON('tg')} Собрать и прислать в Telegram</button></div>
    <div id="wolOut" class="sub" style="margin-top:6px">${w.package ? 'Готовый архив: ' + esc(w.package) : ''}</div>`;
  const go = async (send) => {
    const out = root.querySelector('#wolOut');
    out.textContent = 'собираю…';
    let r;
    try { r = await post('/api/wol/package', { token: root.querySelector('#wolTok').value.trim(), send }); }
    catch (e) { out.textContent = '✗ ' + e.message; toast(e.message); return; }
    out.innerHTML = `✓ Архив: ${esc(r.path)}${r.sent ? '<br>' + esc(r.sent) : ''}<br>Дальше: распакуй на устройстве и запусти <code>python renard_waker.py</code> (инструкция внутри, README.txt). Потом напиши будильнику /status.`;
  };
  root.querySelector('#wolBuild').onclick = () => go(false);
  root.querySelector('#wolSend').onclick = () => go(true);
  bindWolNet(w);
}

function wolNet(w) {
  const n = w.internet || {};
  const r = n.rule || {};
  const host = n.host || '?';
  return `<h4 class="wol-h">Способ 1 — кнопка на телефоне через интернет <span class="chip">без второго устройства</span></h4>
    ${row('Адрес дома в интернете', n.cgnat ? 'Это общий адрес провайдера (CGNAT): снаружи до роутера не достучаться — попроси у Play «publiczny adres IP»' :
      (n.custom_host ? 'своё имя (DDNS) — переживёт смену IP' : 'может смениться после перезапуска роутера — Renard тогда напишет новый в Telegram'),
      `<span class="chip">${esc(n.public_ip || 'не определён')}</span>`)}
    <div class="wol-rule"><b>1. В роутере</b> (${n.router ? `<a href="${esc(n.router)}" target="_blank">${esc(n.router)}</a>` : 'страница роутера'},
      логин и пароль обычно на наклейке) → раздел «Przekierowanie portów / Port forwarding / NAT» → новое правило:
      <div class="wol-kv"><span>Протокол</span><b>${esc(r.proto || 'UDP')}</b><span>Внешний порт</span><b>${esc(r.ext_port)}</b>
        <span>IP в сети</span><b>${esc(r.to_ip)}</b><span>Внутренний порт</span><b>${esc(r.to_port)}</b></div>
      <small>Если роутер не принимает адрес ${esc(r.to_ip)} (на .255) — укажи ${esc(r.to_ip_alt)} и закрепи этот IP за ПК
      («DHCP rezerwacja / Static lease» для MAC ${esc(w.mac)}). Пакет может только включить ПК — больше через этот порт ничего не сделать.</small></div>
    <div class="wol-rule"><b>2. На телефоне</b> — приложение «Wake On Lan» (Android, есть виджет-кнопка) → новое устройство:
      <div class="wol-kv"><span>MAC</span><b>${esc(w.mac)}</b><span>Адрес / хост</span><b>${esc(host)}</b><span>Порт</span><b>${esc(n.port)}</b></div>
      <small>Или готовая кнопка Termux:Widget — пришлю архив с инструкцией.</small></div>
    ${row('Своё имя вместо IP (необязательно)', 'например myhome.duckdns.org — тогда смена IP не ломает кнопку',
      `<input class="txt" id="wolHost" placeholder="имя DDNS" value="${n.custom_host ? esc(host) : ''}" style="width:180px">
       <input class="txt" id="wolPort" value="${esc(n.port)}" style="width:80px" title="внешний порт">
       <button class="btn" id="wolNetSave">Сохранить</button>`)}
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
      <button class="btn primary" id="wolTest">📱 Проверить с телефона</button>
      <button class="btn" id="wolBtn">${ICON('tg')} Прислать кнопку в Telegram</button></div>
    <div id="wolTestOut" class="sub" style="margin-top:6px">${n.tested ? '✓ Проброс проверен ' + esc(n.tested) + ' — включение через интернет работает.' : ''}</div>`;
}

function bindWolNet(w) {
  const $ = (id) => root.querySelector(id);
  if (!$('#wolTest')) return;
  const out = $('#wolTestOut');
  $('#wolNetSave').onclick = async () => {
    try { await post('/api/wol/internet', { host: $('#wolHost').value.trim(), port: $('#wolPort').value.trim() }); toast('Сохранено'); paintWol(); }
    catch (e) { toast(e.message); }
  };
  $('#wolBtn').onclick = async () => {
    out.textContent = 'собираю…';
    try { const r = await post('/api/wol/button', { send: true }); out.textContent = r.sent || ('Архив: ' + r.path); }
    catch (e) { out.textContent = '✗ ' + e.message; }
  };
  $('#wolTest').onclick = async () => {
    const n = w.internet || {};
    out.textContent = 'запускаю проверку…'; delete out.dataset.loc;
    try { await post('/api/wol/listen', { seconds: 180 }); } catch (e) { out.textContent = '✗ ' + e.message; return; }
    out.innerHTML = `<b>Слушаю 3 минуты…</b> Сейчас: выключи Wi-Fi на телефоне (нужен мобильный интернет) и отправь пакет
      на <b>${esc(n.host)}:${esc(n.port)}</b> (кнопка или приложение). ПК при этом не выключится — я просто увижу, что пакет дошёл.`;
    const t0 = Date.now();
    const poll = async () => {
      if (!document.body.contains(out)) return;
      let s;
      try { s = await api('/api/wol/listen'); } catch { s = {}; }
      const ext = (s.hits || []).find(h => h.external), loc = (s.hits || []).find(h => !h.external);
      if (ext) { out.innerHTML = `<span style="color:#7FB069">✓ Работает!</span> Пакет пришёл из интернета (с ${esc(ext.from)}). Теперь кнопка включит выключенный ПК.`; return; }
      if (s.error && !(s.ports || []).length) { out.textContent = '✗ ' + s.error; return; }
      if (loc && !out.dataset.loc) { out.dataset.loc = 1; out.insertAdjacentHTML('beforeend', `<br>Пакет пришёл, но из домашней сети (${esc(loc.from)}) — выключи Wi-Fi на телефоне и отправь ещё раз.`); }
      if (s.running !== false && Date.now() - t0 < 185000) return setTimeout(poll, 1500);
      out.innerHTML = `✗ За 3 минуты пакет из интернета не пришёл. Проверь правило в роутере (UDP, порт ${esc(n.port)} → ${esc((n.rule || {}).to_ip)}, порт 9).
        Если правило верное — у провайдера может быть общий адрес (CGNAT): тогда нужен «publiczny adres IP» от Play или способ 2.`;
    };
    setTimeout(poll, 1500);
  };
}
