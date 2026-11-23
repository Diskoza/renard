import { api, post, esc, h, ICON, toast, prefs, savePrefs } from '../core.js';
import { speak, audioCtx } from '../chatview.js';

let root;
const row = (b, s, ctl) => `<div class="row"><span class="lbl"><b>${b}</b>${s ? `<small>${s}</small>` : ''}</span>${ctl}</div>`;
const tog = (on, id) => `<div class="tog ${on ? 'on' : ''}" id="${id}"></div>`;
const LANGS = { ru: 'русский', uk: 'украинский', pl: 'польский', en: 'английский' };

export async function mount(el) { root = el; el.classList.add('scrollpage'); await paint(); }
export function show() { paint(); }

async function paint() {
  const [v, cl] = await Promise.all([api('/api/voice/info'), api('/api/voice/clones').catch(() => ({ voices: [] }))]), p = v.prefs || {};
  const rate = Number(p.tts_rate || v.tts_rate || 1);
  const others = Object.entries(v.other_voices || {}).map(([l, n]) => `<span class="chip">${LANGS[l] || l}: ${esc(n.split('-')[1] || n)}</span>`).join(' ');
  root.innerHTML = '';
  root.appendChild(h(`<div style="display:flex;width:100%;overflow-y:auto">
    <nav class="subnav glass">${[['mic', 'Микрофон'], ['wake', 'Слово-активатор'], ['talk', 'Разговор'], ['tts', 'Генерация речи'], ['clone', 'Свои голоса'], ['ptt', 'Push to Talk'], ['stt', 'Распознавание']]
      .map(([k, t], i) => `<a href="#" data-s="${k}" class="${i ? '' : 'on'}">${t}</a>`).join('')}</nav>
    <div class="page-pad"><div class="narrow">
      <h1>Голос</h1>
      <div class="card" id="s-mic"><h3>${ICON('mic')} Микрофон</h3>
        ${row('Устройство ввода', 'Слово «Ренар» слушает микрофон по умолчанию в Windows', `<span class="sub">${esc(v.wake_device || v.mics[0] || 'не найден')}</span>`)}
        ${row('Как ты меня слышишь', 'Нажми и скажи фразу — покажу, что расслышал, громкость и язык', `<button class="btn" id="vHear">${ICON('mic')} Проверить слух</button>`)}
        <div id="vHearOut" class="sub" style="margin:6px 0 2px;white-space:pre-wrap"></div>
        ${row('Проверка голоса', 'Так Renard звучит сейчас', `<button class="btn" id="vTestTts">${ICON('wave')} Тест голоса</button>`)}</div>
      <div class="card" id="s-wake"><h3>${ICON('ear')} Слово-активатор «Ренар»</h3>
        ${row('Слушать «Ренар»', v.wake_available ? 'Распознавание прямо на ПК (Vosk), ~0.6% CPU в тишине. Звук никуда не отправляется.' : 'Не найдена модель Vosk или микрофон', tog(v.wake, 'vWake'))}
        ${row('Звук при активации', 'Короткий сигнал, когда слово распознано', tog(p.wake_beep !== false, 'vBeep'))}
        ${row('Чувствительность к «Ренар»', 'Высокая — отзывается почти всегда (99% в тесте), изредка на похожие слова. Обычная — реже ложные срабатывания, но пропускает ~6%. Максимальная — без второй проверки',
          `<select id="vSens">${[['normal', 'обычная — реже срабатывает зря'], ['high', 'высокая — рекомендуется'], ['low', 'максимальная — может срабатывать зря']].map(([v, t]) => `<option value="${v}" ${(p.wake_sensitivity || 'high') === v ? 'selected' : ''}>${t}</option>`).join('')}</select>`)}
        <div class="sub" style="margin-top:10px"><b>Последние «Ренар», которые он слышал</b> — если он не отозвался, здесь видно, что расслышал:</div>
        <div class="wake-log">${(v.wake_log || []).length ? v.wake_log.map(x => `<div>${x.ok ? '<span style="color:#7FB069">✓ отозвался</span>' : '<span style="color:#E0A458">✗ не уверен</span>'} <small>${esc(x.t)}</small> <span class="sub">${esc(x.heard)}</span></div>`).join('') : '<div class="sub">пока пусто — скажи «Ренар»</div>'}</div></div>
      <div class="card" id="s-talk"><h3>${ICON('talk')} Разговор</h3>
        ${row('Режим разговора', 'После «Ренар» слушает тебя всё время, без повторного «Ренар». Скажи «Ренар, засни» (или «хватит слушать»), и он будет ждать только слово «Ренар»', tog(p.conversation !== false, 'vConv'))}
        ${row('Заснуть, если тишина', 'Сколько молчать, чтобы он сам перестал слушать', `<select id="vConvS">${[[30, '30 с'], [60, '1 мин'], [120, '2 мин'], [300, '5 мин'], [900, '15 мин']].map(([s, t]) => `<option value="${s}" ${Number(p.conversation_idle_s || 120) === s ? 'selected' : ''}>${t}</option>`).join('')}</select>`)}
        ${row('Дослушивать фразу', 'Если фраза оборвалась на «и», «потому что», запятой — ждёт ещё 2,5 с, пока договоришь', '<span class="chip">всегда</span>')}
        ${row('Без режима разговора', 'Сколько секунд ждать продолжения после ответа', `<select id="vFollowS">${[4, 6, 8, 12, 20].map(s => `<option value="${s}" ${Number(p.followup_s || 6) === s ? 'selected' : ''}>${s} с</option>`).join('')}</select>`)}
        ${row('Перебивать словом «Ренар»', 'Скажи «Ренар», пока он говорит, — замолчит и выслушает. В наушниках работает лучше всего', tog(p.barge_in !== false, 'vBarge'))}
        ${row('Отвечать «Сейчас поищу»', 'Пока идёт поиск, взгляд на экран или проверка ПК — коротко говорит, что занялся делом, а не молчит', tog(p.voice_acks !== false, 'vAcks'))}</div>
      <div class="card" id="s-tts"><h3>${ICON('wave')} Генерация речи (TTS)</h3>
        ${row('Озвучивать ответы ИИ', 'Если выключено — голосом отвечает только на голосовые вопросы', tog(p.speak_answers, 'vSpeak'))}
        ${row('Скорость речи', '', `<select id="vRate">${[[0.9, 'медленнее'], [1, 'обычная'], [1.1, 'быстрее'], [1.2, 'быстро']].map(([r, t]) => `<option value="${r}" ${Math.abs(rate - r) < .01 ? 'selected' : ''}>${t}</option>`).join('')}</select>`)}
        ${row('Движок', 'Piper — локально, на процессоре, без интернета. Числа, единицы и английские названия он теперь произносит словами, эмодзи и разметку пропускает', `<span class="chip">${String(v.tts_voice || '').startsWith('clone:') ? 'свой голос · OmniVoice' : 'Piper · локальный'}</span>`)}
        ${others ? row('Другие языки', 'Если ответ на другом языке — читает этим голосом', others) : ''}
        ${row('Английские фразы — английским голосом', 'Названия песен, цитаты и английские предложения внутри русского ответа читает английский голос, а не русский с акцентом', tog(p.english_voice !== false, 'vEng'))}
        <div style="margin-top:10px" class="chars">${[...new Set([...v.voices, ...v.downloadable])].map(n => `<div class="char ${n === v.tts_voice ? 'on' : ''}" data-v="${esc(n)}">
          <b>${esc(n.replace('ru_RU-', '').replace('-medium', ''))}</b><small>${v.voices.includes(n) ? (n === v.tts_voice ? 'выбран' : 'установлен') : 'скачать (~60 МБ)'}</small></div>`).join('')}</div></div>
      <div class="card" id="s-clone"><h3>${ICON('mic')} Свои голоса</h3>
        <div class="sub" style="margin-bottom:8px">Клон голоса по 5–10 секундам речи: запиши свой голос или возьми звук из аудио- или видеофайла.
          Работает на этом ПК (OmniVoice, видеокарта ~2 ГБ, пока он говорит; во время игры — на процессоре, медленнее). Если свой голос не сможет говорить, ответит обычный голос.</div>
        ${cl.installed ? '' : '<div class="sub" style="color:#E0A458">Движок своих голосов не установлен (data/voiceclone).</div>'}
        <div class="chars">${(cl.voices || []).map(c => `<div class="char ${c.id === v.tts_voice ? 'on' : ''}" data-v="${esc(c.id)}">
          <b>${esc(c.name)}</b><small>${c.id === v.tts_voice ? 'выбран' : esc(({ mic: 'запись', file: 'файл', video: 'из видео' })[c.source] || c.source || '')}${c.seconds ? ' · ' + c.seconds + ' с' : ''}</small>
          <span class="char-acts"><button class="btn icon" data-play="${esc(c.name)}" title="Послушать образец">${ICON('play')}</button>
          <button class="btn icon" data-del="${esc(c.name)}" title="Удалить (в корзину)">${ICON('trash')}</button></span></div>`).join('') || '<div class="sub">пока нет своих голосов</div>'}</div>
        <div class="clone-new">
          ${row('Название', '', '<input id="cName" placeholder="например, мой голос" maxlength="40">')}
          ${row('Согласие', 'Это мой голос, или у меня есть разрешение владельца голоса', '<label class="chk"><input type="checkbox" id="cConsent"> да</label>')}
          ${row('Записать с микрофона', 'Прочитай вслух спокойно, 10 секунд: «Привет! Я проверяю, как звучит мой голос. Сегодня хороший день, и я никуда не спешу.»',
            `<button class="btn" id="cRec" ${cl.installed ? '' : 'disabled'}>${ICON('mic')} Записать</button>`)}
          ${row('Из аудио или видео', 'mp3, wav, m4a, ogg, mp4, mkv… Возьму самый «разговорный» кусок; можно указать, с какой секунды',
            `<input id="cStart" type="number" min="0" step="1" placeholder="с секунды" style="width:96px">
             <button class="btn" id="cFileBtn" ${cl.installed ? '' : 'disabled'}>${ICON('upload')} Выбрать файл</button>
             <input type="file" id="cFile" accept="audio/*,video/*" hidden>`)}
          <div id="cOut" class="sub" style="margin-top:6px;white-space:pre-wrap"></div></div></div>
      <div class="card" id="s-ptt"><h3>⌨ Push to Talk</h3>
        ${row('Ctrl + Alt + V', 'Открыть окно и начать говорить; закончишь фразу — отправится сам (или нажми ещё раз)', '<span class="chip">глобально</span>')}
        ${row('Ctrl + Alt + Space', 'Показать / скрыть окно Renard', '<span class="chip">глобально</span>')}
        ${row('Микрофон в поле ввода', 'Кнопка 🎤 в любом чате', '<span class="chip">в окне</span>')}</div>
      <div class="card" id="s-stt"><h3>${ICON('sparkle')} Распознавание (STT)</h3>
        ${row('Модель', 'faster-whisper на видеокарте; загружается при нажатии микрофона и выгружается через 5 минут тишины', `<span class="chip">${esc(v.stt_model)}</span>`)}
        ${row('Язык речи', 'Обычно русский; если уверенно слышит украинский, польский или английский — распознаёт на нём', tog(p.stt_auto_lang !== false, 'vAutoLang'))}
        ${row('Записи для настройки слуха', 'Хранит 20 последних голосовых команд в data/voice_debug (только на этом ПК), чтобы можно было разобрать, где он ослышался', tog((p.debug_keep ?? 20) > 0, 'vDebug'))}</div>
    </div></div></div>`));
  root.querySelectorAll('.subnav a').forEach(a => a.onclick = (e) => { e.preventDefault(); root.querySelectorAll('.subnav a').forEach(x => x.classList.toggle('on', x === a));
    root.querySelector('#s-' + a.dataset.s).scrollIntoView({ behavior: 'smooth', block: 'start' }); });
  root.querySelector('#vWake').onclick = async () => { await post('/api/wake/toggle'); paint(); };
  const setp = async (patch) => { await post('/api/voice/set', { prefs: patch }); await savePrefs({ voice: patch }); };
  const ptog = (id, key, val = (on) => on) => root.querySelector(id).onclick = async (e) => {
    const on = !e.target.classList.contains('on'); e.target.classList.toggle('on', on); await setp({ [key]: val(on) }); };
  ptog('#vBeep', 'wake_beep'); ptog('#vSpeak', 'speak_answers');
  root.querySelector('#vSens').onchange = (e) => setp({ wake_sensitivity: e.target.value });
  ptog('#vConv', 'conversation'); ptog('#vEng', 'english_voice'); ptog('#vBarge', 'barge_in'); ptog('#vAcks', 'voice_acks');
  root.querySelector('#vConvS').onchange = (e) => setp({ conversation_idle_s: Number(e.target.value) }); ptog('#vAutoLang', 'stt_auto_lang'); ptog('#vDebug', 'debug_keep', on => on ? 20 : 0);
  root.querySelector('#vFollowS').onchange = (e) => setp({ followup_s: Number(e.target.value) });
  root.querySelector('#vRate').onchange = async (e) => { await setp({ tts_rate: Number(e.target.value) }); speak('Вот так я теперь говорю.'); };
  root.querySelector('#vTestTts').onclick = () => speak('Привет! Я Ренар. Сейчас плюс двенадцать, ветер три метра в секунду — открыть Дискорд или включить музыку?');
  root.querySelector('#vHear').onclick = hearTest;
  root.querySelectorAll('[data-v]').forEach(c => c.onclick = async (e) => {
    if (e.target.closest('.char-acts')) return;
    const clone = c.dataset.v.startsWith('clone:');
    toast('Переключаю голос на ' + c.dataset.v.replace('clone:', '') + (clone ? '… (первый раз модель грузится ~10–40 с)' : '…'));
    const r = await post('/api/voice/set', { tts_voice: c.dataset.v });
    if (r && r.ok === false) { toast(r.error || 'не получилось'); return; }
    await paint(); speak('Теперь я говорю этим голосом.');
  });
  let sample;
  root.querySelectorAll('[data-play]').forEach(b => b.onclick = () => {
    sample?.pause(); sample = new Audio('/api/voice/clone/sample?name=' + encodeURIComponent(b.dataset.play)); sample.play(); });
  root.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
    if (!confirm(`Удалить голос «${b.dataset.del}»? Он уйдёт в корзину.`)) return;
    const r = await post('/api/voice/clone/delete', { name: b.dataset.del }); toast(r.ok ? 'Удалён (в корзине)' : (r.error || r.text || 'не получилось')); paint(); });
  const out = root.querySelector('#cOut');
  const ready = () => {
    if (!root.querySelector('#cConsent').checked) { out.textContent = 'Отметь согласие: это твой голос или у тебя есть разрешение владельца.'; return false; }
    return true;
  };
  const upload = async (blob, source) => {
    const name = root.querySelector('#cName').value.trim() || (source === 'mic' ? 'мой голос' : 'новый голос');
    const start = Number(root.querySelector('#cStart').value || 0);
    out.textContent = 'Готовлю образец: вырезаю речь, распознаю текст…';
    const q = new URLSearchParams({ name, source, consent: 1, start });
    let r;
    try { r = await (await fetch('/api/voice/clone/add?' + q, { method: 'POST', body: blob })).json(); }
    catch (e) { r = { ok: false, error: String(e) }; }
    if (!r.ok) { out.textContent = '✗ ' + (r.error || 'не получилось'); return; }
    out.textContent = `✓ Голос «${r.name}» сохранён (${r.seconds} с)${r.text ? `\nВ образце: «${r.text}»` : ''}\nНажми на него выше, чтобы Renard говорил им.`;
    await paint(); root.querySelector('#s-clone').scrollIntoView({ block: 'start' });
  };
  root.querySelector('#cFileBtn').onclick = () => { if (ready()) root.querySelector('#cFile').click(); };
  root.querySelector('#cFile').onchange = (e) => { const f = e.target.files[0]; if (f) upload(f, /^video\//.test(f.type) ? 'video' : 'file'); };
  root.querySelector('#cRec').onclick = async (e) => {
    const btn = e.currentTarget;
    if (btn.dataset.busy || !ready()) return; btn.dataset.busy = '1';
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
      const rec = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' }), chunks = [];
      rec.ondataavailable = ev => chunks.push(ev.data);
      const done = new Promise(r => rec.onstop = r);
      rec.start();
      for (let s = 10; s > 0; s--) { out.textContent = `🎙 Читай текст вслух… ${s}`; await new Promise(r => setTimeout(r, 1000)); }
      rec.stop(); await done; stream.getTracks().forEach(t => t.stop());
      await upload(new Blob(chunks, { type: 'audio/webm' }), 'mic');
    } catch (err) { out.textContent = 'Нет доступа к микрофону: ' + err; }
    delete btn.dataset.busy;
  };
  bakeCard();
}

const READ_TEXT = [
  'Привет! Меня зовут так-то, и сейчас я записываю свой голос для помощника. Я говорю спокойно, чётко и с обычной интонацией.',
  'Сегодня двенадцатое ноября. На улице плюс три градуса, небольшой ветер. Вечером, возможно, пойдёт дождь.',
  'Открой браузер и найди расписание поездов до Варшавы. Потом включи музыку и сделай громкость шестьдесят процентов.',
  'Съешь же ещё этих мягких французских булок, да выпей чаю. В чащах юга жил бы цитрус? Да, но фальшивый экземпляр!',
  'Шла Саша по шоссе и сосала сушку. Цапля чахла, цапля сохла. Жужжит жужелица, жужжит, да не кружится.',
  'Один, два, три, четыре, пять, шесть, семь, восемь, девять, десять. Понедельник, вторник, среда, четверг, пятница.',
  'Как дела? Что нового? Отлично, спасибо! Нет, я не уверен. Давай попробуем ещё раз. Готово, всё работает.',
  'Расскажи что-нибудь своими словами: про школу, про игру, про то, что ты сегодня делал — минуту или две, как обычно говоришь.',
];
let bakeTimer = null;
async function bakeCard() {
  const anchor = root.querySelector('#s-clone'); if (!anchor) return;
  root.querySelector('#s-bake')?.remove();
  const b = await api('/api/voicebake').catch(() => null); if (!b) return;
  const STAGE = { new: 'файлы загружены', prepare: '1/4 режу запись на фразы', augment: '2/4 ИИ досинтезирует фразы', separate: '3/4 отделяю голос от музыки', train: '3/4 обучение', export: '4/4 сборка', check: '4/4 проверка голоса', done: 'готово', error: 'ошибка' };
  const ok = b.ready.venv && b.ready.base && b.ready.ffmpeg;
  const card = h(`<div class="card" id="s-bake"><h3>🔥 Запечь полноценный голос</h3>
    <div class="sub" style="margin-bottom:8px">Длинная запись твоего голоса (лучше 5–20 минут, можно несколько файлов) → Renard режет её на фразы и распознаёт текст →
      ИИ голосом-клоном досинтезирует недостающие звуки и фразы (каждую проверяет и кривые выбрасывает) → на видеокарте обучается настоящий голос Piper.
      Долго один раз (~40–90 минут, во время игры ставится на паузу), зато потом голос работает мгновенно и ровно, как 4 встроенных.</div>
    ${ok ? '' : `<div class="sub" style="color:#E0A458">Не готово: ${!b.ready.venv ? 'движок (data/voiceclone) ' : ''}${!b.ready.base ? 'базовая модель ' : ''}${!b.ready.ffmpeg ? 'ffmpeg' : ''}</div>`}
    <div class="bake-jobs">${b.jobs.map(j => `<div class="row"><span class="lbl"><b>${esc(j.name || j.slug)}</b><small>${esc(STAGE[j.stage] || j.stage || '')}${j.note ? ' — ' + esc(j.note) : ''}${j.error ? '<br><span style="color:#E07A6A">' + esc(j.error.slice(0, 300)) + '</span>' : ''}
        ${j.real_seconds ? `<br>твоей речи: ${Math.round(j.real_seconds / 60 * 10) / 10} мин (${j.phrases} фраз)` : ''}${j.synthetic ? ` · ИИ добавил: ${j.synthetic} фраз (${Math.round(j.synthetic_seconds / 60 * 10) / 10} мин), отброшено ${j.rejected || 0}` : ''}${j.quality ? `<br>в обучение взято ${j.quality.kept} фраз; отброшено: ${Object.entries(j.quality.rejected || {}).filter(e => e[1]).map(e => esc(e[0]) + ' ' + e[1]).join(', ') || 'ничего'}${j.separated ? ' · голос отделён от музыки' : ''}` : ''}${j.check && j.check.score != null ? `<br>понятность (Whisper): <b>${j.check.score}/100</b>${j.check.score < 85 ? ' — голос звучит неровно' : ''}${j.check.worst ? ' · ' + esc(j.check.worst) : ''}` : ''}</small>
        ${['prepare', 'augment', 'separate', 'train', 'export', 'check'].includes(j.stage) && b.running ? `<div class="bar"><i style="width:${j.pct || 0}%"></i></div>` : ''}</span>
        ${j.stage === 'done' ? `<button class="btn ok" data-bv="${esc(j.voice)}">Выбрать голос</button>` + (!b.running ? `<button class="btn" data-breb="${esc(j.name)}" title="${b.can_separate ? 'отделить голос от музыки, отобрать чистые фразы и обучить заново' : 'отобрать чистые фразы и обучить заново'}">Переобучить чище</button>` : '')
          : b.running === j.name ? `<button class="btn" data-bcancel>Остановить</button>`
          : ['error', 'prepare', 'augment', 'separate', 'train', 'export', 'check'].includes(j.stage) ? `<button class="btn" data-bres="${esc(j.name)}">Продолжить</button>` : ''}</div>`).join('')}</div>
    <div class="clone-new">
      ${row('Название', 'Станет голосом в списке', '<input id="bName" placeholder="например, мой голос" maxlength="30">')}
      ${row('Согласие', 'Это мой голос, или у меня есть разрешение владельца голоса', '<label class="chk"><input type="checkbox" id="bConsent"> да</label>')}
      ${row('Файлы', 'Аудио или видео с твоей речью: mp3, wav, m4a, ogg, mp4… без музыки на фоне', `<button class="btn" id="bFileBtn" ${ok ? '' : 'disabled'}>${ICON('upload')} Добавить файлы</button><input type="file" id="bFile" accept="audio/*,video/*" multiple hidden>`)}
      ${row('Или записать', 'Читай тексты ниже вслух, сколько хочется (хотя бы 3–5 минут), потом «Стоп»', `<button class="btn" id="bRec" ${ok ? '' : 'disabled'}>${ICON('mic')} Записывать</button>`)}
      <div class="bake-read" id="bRead" hidden>${READ_TEXT.map((t, i) => `<p><b>${i + 1}.</b> ${esc(t)}</p>`).join('')}</div>
      ${row('Сколько речи для обучения', 'Если твоей записи меньше, ИИ досинтезирует до этого объёма', '<select id="bMin" class="txt" style="width:190px;flex:none"><option value="15">15 мин — быстрее</option><option value="25" selected>25 мин</option><option value="40">40 мин — лучше</option></select>')}
      <div class="row"><button class="btn primary" id="bStart" ${ok && !b.running ? '' : 'disabled'}>🔥 Запечь голос</button><span class="sub" id="bOut" style="white-space:pre-wrap"></span></div></div></div>`);
  anchor.after(card);
  const out = card.querySelector('#bOut');
  const name = () => card.querySelector('#bName').value.trim() || 'мой голос';
  const consent = () => { if (card.querySelector('#bConsent').checked) return true; out.textContent = 'Отметь согласие.'; return false; };
  const send = async (blob, fn) => {
    out.textContent = `Загружаю ${fn} (${Math.round(blob.size / 1e5) / 10} МБ)…`;
    const r = await (await fetch(`/api/voicebake/upload?name=${encodeURIComponent(name())}&fn=${encodeURIComponent(fn)}`, { method: 'POST', body: blob })).json().catch(e => ({ ok: false, error: String(e) }));
    out.textContent = r.ok ? `✓ Загружено файлов: ${r.files.length} (${r.mb} МБ). Можно добавить ещё или жать «Запечь голос».` : '✗ ' + (r.error || 'не получилось');
  };
  card.querySelector('#bFileBtn').onclick = () => { if (consent()) card.querySelector('#bFile').click(); };
  card.querySelector('#bFile').onchange = async (e) => { for (const f of e.target.files) await send(f, f.name); };
  let rec = null;
  card.querySelector('#bRec').onclick = async (e) => {
    const btn = e.currentTarget;
    if (rec) { rec.stop(); return; }
    if (!consent()) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
      rec = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus', audioBitsPerSecond: 128000 }); const chunks = [], t0 = Date.now();
      rec.ondataavailable = ev => chunks.push(ev.data);
      card.querySelector('#bRead').hidden = false;
      const tick = setInterval(() => { const s = Math.round((Date.now() - t0) / 1000); btn.innerHTML = `⏹ Стоп · ${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }, 500);
      rec.onstop = async () => { clearInterval(tick); stream.getTracks().forEach(t => t.stop()); rec = null; btn.innerHTML = `${ICON('mic')} Записывать ещё`;
        await send(new Blob(chunks, { type: 'audio/webm' }), `rec_${Date.now()}.webm`); };
      rec.start(1000);
    } catch (err) { out.textContent = 'Нет доступа к микрофону: ' + err; rec = null; }
  };
  card.querySelector('#bStart').onclick = async () => {
    if (!consent()) return;
    const r = await post('/api/voicebake/start', { name: name(), consent: true, minutes: +card.querySelector('#bMin').value });
    if (!r.ok) { out.textContent = '✗ ' + (r.error || 'не получилось'); return; }
    toast('Запекаю голос — это долго, можно заниматься своими делами'); bakeCard();
  };
  card.querySelectorAll('[data-breb]').forEach(x => x.onclick = async () => { const r = await post('/api/voicebake/rebake', { name: x.dataset.breb }); if (!r.ok) toast(r.error || 'не получилось', 'err'); else toast('Переобучаю голос: ~40–90 минут, прогресс здесь'); bakeCard(); });
  card.querySelectorAll('[data-bres]').forEach(x => x.onclick = async () => { const r = await post('/api/voicebake/start', { name: x.dataset.bres, resume: true }); if (!r.ok) toast(r.error || 'не получилось', 'err'); bakeCard(); });
  card.querySelector('[data-bcancel]')?.addEventListener('click', async () => { await post('/api/voicebake/cancel'); toast('Останавливаю…'); setTimeout(bakeCard, 1500); });
  card.querySelectorAll('[data-bv]').forEach(x => x.onclick = async () => { await post('/api/voice/set', { tts_voice: x.dataset.bv }); await paint(); speak('Теперь я говорю твоим запечённым голосом.'); });
  clearTimeout(bakeTimer);
  if (b.running) bakeTimer = setTimeout(() => { if (root.isConnected && root.querySelector('#s-bake') && !rec) bakeCard(); }, 5000);
}

async function hearTest() {
  const out = root.querySelector('#vHearOut'), btn = root.querySelector('#vHear');
  if (btn.dataset.busy) return; btn.dataset.busy = '1';
  try {
    fetch('/api/voice/warmup', { method: 'POST' });
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
    const rec = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' }), chunks = [];
    const an = audioCtx().createAnalyser(); an.fftSize = 1024; audioCtx().createMediaStreamSource(stream).connect(an);
    const buf = new Float32Array(an.fftSize); let peak = 0;
    rec.ondataavailable = e => chunks.push(e.data);
    const done = new Promise(r => rec.onstop = r);
    rec.start(); out.textContent = '🎙 Говори… (5 секунд)';
    const t0 = performance.now();
    while (performance.now() - t0 < 5000) {
      an.getFloatTimeDomainData(buf); for (const x of buf) peak = Math.max(peak, Math.abs(x));
      out.textContent = '🎙 Говори… ' + '▮'.repeat(Math.round(peak * 30)).padEnd(30, '▯');
      await new Promise(r => setTimeout(r, 100));
    }
    rec.stop(); await done; stream.getTracks().forEach(t => t.stop());
    out.textContent = 'Распознаю…';
    const j = await (await fetch('/api/voice/hear_test', { method: 'POST', body: new Blob(chunks, { type: 'audio/webm' }) })).json();
    const lvl = peak < 0.02 ? '⚠ почти тишина — проверь, не выключен ли микрофон на гарнитуре' : peak < 0.08 ? 'тихо, но я усилил' : 'хорошо';
    out.textContent = (j.text ? `Расслышал: «${j.text}»` : `Ничего не расслышал${j.error ? ' (' + j.error + ')' : ''}`) +
      `\nГромкость: ${lvl}${j.gain ? ` · усиление ×${j.gain}` : ''} · язык: ${LANGS[j.lang] || j.lang || '—'}${j.lang_p ? ` (${Math.round(j.lang_p * 100)}%)` : ''}` +
      ` · ${((j.ms || 0) / 1000).toFixed(1)} с${j.load_ms > 500 ? ` (из них загрузка модели ${(j.load_ms / 1000).toFixed(1)} с)` : ''}`;
  } catch (e) { out.textContent = 'Нет доступа к микрофону: ' + e; }
  delete btn.dataset.busy;
}
