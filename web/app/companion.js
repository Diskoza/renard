import { loadPrefs, connect, on, state, savePrefs, api } from '/app/core.js';
import { renderAvatar, companionCfg, ACTIONS, EMOTIONS } from '/app/avatar.js';
import { PixelScene, ACTIVITIES, loadSheet } from '/app/pixel.js';

await loadPrefs();
const stage = document.getElementById('stage'), bubble = document.getElementById('bubble'), menu = document.getElementById('menu');
const px = document.getElementById('px');
const cfg = () => companionCfg();
const ctl = renderAvatar(stage, { view: 'desktop' });
const scene = new PixelScene(px, { size: cfg().pixel_size || 1 });
ctl.requestMode = m => setMode(m);
window.nxBody = cfg().body || 'male';
window.nx = ctl; window.nxScene = scene; window.nxState = state;
const useSheet = async () => {
  const n = cfg().pixel_sheet || '';
  scene.char = n.startsWith('@') ? n.slice(1) : 'fox';
  scene.sheet = n && !n.startsWith('@') ? await loadSheet(n).catch(() => null) : null;
  try { if (pixel) sendAnchor(); } catch {  }
};
useSheet();
const body = await new Promise(res => {
  if (window.pywebview?.api?.geom) return res(window.pywebview.api);
  let n = 0; const iv = setInterval(() => { if (window.pywebview?.api?.geom) { clearInterval(iv); res(window.pywebview.api); } else if (++n > 30) { clearInterval(iv); res(null); } }, 100);
});
const B = (fn, ...a) => body && body[fn] ? body[fn](...a).catch?.(() => null) : Promise.resolve(null);

const now = () => performance.now() / 1000;
const wait = (ms) => new Promise(r => setTimeout(r, ms));
let lastTouch = now(), nextIdle = now() + 8, sitUntil = 0, pixel = false, actUntil = 0, userAct = false, placedAt = -1e9, mediaOn = false;

function sendAnchor(m = ctl.mode) {
  if (pixel) B('set_anchor', px.offsetTop + scene.anchorY(), px.offsetLeft + scene.anchorX(), scene.margin());
  else B('set_anchor', ctl.anchor(m), innerWidth / 2, 95);
}
addEventListener('resize', () => setTimeout(() => sendAnchor(), 80));
function setMode(m) {
  ctl.setMode(m);
  document.body.dataset.mode = m;
  if (!pixel) setTimeout(() => sendAnchor(m), 60);
}

function chooseActivity(force) {
  const c = cfg(), place = scene.place, h = new Date().getHours(), t = now();
  if (userAct && !force && t < actUntil) return;
  userAct = false;
  let pool;
  if (c.activities === false) pool = ['sit'];
  else if (mediaOn) pool = ['music'];
  else if ((h >= 1 && h < 7) || t - lastTouch > 1800) pool = ['sleep'];
  else pool = Object.keys(ACTIVITIES).filter(a => a !== 'sleep' && ACTIVITIES[a].places.includes(place) && a !== scene.activity);
  scene.setActivity(pool[Math.floor(Math.random() * pool.length)] || 'sit');
  actUntil = t + (scene.activity === 'sit' ? 60 : 150) + Math.random() * 180;
}
async function enterPixel(force = false) {
  if (pixel || (cfg().idle_pixel === false && !force)) return;
  pixel = true; hideMenu(); bubble.classList.remove('on');
  document.body.classList.add('pixel');
  scene.held = false; scene.puff();
  const g = await B('geom');
  const pref = cfg().perch || 'auto';
  if (now() - placedAt < 300 && g) {
    scene.setPlace(g.perch === 'window' ? 'window' : 'corner'); sendAnchor();
  } else {
    scene.setPlace(pref === 'window' ? 'window' : 'corner'); sendAnchor();
    const r = await B('perch', pref);
    if (r) { scene.setPlace(r.kind === 'window' ? 'window' : 'corner'); sendAnchor(); }
  }
  chooseActivity(true);
}
async function exitPixel() {
  if (!pixel || now() < holdPixel) return;
  pixel = false;
  document.body.classList.remove('pixel');
  setMode('stand'); ctl.face(0); sendAnchor('stand');
  const g = await B('geom');
  if (g && g.perch === 'window' && g.room < 360) B('perch', 'corner');
}
let pxLast = performance.now(), pxDrawn = 0;
(function pxLoop(t) {
  requestAnimationFrame(pxLoop);
  if (!pixel) { pxLast = t; return; }
  if (t - pxDrawn < 66) return;
  scene.update((t - pxLast) / 1000); pxLast = t; pxDrawn = t;
  scene.render();
  if (bubble.classList.contains('on')) bubble.style.top = Math.max(4, px.offsetTop + scene.charTop() - bubble.offsetHeight - 6) + 'px';
})(pxLast);
setInterval(async () => {
  if (!pixel) return;
  try { const m = await api('/api/widgets/media'); const on2 = !!m.playing; if (on2 !== mediaOn) { mediaOn = on2; if (!userAct) chooseActivity(true); } } catch {}
}, 15000);

let jumpAfterWalk = 0;
window.nxArrived = () => {
  if (ctl.mode === 'walk') { setMode('stand'); ctl.face(0); }
  if (jumpAfterWalk) { const d = jumpAfterWalk; jumpAfterWalk = 0; ctl.face(d); jumpDown(d); }
};
async function jumpDown(d) {
  ctl.act('jump'); await wait(220);
  if (await B('jump_down', d)) { ctl.gesture = null; setMode('fall'); }
}
window.nxDrag = (vx) => { ctl.dragVx = vx; };
window.nxWobble = (vx, vy) => {
  if (pixel) return;
  ctl.wobble = Math.max(-.3, Math.min(.3, -vx / 2600)); ctl.wobbleT = now();
  if (Math.hypot(vx, vy) > 1100 && !ctl.gesture && ctl.mode !== 'sit') ctl.act('balance');
};
window.nxKnocked = (why) => {
  lastTouch = now();
  if (pixel) { scene.held = true; return; }
  ctl.gesture = null; setMode('fall');
  say({ shake: ['Эй! Не тряси 😵', 'Аааа!', 'Землетрясение!'], fast: ['Воу-воу!', 'Куда так быстро?!'],
        gone: ['Ой, окно пропало!', 'Эээ… а где пол?'] }[why]?.[Math.floor(Math.random() * 2)] || 'Ой!', 2600);
};
window.nxDropped = () => { if (pixel) scene.held = false; else setMode('fall'); };
window.nxHop = (kind) => { if (pixel) { scene.setPlace(kind === 'window' ? 'window' : 'corner'); sendAnchor(); } };
window.nxLanded = (v, kind) => {
  if (v > 0) placedAt = now();
  if (pixel) {
    scene.held = false; scene.setPlace(kind === 'window' ? 'window' : 'corner'); sendAnchor();
    if (v > 1400) { scene.setMood('happy', 2); say(['Ой!', 'Уф!', 'Мягкая посадка 😅'][Math.floor(Math.random() * 3)], 2200); }
    return;
  }
  setMode('stand'); ctl.face(0);
  if (v > 1400) { ctl.emote('surprised', 2); say(['Ой!', 'Уф, приземлился', 'Аккуратнее 😅'][Math.floor(Math.random() * 3)], 2500); }
};
async function walk(where, speed = 160) {
  ctl.gesture = null;
  if (ctl.mode === 'sleep' || ctl.mode === 'sit') { setMode('stand'); await wait(500); }
  const r = await B('walk_to', where, speed);
  if (r && r.dir) { ctl.walkSpeed = speed; ctl.face(r.dir); setMode('walk'); }
}

let hideT;
function say(text, ms = 6000) {
  if (cfg().bubbles === false || !text) return;
  bubble.textContent = text.length > 200 ? text.slice(0, 197) + '…' : text;
  bubble.style.top = pixel ? Math.max(4, px.offsetTop + scene.charTop() - 60) + 'px' : '6px';
  const cx = pixel ? px.offsetLeft + scene.anchorX() : innerWidth / 2;
  bubble.style.left = Math.max(8, Math.min(innerWidth - bubble.offsetWidth - 8, cx - bubble.offsetWidth / 2)) + 'px';
  bubble.classList.add('on'); clearTimeout(hideT); hideT = setTimeout(() => bubble.classList.remove('on'), ms);
}

const ALIASES = { hello: 'wave', hi: 'wave', greet: 'wave', yes: 'nod', no: 'shake', joy: 'celebrate', yawn: 'stretch' };
let holdPixel = 0;
async function command(ev) {
  lastTouch = now();
  const a = ALIASES[ev.action] || ev.action || '';
  if (a === 'pixel' || ev.activity || ev.place) {
    holdPixel = now() + 6;
    if (!pixel) await enterPixel(true);
    if (ev.place) { const r = await B('perch', ev.place); if (r) { scene.setPlace(r.kind === 'window' ? 'window' : 'corner'); sendAnchor(); } }
    if (ev.activity && ACTIVITIES[ev.activity]) {
      if (!ACTIVITIES[ev.activity].places.includes(scene.place)) { const r = await B('perch', 'corner'); if (r) { scene.setPlace('corner'); sendAnchor(); } }
      scene.setActivity(ev.activity); userAct = true; actUntil = now() + 900;
    }
    if (ev.say) say(ev.say);
    return;
  }
  if (a === 'big') { holdPixel = 0; return exitPixel(); }
  if (pixel) { holdPixel = 0; await exitPixel(); await wait(250); }
  const ANIM_EMO = { Laughing: 'happy', Crying: 'sad', 'Sad Idle': 'sad', Angry: 'angry', 'Angry Gesture': 'angry', Victory: 'happy',
    Surprised: 'surprised', Cheering: 'happy', 'Blow A Kiss': 'happy', Terrified: 'surprised', Defeated: 'sad', Disappointed: 'sad' };
  const ACT_EMO = { celebrate: 'happy', jump: 'happy', wave: 'happy', clap: 'happy', dance: 'happy', shy: 'happy' };
  if (ev.face && ctl.showFace) ctl.showFace(ev.face, ev.seconds || 6);
  if (ev.red !== undefined && ctl.setRed) ctl.setRed(ev.red);
  if (ev.emotion && EMOTIONS.includes(ev.emotion)) ctl.emote(ev.emotion, ev.seconds || 6);
  else if (ev.anim || a) ctl.emote(ANIM_EMO[ev.anim] || ACT_EMO[a] || 'neutral', 6);
  if (ev.say) say(ev.say);
  if (ev.anim && ctl.anim) {
    if (ctl.mode === 'walk') await B('stop');
    if (ctl.mode !== 'stand') { setMode('stand'); await wait(300); }
    ctl.anim(ev.anim, { seconds: ev.seconds || 25 }).catch(e => console.warn('anim', e));
    if (!a) return;
  }
  if (!a) return;
  if (a === 'sit') { await B('stop'); if (ctl.gesture?.name === 'dance') ctl.gesture = null; setMode('sit'); sitUntil = now() + 90; ctl.face(0); }
  else if (a === 'stand' || a === 'wake') { ctl.clips?.stop?.(.4); setMode('stand'); ctl.face(0); }
  else if (a === 'sleep') { await B('stop'); ctl.gesture = null; setMode('sleep'); }
  else if (a === 'walk_left') walk('left');
  else if (a === 'walk_right') walk('right');
  else if (a === 'walk' || a === 'wander') walk('random');
  else if (a === 'come') walk('cursor', 210);
  else if (a === 'center') walk('center', 190);
  else if (a === 'jump_down') { const g = await B('geom'); if (g?.perch === 'window') jumpDown(g.rel < g.win_w / 2 ? -1 : 1); }
  else if (a === 'climb') { const r = await B('perch', 'window'); if (r?.kind === 'window') ctl.act('jump'); }
  else if (a === 'stop') { await B('stop'); ctl.clips?.stop?.(.4); ctl.gesture = null; setMode('stand'); ctl.face(0); }
  else if (ACTIONS[a]) {
    if (ctl.mode === 'walk') { await B('stop'); setMode('stand'); }
    if ((ctl.mode === 'sit' || ctl.mode === 'sleep') && !['wave', 'nod', 'shake', 'think', 'clap', 'point', 'brush', 'catch'].includes(a)) { setMode('stand'); await wait(450); }
    ctl.act(a, { style: ev.style, dur: ev.seconds, user: true });
  }
}
on('avatar', command);

const EMO_BODY = [[/😂|🤣|😆/, ['happy', 'anim:Laughing']], [/😭|😢|🥲/, ['sad', 'anim:Crying']], [/😔|😞|😟|☹|🙁/, ['sad', null]],
  [/😊|🙂|😄|😁|😃|☺/, ['happy', 'nod']], [/🧐|🤔/, [null, 'think']], [/😳|😮|😲|😯/, ['surprised', null]], [/😡|😠|🤬/, ['angry', null]],
  [/🤸|🦘|⬆/, ['happy', 'jump']], [/👋/, ['happy', 'wave']], [/💃|🕺/, ['happy', 'dance']], [/👏/, ['happy', 'clap']], [/🙇/, [null, 'bow']],
  [/🤷/, [null, 'shrug']], [/😴|💤/, ['relaxed', null]], [/😘/, ['happy', 'anim:Blow A Kiss']], [/🎉|🥳/, ['happy', 'celebrate']]];
function moodOf(text) {
  const s = text.toLowerCase();
  if (s.replace(/[\s\u200d\ufe0f]/g, '').length <= 6 && !/[a-zа-яё0-9]/i.test(s)) {
    for (const [rx, r] of EMO_BODY) if (rx.test(s)) return r;
  }
  if (/(погиб|убит|убил|смерт|умер|теракт|трагед|соболезн|катастроф|жертв|раненых|похорон|война|болезн|печальн|грустн|тяжел|депресс)/.test(s)) return ['sad', null];
  if (/(ошибк|не удалось|не получилось|к сожалению|не могу|не нашёл|не нашел|не найден)/.test(s)) return ['sad', null];
  if (/^(привет|здравствуй|добр(ое|ый) (утро|день|вечер)|хай)/.test(s)) return ['happy', 'wave'];
  if (/(ура|поздравля|отлично|супер|получилось|готово|рад(а)? помочь|😊|🙂|😄|🎉)/.test(s)) return ['happy', Math.random() < .3 ? 'nod' : null];
  if (/(внимание|осторожн|опасн|⚠|предупрежд)/.test(s)) return ['surprised', null];
  if (/\?\s*$/.test(s)) return [null, Math.random() < .5 ? 'think' : null];
  return [null, null];
}
let lvT = performance.now();
(function decay(t) { requestAnimationFrame(decay); state.level *= Math.pow(.12, (t - lvT) / 1000); lvT = t; })(lvT);
let speechEnd = 0;
if ('BroadcastChannel' in window) new BroadcastChannel('nx-speech').onmessage = ({ data: d }) => {
  if (d.done) { speechEnd = setTimeout(() => { if (state.orb === 'speaking') state.orb = 'idle'; }, 500); return; }
  clearTimeout(speechEnd);
  if (state.orb !== 'speaking') { state.orb = 'speaking'; lastTouch = now(); if (pixel) exitPixel(); }
  state.level = Math.max(state.level, d.level || 0);
};
on('activity', (ev) => {
  if (ev.level != null) state.level = Math.max(state.level, ev.level);
  if (ev.state) {
    state.orb = ev.state;
    if (ev.state === 'listening' || ev.state === 'thinking' || ev.state === 'speaking') {
      lastTouch = now();
      if (pixel) exitPixel();
      if (ctl.mode === 'walk') B('stop').then(() => { setMode('stand'); ctl.face(0); });
      if (ctl.mode === 'sleep') { setMode('stand'); ctl.emote('surprised', 1.5); }
    }
  }
  if (ev.state || ev.role) state.lastTalk = performance.now();
  if (ev.role === 'user' && ev.text) { lastTouch = now(); if (pixel) exitPixel(); say('🎙 ' + ev.text, 4000); }
  if (ev.role === 'assistant' && ev.text) {
    lastTouch = now(); if (pixel) exitPixel();
    setTimeout(() => {
      say(ev.text.slice(0, 220));
      const [emo, act] = moodOf(ev.text);
      if (emo) ctl.emote(emo, emo === 'sad' ? 12 : 5);
      if (act?.startsWith('anim:')) ctl.anim?.(act.slice(5)).catch(() => {});
      else if (act && !ctl.gesture) ctl.act(act, { user: /^\W+$/.test(ev.text.trim()) });
    }, pixel ? 300 : 0);
  }
});
let musicSince = 0, danceNext = 0, gearT = 0, quietSince = 0, neckUntil = 0;
const ears = () => (ctl.autoAcc || []).find(a => ['headphones', 'earbuds', 'headphones_neck'].includes(a));
const freeFor = () => state.orb === 'idle' && !ctl.gesture && ['stand', 'sit'].includes(ctl.mode) && !menu.classList.contains('on')
  && !(ctl.clips?.playing?.() && !ctl.clips.playing().auto);
async function gearUp() {
  let last = ''; try { last = localStorage.getItem('nxGear') || ''; } catch { }
  const style = cfg().music_gear && cfg().music_gear !== 'random' ? cfg().music_gear : (last === 'headphones' ? 'earbuds' : 'headphones');
  try { localStorage.setItem('nxGear', style); } catch { }
  if (pixel || !freeFor()) { ctl.autoAcc = [style]; return; }
  const act = ears() === 'headphones_neck' || style === 'headphones' ? 'puton' : 'earbuds';
  ctl.act(act);
  setTimeout(() => { ctl.autoAcc = [act === 'puton' ? 'headphones' : 'earbuds']; }, ACTIONS[act] * 1000 * (act === 'puton' ? .55 : .5));
  await wait(ACTIONS[act] * 1000 + 200);
  listen();
}
function listen() {
  if (pixel || !freeFor() || !ctl.clips || ctl.mode !== 'stand') return;
  ctl.listen = true; ctl.listenT = now();
  ctl.clips.playOneOf(['Listening To Music', 'Hip Hop Just Listening'], { auto: true, loop: true, skip: ['head', 'neck'], tag: 'listen' }).catch(() => {});
}
function stopListen() {
  ctl.listen = false;
  if (ctl.clips?.playing?.()?.tag === 'listen') ctl.clips.stop(.6);
}
on('beat', async (ev) => {
  const t = now(), c = cfg();
  if (!ev.bpm) {
    ctl.bpm = 0; musicSince = 0; stopListen();
    const e = ears();
    if (e === 'headphones' && !pixel && freeFor()) {
      ctl.act('neckoff'); setTimeout(() => { ctl.autoAcc = ['headphones_neck']; }, ACTIONS.neckoff * 1000 * .7);
      neckUntil = t + 90 + Math.random() * 120;
    } else if (e === 'earbuds' && !pixel && freeFor()) {
      ctl.act('earbuds'); setTimeout(() => { ctl.autoAcc = []; }, ACTIONS.earbuds * 1000 * .55);
    } else if (e === 'headphones') { ctl.autoAcc = ['headphones_neck']; neckUntil = t + 120; }
    else if (e !== 'headphones_neck') ctl.autoAcc = [];
    return;
  }
  ctl.bpm = ev.bpm; ctl.lastBeat = t;
  if (!musicSince) musicSince = t;
  if (c.auto_headphones !== false && t - musicSince > 3 && !['headphones', 'earbuds'].includes(ears()) && t - gearT > 20) {
    gearT = t; gearUp(); return;
  }
  if (!ctl.listen && t - gearT > 6 && ['headphones', 'earbuds'].includes(ears()) && freeFor() && !ctl.clips?.playing?.()) listen();
  if (c.dance_music === false || t < danceNext || t - musicSince < 20 || ev.conf < .35 || !freeFor()) return;
  danceNext = t + 180 + Math.random() * 120;
  if (pixel) { holdPixel = 0; await exitPixel(); await wait(400); }
  if (ctl.mode !== 'stand') { setMode('stand'); await wait(450); }
  ctl.listen = false;
  const dur = 18 + Math.random() * 12;
  const ok = ctl.clips ? await ctl.clips.playDance(ev.bpm, { auto: true, seconds: dur, tag: 'dance' }).catch(() => false) : false;
  if (!ok) ctl.act('dance', { dur });
  if (Math.random() < .5) say(['О, моя песня!', 'Под это нельзя не двигаться', 'Качает!'][Math.floor(Math.random() * 3)], 2500);
  setTimeout(() => { if (ctl.bpm) listen(); }, dur * 1000 + 800);
});
setInterval(() => {
  if (ears() === 'headphones_neck' && neckUntil && now() > neckUntil && !ctl.bpm) { ctl.autoAcc = []; neckUntil = 0; }
}, 5000);
let wx = { kind: null }, wxSince = 0, wxNext = 0;
if ('BroadcastChannel' in window) new BroadcastChannel('nx-weather').onmessage = async ({ data: w }) => {
  const t = now(), c = cfg();
  if (w.kind !== wx.kind) {
    wxSince = t; wxNext = t + 6;
    if (w.kind === 'snow' && !pixel && c.bubbles !== false) say(['О, снег! ❄', 'Снег пошёл ☃', 'Зима пришла ❄'][Math.floor(Math.random() * 3)], 3500);
    if (w.kind === 'rain' && !pixel && Math.random() < .5) say('Дождь… 🌧', 2500);
  }
  wx = w;
  ctl.weatherAcc = c.weather_dress === false ? [] : w.kind === 'snow' || (w.cold && w.temp <= 0) ? ['beanie', 'scarf'] : [];
  if (!w.kind || t < wxNext || pixel || state.orb !== 'idle' || ctl.gesture || ctl.mode !== 'stand' || menu.classList.contains('on')) return;
  wxNext = t + 35 + Math.random() * 60;
  const a = w.kind === 'snow' ? (t - wxSince > 120 && Math.random() < .3 ? 'brush' : Math.random() < .75 ? 'catch' : 'shiver') : 'shiver';
  ctl.act(a);
  if (a === 'catch' && Math.random() < .35) setTimeout(() => say(['Поймал ❄', 'Тает на ладони…', 'Каждая снежинка разная!'][Math.floor(Math.random() * 3)], 2500), 1200);
};
on('notice', async (ev) => {
  if (cfg().remarks === false) return;
  say(ev.text, 6000);
  if (pixel) { scene.wave(2); scene.setMood(ev.emotion === 'happy' ? 'happy' : 'calm', 3); return; }
  if (ctl.mode === 'sleep') { setMode('stand'); await wait(500); }
  if (ev.emotion) ctl.emote(ev.emotion, 4);
  if (ev.action && !ctl.gesture) { if (ctl.mode === 'sit' && !['wave', 'nod'].includes(ev.action)) { setMode('stand'); await wait(450); } ctl.act(ev.action); }
});
on('task', (ev) => {
  say('⏰ ' + ev.name + ': ' + ev.text.slice(0, 160), 9000);
  if (pixel) { scene.wave(3); scene.setMood('happy', 3); } else { ctl.act('wave'); ctl.emote('surprised', 2); lastTouch = now(); }
});
on('alert', (ev) => { say('⚠ ' + (ev.text || ''), 8000); if (!pixel) ctl.emote('surprised', 3); });
const lookKey = () => { const c = cfg(); return [c.kind, c.file, c.scale, c.outline, c.msaa, c.size, c.flip2d, c.pixel_size].join('|'); };
on('prefs', async (p) => {
  if (!p || p.type !== 'prefs') return;
  const old = lookKey(), oldPx = cfg().idle_pixel, oldPerch = cfg().perch; await loadPrefs();
  if (lookKey() !== old) return location.reload();
  ctl.apply(); useSheet();
  if (cfg().idle_pixel === false && oldPx !== false && pixel) exitPixel();
  if (pixel && cfg().perch !== oldPerch) { const r = await B('perch', cfg().perch || 'auto'); if (r) { scene.setPlace(r.kind === 'window' ? 'window' : 'corner'); sendAnchor(); } }
  if (pixel && cfg().activities === false) chooseActivity(true);
});
connect();

setInterval(async () => {
  const t = now(), c = cfg();
  if (ctl.mode === 'drag' || ctl.mode === 'fall' || window.nxNoAuto) return;
  if (pixel) { if (t > actUntil) chooseActivity(); return; }
  if (c.idle_pixel !== false && state.orb === 'idle' && t - lastTouch > (c.pixel_after || 25) && ctl.mode !== 'walk'
      && !bubble.classList.contains('on') && !ctl.gesture && !menu.classList.contains('on')) { enterPixel(); return; }
  if (c.idle_pixel === false && c.sleep !== false && t - lastTouch > (c.sleep_after || 300) && ctl.mode !== 'sleep' && ctl.mode !== 'walk' && state.orb === 'idle') {
    await B('stop'); setMode('sleep'); say('💤', 3000); return;
  }
  if (t < nextIdle || c.walk !== true || ctl.mode === 'sleep' || state.orb !== 'idle') return;
  if (ctl.mode === 'sit' && t < sitUntil) { nextIdle = t + 10; return; }
  const r = Math.random();
  if (ctl.mode === 'walk') { nextIdle = t + 3; return; }
  const g = await B('geom');
  if (g?.perch === 'window' && r < .08) {
    const left = g.rel < g.win_w / 2;
    const w = await B('walk_to', left ? 'edge_left' : 'edge_right', 150);
    if (w?.dir) { ctl.walkSpeed = 150; ctl.face(w.dir); setMode('walk'); jumpAfterWalk = left ? -1 : 1; }
    nextIdle = t + 25; return;
  }
  if (r < .38) { walk('random', 130 + Math.random() * 70); nextIdle = t + 18 + Math.random() * 25; }
  else if (r < .62) { setMode('sit'); ctl.face(0); sitUntil = t + 25 + Math.random() * 50; nextIdle = sitUntil; }
  else if (r < .72) { if (ctl.mode !== 'stand') setMode('stand'); ctl.act('stretch'); nextIdle = t + 12 + Math.random() * 20; }
  else { if (ctl.mode === 'sit') setMode('stand'); ctl.face(0); nextIdle = t + 10 + Math.random() * 20; }
}, 1000);

const hov = { since: 0, xs: [], lastPlay: 0 };
setInterval(async () => {
  if (!body) return;
  const p = await B('cursor'); if (!p) return;
  if (!pixel && cfg().look !== false) {
    const hx = innerWidth / 2, hy = innerHeight * .25;
    ctl.look(Math.tanh((p.x - hx) / 500), Math.tanh(-(p.y - hy) / 400));
  }
  const b = pixel ? (() => { const r = scene.bounds(); return [px.offsetLeft + r[0], px.offsetTop + r[1], r[2], r[3]]; })() : ctl.bounds?.();
  const t = now(), over = b && p.x > b[0] && p.x < b[0] + b[2] && p.y > b[1] && p.y < b[1] + b[3];
  if (!over || down || ctl.mode === 'drag') { hov.since = 0; hov.xs = []; return; }
  if (!hov.since) hov.since = t;
  hov.xs = [...hov.xs.filter(q => t - q[0] < 1.2), [t, p.x]];
  const flips = hov.xs.slice(2).filter((q, i) => Math.sign(q[1] - hov.xs[i + 1][1]) !== Math.sign(hov.xs[i + 1][1] - hov.xs[i][1])).length;
  if (t - hov.lastPlay < 8 || state.orb !== 'idle') return;
  if (flips >= 4) {
    hov.lastPlay = t; lastTouch = t; say(['Хи-хи, щекотно! 😆', 'Эй, щекотно!', 'Ха-ха, хватит 😄'][Math.floor(Math.random() * 3)], 2500);
    if (pixel) { scene.setMood('happy', 2.5); scene.wave(1); } else { ctl.emote('happy', 3); ctl.act(ctl.mode === 'sit' ? 'nod' : 'jump'); }
  } else if (t - hov.since > 1.6) {
    hov.lastPlay = t; hov.since = t + 30;
    if (pixel) scene.wave(1.5); else if (!ctl.gesture) { ctl.act('wave'); ctl.emote('happy', 2); }
  }
}, 120);

let down = null;
for (const el of [stage, px]) {
  el.addEventListener('pointerdown', (e) => { if (e.button === 0) down = { x: e.clientX, y: e.clientY, t: now(), dragging: false }; });
  el.addEventListener('pointermove', (e) => {
    if (!down || down.dragging) return;
    if (Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5 && body) {
      down.dragging = true; lastTouch = now(); hideMenu();
      if (pixel) scene.held = true; else setMode('drag');
      B('drag_start', down.x, down.y);
    }
  });
  el.addEventListener('pointerup', () => { if (down && !down.dragging) click(); down = null; });
  el.addEventListener('contextmenu', (e) => { e.preventDefault(); openMenu(e); });
}
let clicks = 0, clickT;
function click() {
  hideMenu();
  if (++clicks === 2) { clearTimeout(clickT); clicks = 0; B('open_main'); if (!pixel) ctl.act('nod'); return; }
  clickT = setTimeout(() => {
    clicks = 0;
    if (pixel) {
      if (scene.activity === 'sleep') { scene.setActivity('sit'); say('А? Я не спал 😳', 2200); }
      else { scene.wave(1.6); scene.setMood('happy', 2); }
      return;
    }
    lastTouch = now();
    if (ctl.mode === 'sleep') { setMode('stand'); ctl.emote('surprised', 1.5); say('А? Я не спал 😳', 2500); return; }
    const pick = [['wave', 'happy', 'Привет! Двойной клик — открою Renard'], ['jump', 'happy', 'Хоп!'], ['nod', 'relaxed', 'Я тут 🙂'],
      ['clap', 'happy', ''], ['shrug', null, 'Чем займёмся?']][Math.floor(Math.random() * 5)];
    if (ctl.mode === 'sit' && pick[0] === 'jump') setMode('stand');
    ctl.act(pick[0]); if (pick[1]) ctl.emote(pick[1], 3); if (pick[2]) say(pick[2], 3500);
  }, 260);
}
function openMenu(e) {
  const items = [['open', 'Открыть Renard'], ['mic', '🎙 Сказать голосом']];
  if (pixel) {
    for (const [k, a] of Object.entries(ACTIVITIES)) items.push(['act:' + k, (scene.activity === k ? '● ' : '') + a.ru[0].toUpperCase() + a.ru.slice(1)]);
    items.push(['perch:corner', 'Сесть в угол у часов'], ['perch:window', 'Сесть на окно'], ['perch:auto', 'Сам выбирает место'], ['big', 'Стать большим (3D)']);
  } else {
    const sitting = ctl.mode === 'sit' || ctl.mode === 'sleep';
    items.push([sitting ? 'stand' : 'sit', sitting ? 'Встать' : 'Сесть на панель'], ['walk', 'Прогуляться'], ['dance', 'Потанцевать'], ['small', 'Стать пиксельным']);
  }
  items.push(['hide', 'Убрать с рабочего стола']);
  menu.innerHTML = items.map(([k, t]) => `<button data-k="${k}">${t}</button>`).join('');
  menu.style.gridTemplateColumns = ''; menu.classList.remove('compact');
  menu.classList.add('on');
  if (menu.offsetHeight > innerHeight - 8) menu.classList.add('compact');
  if (menu.offsetHeight > innerHeight - 8) menu.style.gridTemplateColumns = 'max-content max-content';
  const mw = menu.offsetWidth, mh = menu.offsetHeight;
  menu.style.left = Math.max(4, Math.min(innerWidth - mw - 4, e.clientX - mw / 2)) + 'px';
  menu.style.top = Math.max(4, Math.min(innerHeight - mh - 4, e.clientY - mh - 8)) + 'px';
}
menu.addEventListener('click', async (e) => {
  const k = e.target.dataset?.k; if (!k) return; hideMenu();
  if (k === 'open') B('open_main');
  else if (k === 'mic') B('mic');
  else if (k === 'hide') savePrefs({ companion: { desktop: false } });
  else if (k === 'big') { lastTouch = now(); exitPixel(); }
  else if (k === 'small') enterPixel();
  else if (k.startsWith('act:')) {
    const a = k.slice(4);
    if (!ACTIVITIES[a].places.includes(scene.place)) { const r = await B('perch', 'corner'); if (r) { scene.setPlace('corner'); sendAnchor(); } }
    scene.setActivity(a); userAct = true; actUntil = now() + 900;
  } else if (k.startsWith('perch:')) {
    const where = k.slice(6); placedAt = -1e9;
    savePrefs({ companion: { perch: where } });
  } else command({ action: k });
});
function hideMenu() { menu.classList.remove('on'); }
window.nxCloseMenu = hideMenu;
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideMenu(); });
document.addEventListener('pointerdown', (e) => { if (!menu.contains(e.target)) hideMenu(); }, true);

let lastRegion = '';
setInterval(() => {
  if (!body) return;
  const rects = [];
  if (pixel) { const b = scene.bounds(); rects.push([px.offsetLeft + b[0] - 3, px.offsetTop + b[1] - 3, b[2] + 6, b[3] + 6]); }
  else { const b = ctl.bounds && ctl.bounds(); if (b) rects.push(b); }
  for (const el of [bubble, menu]) if (el.classList.contains('on')) { const r = el.getBoundingClientRect(); rects.push([r.left - 4, r.top - 4, r.width + 8, r.height + 8]); }
  const key = rects.map(r => r.map(v => Math.round(v / 4)).join(',')).join(';');
  const mOn = menu.classList.contains('on');
  if (key + mOn !== lastRegion) { lastRegion = key + mOn; B('region', rects.map(r => r.map(Math.round)), mOn); }
}, 150);

setInterval(() => {
  const c = stage.querySelector('canvas'), pl = ctl.clips?.playing?.();
  B('debug', JSON.stringify({ pixel, mode: ctl.mode, canvas: c ? [c.width, c.height, c.clientWidth, c.clientHeight] : null,
    inner: [innerWidth, innerHeight], dpr: devicePixelRatio, clip: pl ? pl.name : null, upper: !!pl?.upper, gesture: ctl.gesture?.name || null,
    emotion: ctl.emotion || null, bounds: ctl.bounds?.() || null, anchorCss: ctl.anchor?.(ctl.mode), menu: menu.classList.contains('on'), bpm: ctl.bpm || 0, acc: ctl.autoAcc || [], listen: !!ctl.listen, orb: state.orb }));
}, 1000);

setMode('stand');
setTimeout(() => { setMode('stand'); ctl.act('wave'); ctl.emote('happy', 3); }, 1500);
window.nxCommand = command; window.nxPixel = (on2) => on2 ? enterPixel() : exitPixel();
