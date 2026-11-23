import { api, post, del, esc, h, ICON, toast, prefs, savePrefs, debounce, on } from '../core.js';
import { renderAvatar, companionCfg, applyAvatarEvent, ACTION_RU, EMOTION_RU, DANCE_RU, ACCESSORIES } from '../avatar.js';
import { accSlot } from '../accessories.js';
import { drawChar, CHARS } from '../pixel.js';
const BUILTIN_PX = { '9089159310965215321.vrm': '@savi' };

let root, view = null, sub = 'chars', lastKey = '';

export async function mount(el) {
  root = el;
  on('prefs', () => { const c = companionCfg(); const k = c.kind + c.file; if (k !== lastKey && root.querySelector('#stage')) paint(); else if (view) view.apply(); });
  on('avatar', (ev) => applyAvatarEvent(view, ev));
}
export function show(params = []) { sub = params[0] || sub; paint(); }

async function paint() {
  const c = companionCfg(), av = (await api('/api/avatars')).avatars;
  const label = c.kind === 'vrm' ? `3D «${esc(c.file)}»` : c.kind === 'robot' ? `робот «${esc(c.file)}»` : c.kind === '2d' ? `2D «${esc(c.file)}»` : 'лиса Renard (2D)';
  root.innerHTML = '';
  root.appendChild(h(`<div class="page-pad"><div class="narrow" style="max-width:980px">
    <h1>Компаньон</h1>
    <div class="card" style="display:flex;align-items:center;gap:12px;padding:12px 16px"><span class="dot ${c.enabled ? 'on' : ''}"></span>
      <b style="flex:1">${c.enabled ? 'Включён' : 'Выключен'} <span class="sub">${label}</span></b>
      <span class="sub">Включить компаньона</span><div class="tog ${c.enabled ? 'on' : ''}" id="mOn"></div></div>
    <div class="seg2" style="margin:4px 0 14px">${[['chars', 'Персонажи'], ['look', 'Внешний вид'], ['window', 'Окно'], ['adv', 'Дополнительно']].map(([k, t]) => `<button data-s="${k}" class="${sub === k ? 'on' : ''}">${t}</button>`).join('')}</div>
    <div class="avatar-stage" id="stage"></div>
    ${sub === 'adv' ? `<details class="card av-acts fold"><summary><b>Жесты и эмоции</b> <span class="sub">— попробовать (то же самое ИИ делает сам: «помаши», «потанцуй», «сядь на панель»)</span></summary>
      <div class="chips">${Object.entries(ACTION_RU).map(([k, t]) => `<button class="chip" data-act="${k}">${t}</button>`).join('')}
        <button class="chip" data-act="sit">сесть</button><button class="chip" data-act="stand">встать</button><button class="chip" data-act="sleep">уснуть</button>
        <button class="chip" data-act="walk">погулять</button></div>
      <div class="chips" style="margin-top:6px"><span class="sub" style="align-self:center">Танцы:</span>${Object.entries(DANCE_RU).map(([k, t]) => `<button class="chip ghost" data-dance="${k}">💃 ${t}</button>`).join('')}</div>
      <div class="chips" style="margin-top:6px">${Object.entries(EMOTION_RU).filter(([k]) => k !== 'neutral').map(([k, t]) => `<button class="chip ghost" data-emo="${k}">${{ happy: '😊', sad: '😢', angry: '😠', surprised: '😮', relaxed: '😌' }[k] || ''} ${t}</button>`).join('')}</div></details>
    <details class="card fold" id="mAnims"><summary><b>Анимации</b> <span class="sub">— mocap для 3D-модели; ИИ тоже их включает: «попей чай», «станцуй гангнам». ✕ — убрать в корзину</span></summary>
      <div class="chips" id="mAnimCats" style="margin-top:8px"></div><div class="chips" id="mAnimList" style="margin-top:6px;max-height:220px;overflow:auto"></div>
      <div class="chips" style="margin-top:8px"><span class="sub" style="align-self:center">Своя анимация (.fbx со скелетом Mixamo):</span>
        <select class="txt" id="mAnimCat" style="width:150px"></select>
        <label class="chip"><input type="file" accept=".fbx" hidden id="mAnimUp" multiple>＋ добавить</label></div></details>` : ''}
    <div id="msub" style="margin-top:14px"></div></div></div>`));
  const RU = { idle: 'ожидание', walk: 'ходьба', dance: 'танцы', sit: 'сидя', gesture: 'жесты', emotion: 'эмоции', props: 'с предметами', misc: 'разное', music: 'музыка' };
  const animCard = (keep) => fetch('/anims/catalog.json?v=' + Date.now()).then(r => r.ok ? r.json() : []).then(cat => {
    const card = root.querySelector('#mAnims');
    if (!card) return;
    const cats = card.querySelector('#mAnimCats'), list = card.querySelector('#mAnimList'), sel = card.querySelector('#mAnimCat');
    const by = {}; cat.forEach(c => (by[c.cat] = by[c.cat] || []).push(c));
    sel.innerHTML = Object.keys(RU).map(k => `<option value="${k}">${RU[k]}</option>`).join('');
    const show = k => {
      if (!by[k]) { list.innerHTML = '<span class="sub">пусто</span>'; return; }
      sel.value = k;
      list.innerHTML = by[k].map(c => `<button class="chip ghost" data-anim="${esc(c.name)}">${esc(c.name)} <span class="x" data-adel="${esc(c.id)}" title="убрать в корзину">✕</span></button>`).join('');
      list.querySelectorAll('[data-anim]').forEach(b => b.onclick = async (e) => {
        const d = e.target.closest('[data-adel]');
        if (!d) return post('/api/avatar', { anim: b.dataset.anim });
        e.stopPropagation();
        if (!confirm(`Убрать анимацию «${b.dataset.anim}» в корзину?`)) return;
        const r = await del('/api/anims/' + encodeURIComponent(d.dataset.adel)).catch(err => ({ error: String(err) }));
        if (r.error) toast(r.error, 'err'); else animCard(k);
      });
    };
    cats.innerHTML = Object.keys(by).map(k => `<button class="chip" data-acat="${k}">${RU[k] || k} · ${by[k].length}</button>`).join('');
    cats.querySelectorAll('[data-acat]').forEach(b => b.onclick = () => show(b.dataset.acat));
    show(keep && by[keep] ? keep : Object.keys(by)[0]);
    card.querySelector('#mAnimUp').onchange = async (e) => {
      for (const f of e.target.files) {
        const r = await fetch(`/api/anims/upload?cat=${sel.value}&name=${encodeURIComponent(f.name)}`, { method: 'POST', body: f }).then(r => r.json()).catch(err => ({ error: String(err) }));
        if (r.error) { toast(r.error, 'err'); return; }
      }
      toast('Добавил: ' + e.target.files.length); animCard(sel.value);
    };
  }).catch(() => {});
  animCard();
  root.querySelectorAll('[data-act]').forEach(b => b.onclick = () => post('/api/avatar', { action: b.dataset.act }).then(r => r.text && !r.text.startsWith('Аватар') && toast(r.text)));
  root.querySelectorAll('[data-emo]').forEach(b => b.onclick = () => post('/api/avatar', { emotion: b.dataset.emo }));
  root.querySelectorAll('[data-dance]').forEach(b => b.onclick = () => post('/api/avatar', { action: 'dance', style: b.dataset.dance }));
  if (view) view.stop();
  lastKey = c.kind + c.file;
  const needSnap = (c.kind === 'vrm' || c.kind === 'robot') && !(av.find(a => a.name === c.file) || {}).thumb;
  if (c.kind === 'robot') {
    const { FACES } = await import('../robotface.js');
    setTimeout(() => {
      const acts = root.querySelector('.av-acts');
      if (!acts || acts.querySelector('[data-face]')) return;
      acts.appendChild(h(`<div class="chips" style="margin-top:6px"><span class="sub" style="align-self:center">Лицо-экран:</span>${Object.entries(FACES).map(([k, f]) =>
        `<button class="chip ghost" data-face="${k}" title="${esc(f.ru)}">${esc(f.ru.split(' / ')[0].split(':')[0])}</button>`).join('')}
        <button class="chip ghost" data-red>🔴 красный режим</button></div>`));
      acts.querySelectorAll('[data-face]').forEach(b => b.onclick = () => view?.showFace?.(b.dataset.face, 6));
      acts.querySelector('[data-red]').onclick = (e) => { const on = !e.target.classList.toggle('ghost'); view?.setRed?.(on); };
    }, 50);
  }
  view = renderAvatar(root.querySelector('#stage'), { snapshot: needSnap });
  root.querySelector('#mOn').onclick = () => savePrefs({ companion: { enabled: !c.enabled } }).then(paint);
  root.querySelectorAll('[data-s]').forEach(b => b.onclick = () => { location.hash = '#/model/' + b.dataset.s; });
  const box = root.querySelector('#msub');

  if (sub === 'chars') {
    await personaCard(box);
    const card = (a) => `<div class="char ${c.kind === a.kind && c.file === a.name ? 'on' : ''}" data-name="${esc(a.name)}" data-kind="${a.kind}">
        <button class="ic xdel" data-del="${esc(a.name)}" title="Удалить (в корзину)">${ICON('x', 'sm')}</button>
        <div class="pv">${a.thumb ? `<img src="${a.thumb}?v=${Date.now() % 100000}">` : '🧍'}</div>
        <b>${esc((a.title || a.name.replace(/\.[^.]+$/, '')).slice(0, 22))}</b><small>${a.kind === 'vrm' ? '3D · VRM' : a.kind === 'robot' ? '3D · робот, лицо-экран' : '2D · картинка'}</small></div>`;
    box.appendChild(h(`<div class="card"><h3>Персонажи</h3>
      <div class="sub">3D — файл .vrm (VRoid Studio бесплатно, VRoid Hub — с разрешённым использованием). 2D — любая картинка: PNG/WebP с прозрачным фоном или анимированный GIF.</div>
      <div class="chars" style="margin-top:12px">
        <div class="char ${c.kind === 'fox2d' ? 'on' : ''}" data-kind="fox2d"><div class="pv"><img src="/assets/renard_corner.svg"></div><b>Лиса Renard</b><small>2D · встроенная</small></div>
        ${av.map(card).join('')}
        <label class="char" style="display:block"><div class="pv">${ICON('upload')}</div><b>Добавить</b><small>.vrm или картинка</small>
          <input type="file" accept=".vrm,.glb,.png,.gif,.webp,.jpg,.jpeg,.svg" hidden id="mUp"></label>
      </div></div>`));
    box.querySelectorAll('.char[data-kind]').forEach(x => x.onclick = async (e) => {
      if (e.target.closest('[data-del]')) return;
      const kind = x.dataset.kind, file = x.dataset.name || '';
      const { sheets } = await api('/api/pixel_sheets').catch(() => ({ sheets: [] }));
      const px = kind === 'vrm' ? (BUILTIN_PX[file] || 'px_' + file.replace(/\.[^.]+$/, '').replace(/[^\w\-]+/g, '_').slice(0, 37)) : '';
      const has = px.startsWith('@') || (px && sheets.some(s => s.name === px));
      await savePrefs({ companion: { kind, file, vrm: kind === 'vrm' ? file : '', enabled: true, ...(kind === 'vrm' ? { pixel_sheet: has ? px : '' } : { pixel_sheet: '' }) } });
      paint();
      if (kind === 'vrm' && !has) bakePixel();
    });
    box.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
      if (!confirm(`Удалить ${b.dataset.del}? (в корзину)`)) return;
      await del('/api/avatars/' + encodeURIComponent(b.dataset.del));
      if (c.file === b.dataset.del) await savePrefs({ companion: { kind: 'fox2d', file: '', vrm: '' } });
      paint();
    });
    box.querySelector('#mUp').onchange = async (e) => {
      const f = e.target.files[0]; if (!f) return; toast('Загружаю ' + f.name + '…');
      const r = await fetch('/api/avatars/upload?name=' + encodeURIComponent(f.name), { method: 'POST', body: f }).then(r => r.json());
      if (r.error) return toast(r.error, 'err');
      await savePrefs({ companion: { kind: r.kind, file: r.name, vrm: r.kind === 'vrm' ? r.name : '', enabled: true, pixel_sheet: '' } }); paint();
      if (r.kind === 'vrm') bakePixel();
    };
    chibiCard(box, c);
  }
  if (sub === 'look') {
    box.appendChild(h(`<div class="card"><h3>Внешний вид</h3>
      <div class="row"><span class="lbl"><b>Размер</b></span><input type="range" min=".5" max="1.6" step=".05" value="${c.scale ?? 1}" id="mScale" style="width:220px"></div>
      <div class="row"><span class="lbl"><b>Толщина контура</b><small>MToon outline, только для VRM</small></span><input type="range" min="0" max="10" step=".5" value="${c.outline ?? 0}" id="mOut" style="width:220px"></div>
      <div class="row"><span class="lbl"><b>Смотреть на курсор</b><small>только для VRM</small></span><div class="tog ${c.look !== false ? 'on' : ''}" id="mLook"></div></div></div>`));
    box.querySelector('#mScale').oninput = debounce(e => savePrefs({ companion: { scale: +e.target.value } }), 150);
    box.querySelector('#mOut').oninput = debounce(e => savePrefs({ companion: { outline: +e.target.value } }), 150);
    box.querySelector('#mLook').onclick = (e) => { const on = !e.target.classList.contains('on'); e.target.classList.toggle('on', on); savePrefs({ companion: { look: on } }); };
    const worn = new Set(c.accessories || []);
    box.appendChild(h(`<div class="card" id="mAccCard"><h3>Аксессуары</h3>
      <div class="sub">${c.kind === 'vrm' ? 'Подгоняются под голову любой 3D-модели и двигаются вместе с ней. Голосом: «надень шапку», «сними очки».'
        : 'Аксессуары есть только у 3D-модели (VRM).'}</div>
      <div class="chips" style="margin-top:10px">${Object.entries(ACCESSORIES).map(([k, t]) => `<button class="chip ${worn.has(k) ? 'on' : 'ghost'}" data-acc="${k}">${t}</button>`).join('')}</div>
      <div class="row" style="margin-top:8px"><span class="lbl"><b>Наушники сами, когда играет музыка</b><small>снимает, когда музыка закончилась</small></span>
        <div class="tog ${c.auto_headphones !== false ? 'on' : ''}" id="mAutoHp"></div></div></div>`));
    box.querySelectorAll('[data-acc]').forEach(b => b.onclick = () => {
      const k = b.dataset.acc, cur = new Set(companionCfg().accessories || []);
      if (cur.has(k)) cur.delete(k); else { for (const x of [...cur]) if (accSlot(x) === accSlot(k)) cur.delete(x); cur.add(k); }
      savePrefs({ companion: { accessories: [...cur] } }).then(() => box.querySelectorAll('[data-acc]').forEach(x => {
        const on = cur.has(x.dataset.acc); x.classList.toggle('on', on); x.classList.toggle('ghost', !on); }));
    });
    box.querySelector('#mAutoHp').onclick = (e) => { const on = !e.target.classList.contains('on'); e.target.classList.toggle('on', on); savePrefs({ companion: { auto_headphones: on } }); };
  }
  if (sub === 'window') {
    const tog = (id, key, on, title, hint) => `<div class="row"><span class="lbl"><b>${title}</b><small>${hint}</small></span><div class="tog ${on ? 'on' : ''}" data-tog="${key}" id="${id}"></div></div>`;
    box.appendChild(h(`<div class="card"><h3>Рабочий стол</h3>
      ${tog('mDesk', 'desktop', c.desktop, 'Компаньон на рабочем столе', 'живёт на панели задач: стоит, сидит на её краю, гуляет; клики мимо него проходят насквозь')}
      ${tog('mWalk', 'walk', c.walk === true, 'Гулять самому (3D)', 'ходит по панели задач и по верхнему краю окна, на котором стоит, иногда спрыгивает вниз — может отвлекать, по умолчанию выключено')}
      ${tog('mDance', 'dance_music', c.dance_music !== false, 'Танцевать под музыку', 'когда на ПК играет музыка — кивает в такт, иногда танцует (раз в 3–5 минут)')}
      ${tog('mRem', 'remarks', c.remarks !== false, 'Замечания', 'иногда говорит в облачке: «с возвращением», «удачи» при запуске игры, «2 часа без перерыва», «уже поздно» — не чаще раза в 15 минут, без голоса')}
      ${tog('mSleep', 'sleep', c.sleep !== false, 'Засыпать без дела', 'через 5 минут тишины садится и спит; клик или голос — просыпается')}
      ${tog('mBub', 'bubbles', c.bubbles !== false, 'Облачка с репликами', 'ответы ИИ и напоминания над головой')}
      ${tog('mFs', 'hide_fullscreen', c.hide_fullscreen !== false, 'Прятаться в играх', 'скрывается, пока открыто полноэкранное приложение')}
      ${c.kind !== 'vrm' ? tog('mFlip', 'flip2d', !!c.flip2d, 'Отразить картинку', 'если 2D-персонаж смотрит не в ту сторону при ходьбе') : ''}
      <div class="row"><span class="lbl"><b>Размер на рабочем столе</b><small>окно перезапустится</small></span><input type="range" min=".6" max="1.6" step=".1" value="${c.size ?? 1}" id="mSize" style="width:220px"></div>
      <div class="sub" style="margin-top:6px">Мышь: клик — реакция, двойной клик — открыть Renard, перетащить — понесёт и уронит (можно уронить на окно), правый клик — меню.</div></div>
      <div class="card"><h3>Когда ИИ не занят — пиксельный</h3>
      ${tog('mPx', 'idle_pixel', c.idle_pixel !== false, 'Превращаться в пиксельного', 'маленький пиксельный Renard не отвлекает; большим становится, когда ты говоришь с ИИ')}
      <div class="row"><span class="lbl"><b>Через сколько</b><small>секунд тишины</small></span><select class="txt" id="mPxAfter" style="width:140px">${[10, 25, 60, 180].map(v => `<option value="${v}" ${(c.pixel_after || 25) === v ? 'selected' : ''}>${v} с</option>`).join('')}</select></div>
      <div class="row"><span class="lbl"><b>Где сидит</b><small>«сам» — на рамке окна, в котором ты работаешь, иначе в углу у часов</small></span><select class="txt" id="mPerch" style="width:200px">${[['auto', 'сам выбирает'], ['corner', 'в углу у часов'], ['window', 'на рамке окна']].map(([v, t]) => `<option value="${v}" ${(c.perch || 'auto') === v ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
      ${tog('mActs', 'activities', c.activities !== false, 'Свои занятия', 'приставка, мультики на диване, костёр, портативка, музыка (когда у тебя играет музыка — слушает с тобой), ночью спит')}
      <div class="row"><span class="lbl"><b>Размер пикселя</b></span><input type="range" min=".6" max="2" step=".2" value="${c.pixel_size ?? 1}" id="mPxSize" style="width:220px"></div>
      <div class="row"><span class="lbl"><b>Посмотреть все занятия</b></span><a class="chip" href="/app/pixel_preview.html?s=1.6" target="_blank">открыть превью</a></div></div>
      <div class="card" id="mWxCard"><h3>Погода на рабочем столе</h3>
      <div class="row"><span class="lbl"><b>Погода</b><small>снег падает поверх всего, ложится на верхние края окон и на панель задач, сыплется с окна, которое двигаешь или закрываешь, мышь его разгребает; клики проходят насквозь</small></span><select class="txt" id="mWx" style="width:200px">${[['off', 'выключена'], ['auto', 'как за окном'], ['snow', 'снег'], ['rain', 'дождь']].map(([v, t]) => `<option value="${v}" ${(c.weather || 'off') === v ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
      <div class="row"><span class="lbl"><b>Сколько</b></span><input type="range" min=".1" max="1" step=".1" value="${c.weather_amount ?? .5}" id="mWxAmt" style="width:220px"></div>
      ${tog('mWxPile', 'weather_piles', c.weather_piles !== false, 'Сугробы', 'снег копится на окнах и панели задач и тает, когда снегопад кончился')}
      ${tog('mWxDress', 'weather_dress', c.weather_dress !== false, 'Одеваться по погоде', 'в снег — шапка и шарф; ловит снежинки, отряхивается, ёжится под дождём')}
      <div class="sub" style="margin-top:6px">«Как за окном» — по виджету погоды (город в Настройках). Скриншоты и стримы погоду не видят. Прячется в полноэкранных играх. Нужен компаньон на рабочем столе.</div></div>
      <div class="card"><h3>Приложение</h3>${tog('mHome', 'on_home', c.on_home !== false, 'Показывать на главной', 'вместо лисы в углу')}</div>`));
    box.querySelectorAll('[data-tog]').forEach(t => t.onclick = (e) => {
      const on = !e.target.classList.contains('on'), key = e.target.dataset.tog; e.target.classList.toggle('on', on);
      savePrefs({ companion: { [key]: on } });
      if (key === 'desktop') toast(on ? 'Компаньон появится на панели задач через пару секунд' : 'Убрал с рабочего стола');
    });
    box.querySelector('#mSize').onchange = (e) => savePrefs({ companion: { size: +e.target.value } });
    box.querySelector('#mPxAfter').onchange = (e) => savePrefs({ companion: { pixel_after: +e.target.value } });
    box.querySelector('#mPerch').onchange = (e) => savePrefs({ companion: { perch: e.target.value } });
    box.querySelector('#mPxSize').onchange = (e) => savePrefs({ companion: { pixel_size: +e.target.value } });
    box.querySelector('#mWx').onchange = (e) => {
      savePrefs({ companion: { weather: e.target.value } });
      if (e.target.value !== 'off') toast(c.desktop ? 'Через пару секунд — погода на рабочем столе' : 'Включи «Компаньон на рабочем столе» — погода живёт вместе с ним');
    };
    box.querySelector('#mWxAmt').onchange = (e) => savePrefs({ companion: { weather_amount: +e.target.value } });
    sheetCard(box, c);
  }
  if (sub === 'adv') {
    box.appendChild(h(`<div class="card"><h3>Дополнительно</h3>
      <div class="row"><span class="lbl"><b>Состояние движка</b></span><span class="chip" id="mEng">${c.kind === 'vrm' ? 'загрузка…' : '2D'}</span></div>
      <div class="row"><span class="lbl"><b>Сглаживание (MSAA)</b><small>красивее края, чуть больше нагрузки на видеокарту</small></span><div class="tog ${c.msaa !== false ? 'on' : ''}" id="mMsaa"></div></div>
      <div class="row"><span class="lbl"><b>Ограничение FPS</b></span><select class="txt" id="mFps" style="width:120px">${[30, 60].map(f => `<option ${(c.fps || 30) === f ? 'selected' : ''}>${f}</option>`).join('')}</select></div></div>`));
    box.querySelector('#mMsaa').onclick = (e) => { const on = !e.target.classList.contains('on'); e.target.classList.toggle('on', on); savePrefs({ companion: { msaa: on } }).then(paint); };
    box.querySelector('#mFps').onchange = (e) => savePrefs({ companion: { fps: +e.target.value } });
    const eng = () => { const cv = root.querySelector('#stage canvas'), el = root.querySelector('#mEng'); if (el && cv && cv.dataset.engine) el.textContent = cv.dataset.engine; else if (el && cv) setTimeout(eng, 500); };
    eng();
  }
}

let baking = false;
async function personaCard(box) {
  const d = await api('/api/personas').catch(() => null); if (!d) return;
  const card = h(`<div class="card"><h3>Личность</h3>
    <div class="sub">Имя, характер, голос и слово для пробуждения — одним кликом. Голосом: «стань Джарвисом», «верни Ренара».
      Сейчас будить: <b>«${esc((d.wake || 'ренар').replace(/^./, c => c.toUpperCase()))}»</b></div>
    <div class="personas">${d.personas.map(p => `<div class="persona ${p.id === d.active ? 'on' : ''}" data-p="${esc(p.id)}">
      <i>${esc(p.emoji || '🙂')}</i><b>${esc(p.name)}</b><small>${esc(p.role || '')}</small>
      ${p.builtin ? '' : `<div class="pacts"><button class="ic" data-pe="${esc(p.id)}" title="Изменить">${ICON('edit', 'sm')}</button><button class="ic" data-pd="${esc(p.id)}" title="Удалить">${ICON('trash', 'sm')}</button></div>`}</div>`).join('')}
      <div class="persona add" data-new><i>＋</i><b>Своя личность</b><small>имя, характер, голос</small></div></div>
    <div id="pForm"></div></div>`);
  box.appendChild(card);
  card.querySelectorAll('[data-p]').forEach(el => el.onclick = async (e) => {
    if (e.target.closest('.pacts')) return;
    const r = await post(`/api/personas/${el.dataset.p}/activate`);
    toast(`${r.persona.emoji} ${r.persona.greeting}` + (r.notes.length ? ' — ' + r.notes.join('; ') : ''));
    card.remove(); await personaCard(box); box.prepend(box.lastElementChild);
  });
  card.querySelectorAll('[data-pd]').forEach(b => b.onclick = async () => { if (!confirm('Удалить личность?')) return; await del('/api/personas/' + b.dataset.pd); card.remove(); await personaCard(box); box.prepend(box.lastElementChild); });
  const form = (p = {}) => {
    const f = card.querySelector('#pForm');
    f.innerHTML = `<div class="pform">
      <input class="txt" id="pfName" placeholder="Имя (Джарвис, Вега…)" value="${esc(p.name || '')}">
      <input class="txt" id="pfEmoji" placeholder="Эмодзи" style="width:80px" value="${esc(p.emoji || '')}">
      <input class="txt" id="pfWake" placeholder="Слово пробуждения (одно слово)" value="${esc(p.wake || '')}">
      <select class="txt" id="pfVoice"><option value="">голос: не менять</option>${d.voices.map(v => `<option ${v === p.voice ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select>
      <input class="txt" id="pfAddr" placeholder="Как обращаться к тебе (сэр, босс…)" value="${esc(p.address || '')}">
      <input class="txt" id="pfRole" placeholder="Коротко: кто это" value="${esc(p.role || '')}">
      <textarea class="txt" id="pfPrompt" rows="3" placeholder="Характер и манера речи: «спокойный, говорит коротко, шутит про котов…»">${esc(p.prompt || '')}</textarea>
      <input class="txt" id="pfGreet" placeholder="Приветствие при включении" value="${esc(p.greeting || '')}">
      <div class="row"><button class="btn ok" id="pfSave">Сохранить</button><button class="btn" id="pfCancel">Отмена</button></div></div>`;
    f.querySelector('#pfCancel').onclick = () => { f.innerHTML = ''; };
    f.querySelector('#pfSave').onclick = async () => {
      const v = id => f.querySelector(id).value;
      try {
        const r = await post('/api/personas', { id: p.id, name: v('#pfName'), emoji: v('#pfEmoji'), wake: v('#pfWake'), voice: v('#pfVoice'),
          address: v('#pfAddr'), role: v('#pfRole'), prompt: v('#pfPrompt'), greeting: v('#pfGreet') });
        toast(r.warn || `Личность «${r.name}» сохранена`, r.warn ? 'err' : undefined);
        card.remove(); await personaCard(box); box.prepend(box.lastElementChild);
      } catch (err) { toast(err.message, 'err'); }
    };
  };
  card.querySelector('[data-new]').onclick = () => form();
  card.querySelectorAll('[data-pe]').forEach(b => b.onclick = () => form(d.personas.find(p => p.id === b.dataset.pe)));
}

async function bakePixel() {
  if (baking) return; baking = true;
  toast('Делаю пиксельную версию этой модели (~40 с)…');
  const r = await post('/api/pixel_sheets/bake').catch(e => ({ error: String(e) }));
  baking = false;
  if (r && r.ok) { toast('Готово: пиксельный компаньон теперь — эта модель'); if (sub === 'chars' || sub === 'window') paint(); }
  else toast('Не получилось сделать пиксельную версию: ' + ((r && r.error) || ''), 'err');
}
function pxPreview(cv, sheets) {
  const ch = cv.dataset.char, s = sheets.find(x => x.name === cv.dataset.sheet);
  const W = ch ? 44 : Math.max(44, s?.frame_w || 44), H = ch ? 50 : Math.max(50, s?.frame_h || 50);
  const low = document.createElement('canvas'); low.width = W; low.height = H; const l = low.getContext('2d');
  const ctx = cv.getContext('2d'); cv.height = Math.round(cv.width * H / W);
  let img = null; if (s) { img = new Image(); img.src = `/avatars/pixel/${encodeURIComponent(s.file)}?v=${s.mtime}`; }
  const t0 = performance.now();
  const tick = () => {
    if (!cv.isConnected) return;
    const t = (performance.now() - t0) / 1000;
    l.clearRect(0, 0, W, H);
    if (ch) {
      const G = CHARS[ch];
      drawChar(l, Math.round((W - G.W) / 2), H - 2 - G.floor, { char: ch, pose: G.floorPose, t, head: (t % 4) < .15 ? 'blink' : (t % 9) > 7.5 ? 'happy' : 'open' });
    } else if (img && img.complete && img.naturalWidth) {
      const a = s.anims?.idle || { row: 0, frames: 1 }, f = Math.floor(t * (a.fps || s.fps || 4)) % (a.frames || 1);
      const bob = s.single && Math.sin(t * 2.3) > .55 ? 1 : 0;
      l.drawImage(img, ((a.col || 0) + f) * s.frame_w, (a.row || 0) * s.frame_h, s.frame_w, s.frame_h,
        Math.round((W - s.frame_w) / 2), H - s.frame_h + bob, s.frame_w, s.frame_h);
    }
    ctx.imageSmoothingEnabled = false; ctx.clearRect(0, 0, cv.width, cv.height); ctx.drawImage(low, 0, 0, cv.width, cv.height);
    setTimeout(() => requestAnimationFrame(tick), 110);
  };
  tick();
}
async function chibiCard(box, c) {
  const { sheets } = await api('/api/pixel_sheets').catch(() => ({ sheets: [] }));
  const cur = c.pixel_sheet || '';
  const title = (s) => s.title ? s.title + (s.baked_from ? ' (из 3D)' : '') : s.name.startsWith('px_') ? 'из 3D-модели' : s.name;
  const tile = (s) => `<div class="char ${cur === s.name ? 'on' : ''}" data-px="${esc(s.name)}">
      <button class="ic xdel" data-pxdel="${esc(s.name)}" title="Удалить (в корзину)">${ICON('x', 'sm')}</button>
      <div class="pv"><canvas class="pxprev" data-sheet="${esc(s.name)}" width="96" style="image-rendering:pixelated;max-height:100%"></canvas></div>
      <b>${esc(title(s).slice(0, 24))}</b><small>${s.single ? 'своя картинка' : s.baked_from ? 'пиксели из 3D' : 'спрайт-лист'}</small></div>`;
  box.appendChild(h(`<div class="card"><h3>Пиксельный (чиби)</h3>
    <div class="sub">Когда ИИ не занят, компаньон становится маленьким пиксельным. Лиса Renard — встроенная, Savi — рисованный чиби своей 3D-модели
      (включается сам, когда выбран Savi), для других 3D-моделей пиксельная версия делается сама. Можно загрузить своего: любая картинка
      или анимированный GIF (большая картинка станет пиксельной). ✕ — убрать в корзину. Покадровый спрайт-лист — вкладка «Окно».</div>
    <div class="chars" style="margin-top:12px">
      <div class="char ${!cur ? 'on' : ''}" data-px=""><div class="pv"><canvas class="pxprev" data-char="fox" width="96" style="image-rendering:pixelated"></canvas></div><b>Лиса Renard</b><small>встроенная</small></div>
      <div class="char ${cur === '@savi' ? 'on' : ''}" data-px="@savi"><div class="pv"><canvas class="pxprev" data-char="savi" width="96" style="image-rendering:pixelated"></canvas></div><b>Savi</b><small>рисованный</small></div>
      ${sheets.map(tile).join('')}
      ${c.kind === 'vrm' && !BUILTIN_PX[c.file] ? `<div class="char" id="pxBake"><div class="pv">${ICON('sparkle')}</div><b>Сделать из 3D</b><small>пересобрать из «${esc(c.file.slice(0, 18))}»</small></div>` : ''}
      <label class="char" style="display:block"><div class="pv">${ICON('upload')}</div><b>Свой чиби</b><small>PNG / GIF / WebP</small>
        <input type="file" accept=".png,.gif,.webp,.jpg,.jpeg" hidden id="pxUp"></label>
    </div></div>`));
  box.querySelectorAll('canvas.pxprev').forEach(cv => pxPreview(cv, sheets));
  box.querySelectorAll('[data-px]').forEach(x => x.onclick = (e) => {
    if (e.target.closest('[data-pxdel]')) return;
    savePrefs({ companion: { pixel_sheet: x.dataset.px } }).then(paint);
  });
  box.querySelectorAll('[data-pxdel]').forEach(b => b.onclick = async (e) => {
    e.stopPropagation();
    if (!confirm(`Убрать пиксельного «${b.dataset.pxdel}» в корзину?`)) return;
    const r = await del('/api/pixel_sheets/' + encodeURIComponent(b.dataset.pxdel)).catch(e => ({ error: String(e) }));
    if (r && r.error) toast(r.error, 'err'); else toast('Убрал в корзину');
    paint();
  });
  box.querySelector('#pxUp').onchange = async (e) => {
    const f = e.target.files[0]; if (!f) return; toast('Делаю пиксельного из ' + f.name + '…');
    const r = await fetch('/api/pixel_sheets/upload?mode=single&name=' + encodeURIComponent(f.name), { method: 'POST', body: f }).then(r => r.json()).catch(e => ({ error: String(e) }));
    if (r.error) return toast(r.error, 'err');
    await savePrefs({ companion: { pixel_sheet: r.name } }); toast('Готово: теперь пиксельный — «' + (r.title || r.name) + '»'); paint();
  };
  const b = box.querySelector('#pxBake'); if (b) b.onclick = bakePixel;
}

const ANIMS = [['idle', 'стоит / по умолчанию'], ['sit', 'сидит'], ['sleep', 'спит'], ['wave', 'машет'], ['walk', 'несут / идёт']];
async function sheetCard(box, c) {
  const { sheets } = await api('/api/pixel_sheets').catch(() => ({ sheets: [] }));
  const cur = sheets.find(s => s.name === c.pixel_sheet);
  const card = h(`<div class="card"><h3>Пиксельный персонаж</h3>
    <div class="sub">Встроенный — нарисованный пиксельный Renard по твоей модели. Можно поставить свой спрайт-лист (PNG, кадры одинакового размера,
      каждая строка — анимация; например паки с itch.io). Высота кадра до ~36 px смотрится лучше всего.</div>
    <div class="row"><span class="lbl"><b>Персонаж</b></span><select class="txt" id="pxSheet" style="width:240px">
      <option value="">Renard (встроенный)</option>${sheets.map(s => `<option value="${esc(s.name)}" ${s.name === c.pixel_sheet ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select>
      <label class="chip" style="cursor:pointer">${ICON('upload', 'sm')} загрузить PNG<input type="file" accept=".png" hidden id="pxUp"></label></div>
    ${cur ? `<div class="row"><span class="lbl"><b>Кадр</b><small>ширина × высота, точка «сиденья» от верха кадра, кадров в секунду</small></span>
      <span><input class="txt" id="pxW" style="width:60px" value="${cur.frame_w}"> × <input class="txt" id="pxH" style="width:60px" value="${cur.frame_h}">
      сиденье <input class="txt" id="pxSeat" style="width:60px" value="${cur.seat ?? cur.frame_h}"> fps <input class="txt" id="pxFps" style="width:50px" value="${cur.fps || 6}"></span></div>
      ${ANIMS.map(([k, t]) => `<div class="row"><span class="lbl"><b>${t}</b><small>строка, кадров (пусто — не использовать)</small></span>
        <span><input class="txt" data-row="${k}" style="width:60px" placeholder="строка" value="${cur.anims?.[k]?.row ?? ''}"> <input class="txt" data-frames="${k}" style="width:60px" placeholder="кадров" value="${cur.anims?.[k]?.frames ?? ''}"></span></div>`).join('')}
      <div class="row"><span class="lbl"><b>Лист</b></span><img src="/avatars/pixel/${esc(cur.file)}?v=${cur.mtime}" style="max-width:420px;max-height:160px;image-rendering:pixelated;background:#3a6ea5;border-radius:8px"></div>
      <div class="row"><span></span><span><button class="btn" id="pxSave">Сохранить разметку</button> <a class="chip" target="_blank" href="/app/pixel_preview.html?s=1.6&sheet=${encodeURIComponent(cur.name)}">превью занятий</a></span></div>` : ''}
  </div>`);
  box.appendChild(card);
  box.querySelector('#pxSheet').onchange = (e) => savePrefs({ companion: { pixel_sheet: e.target.value } }).then(() => show(['window']));
  box.querySelector('#pxUp').onchange = async (e) => {
    const f = e.target.files[0]; if (!f) return;
    const r = await fetch('/api/pixel_sheets/upload?name=' + encodeURIComponent(f.name), { method: 'POST', body: f }).then(r => r.json());
    if (r.error) return toast(r.error, 'err');
    await savePrefs({ companion: { pixel_sheet: r.name } }); toast('Загрузил. Проверь размер кадра и строки анимаций'); show(['window']);
  };
  const save = box.querySelector('#pxSave');
  if (save) save.onclick = async () => {
    const num = (id) => +box.querySelector(id).value || 0, anims = {};
    for (const [k] of ANIMS) {
      const row = box.querySelector(`[data-row="${k}"]`).value, fr = box.querySelector(`[data-frames="${k}"]`).value;
      if (row !== '' && fr !== '') anims[k] = { row: +row, frames: +fr };
    }
    await post(`/api/pixel_sheets/${encodeURIComponent(cur.name)}/meta`, { frame_w: num('#pxW'), frame_h: num('#pxH'), seat: num('#pxSeat'), fps: num('#pxFps') || 6, anims });
    toast('Сохранил — компаньон обновится');
  };
}
