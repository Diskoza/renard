import { CPAL, CPARTS, CHIBI, FOX } from './pixel_chibi.js';

export const PAL = {
  k: '#1b1c24', h: '#3a4150', H: '#5d6880', d: '#272c37',
  s: '#f5d9ca', S: '#e0b3a1', c: '#f2a49a', e: '#2f4266', w: '#ffffff', m: '#a8584f',
  g: '#76747f', G: '#5a5863', L: '#9593a0', r: '#c42a35', R: '#861c25',
  p: '#24242c', P: '#373742', b: '#6c6f79', B: '#474951',
  y: '#ffd84d', o: '#ff8a2a', f: '#e2431d', n: '#7a4e2b', N: '#4e3019', q: '#7d7e86', Q: '#56575e',
  T: '#8a6a4a', t: '#6b4f35', a: '#3c6e71', A: '#2a4d50', l: '#5a9194', v: '#9be08f', V: '#5fa35a', z: '#c9d6ff',
};

const M = (half) => half + [...half].reverse().join('');
const sprite = (rows, name) => {
  const w = Math.max(...rows.map(r => r.length));
  rows.forEach((r, i) => { if (r.length !== w) console.warn('pixel sprite', name, 'row', i, 'len', r.length, '!=', w); });
  return { w, h: rows.length, rows };
};
const patch = (spr, x, y, str) => {
  const rows = spr.rows.slice();
  rows[y] = rows[y].slice(0, x) + str + rows[y].slice(x + str.length);
  return { ...spr, rows };
};

const HEAD_ROWS = [
  '........k..k........',
  '......kkhkkhkk......',
  '....kkhhhhhhhhhkk...',
  '...khhhHHhhhhhhhhk..',
  '..khhHHhhhhhhhhhhhk.',
  '.khhHhhhhhhhhhhhhhk.',
  'khhhhhhhhhhhhhhhhhhk',
  'khhhhhhhhhhhhhhhhhhk',
  '.khhhdhhhhhhdhhhdhk.',
  '.khhshhhhsshhhhshhk.',
  '.khssshsssssshssshk.',
  '.khs' + 'wee' + 'ssssss' + 'wee' + 'shk.',
  '.khs' + 'eee' + 'ssssss' + 'eee' + 'shk.',
  M('.khscsssss'),
  '..kSssss' + 's' + 'mm' + 's' + 'ssssSk..',
  M('....kkSSSS'),
];
const HEAD = sprite(HEAD_ROWS, 'head');
export const HEADS = {
  open: HEAD,
  blink: patch(patch(HEAD, 0, 11, M('.khsssssss')), 0, 12, '.khs' + 'kkk' + 'ssssss' + 'kkk' + 'shk.'),
  happy: patch(patch(HEAD, 0, 11, '.khs' + 'sks' + 'ssssss' + 'sks' + 'shk.'), 0, 12, '.khs' + 'kSk' + 'ssssss' + 'kSk' + 'shk.'),
  left: patch(patch(HEAD, 0, 11, '.khs' + 'ews' + 'ssssss' + 'ews' + 'shk.'), 0, 12, '.khs' + 'ees' + 'ssssss' + 'ees' + 'shk.'),
  sleep: patch(patch(patch(HEAD, 0, 11, M('.khsssssss')), 0, 12, '.khs' + 'kkk' + 'ssssss' + 'kkk' + 'shk.'), 0, 14, '..kSsssssmssssssSk..'),
};

let TORSO_REST = sprite([
  M('...kggGkrr'), M('..kgggggGr'), M('.kgGLggggG'), M('.kgGLggggG'), M('.kgGgggggG'),
  M('.kssGggggg'), M('..kGGGGGGG'),
], 'torso');
for (const [x, y] of [[8, 2], [11, 2], [8, 3], [11, 3]]) TORSO_REST = patch(TORSO_REST, x, y, 'w');
export const TORSOS = {
  rest: TORSO_REST,
  hold: patch(patch(TORSO_REST, 0, 5, M('.kgGgggGss')), 0, 4, M('.kgGgggggg')),
  wave: patch(patch(patch(patch(TORSO_REST, 16, 5, 'Gk..'), 17, 2, 'k.'), 17, 3, 'k.'), 17, 4, 'k.'),
};
const ARM_TAIL = ['..kggk', '..kggk', '..kggk', '..kggk', '.kggk.', '.kggk.', 'kggk..', 'kGk...', 'kGk...'];
const ARM_UP = [sprite(['...ss.', '..ssss', '..ssss', '..kssk', ...ARM_TAIL], 'arm'),
                sprite(['....ss', '...sss', '..ssss', '..kssk', ...ARM_TAIL], 'arm2')];
const THIGHS = sprite([M('...kpppppk')], 'thighs');
const CROSS = sprite([M('..kppppppp'), M('.kbbpppPpp'), M('.kBbkkkkkk')], 'cross');
const LEG = sprite(['.kpppk', '.kpppk', 'kbbbbk', 'kBBBBk', '.kkkk.'], 'leg');
const STAND_LEGS = sprite([M('...kpppppk'), M('...kpppPk.'), M('...kpppPk.'), M('...kpppPk.'), M('..kbbbbbk.'),
  M('..kBBBBBk.'), M('...kkkkk..')], 'standlegs');
const HEADPHONES = sprite([
  M('.....kkkkk'), M('....kRRRRR'), M('...kR.....'), M('..kR......'), M('..kR......'), M('..kR......'),
  M('..kR......'), M('..kR......'), M('.kRk......'), M('kRRk......'), M('kRrk......'), M('kRRk......'), M('.kk.......'),
], 'phones');

export const PROPS = {
  gamepad: sprite(['.kkkkkk.', 'kBbBBrBk', '.kk..kk.'], 'gamepad'),
  handheld: sprite(['kkkkkk', 'kvvvvk', 'kvVvvk', 'kvvvvk', 'kbbbbk', 'krbbok', 'kkkkkk'], 'handheld'),
  fire: [
    ['......y......', '.....yoy.....', '....yoooy....', '...fooyoof...', '...foyyyof...', '....fyyyf....'],
    ['.....y.......', '.....oy..y...', '....yooyoo...', '...fooyyof...', '..ffoyyyoff..', '....fyyyf....'],
    ['.......y.....', '...y..yo.....', '...ooyooy....', '...foyyoof...', '...foyyyof...', '....fyyyf....'],
  ].map((f, i) => sprite(f.concat(['..NnnN.NnnN..', '.qNnnnnnnnNq.', 'qqQkkkkkkkQqq']), 'fire' + i)),
  tv: sprite(['...k......k.....', '....k....k......', '.....k..k.......', '.kkkkkkkkkkkkkk.', 'kTTTTTTTTTTTTTTk',
    'kTkkkkkkkkkkTTTk', 'kTk........kToTk', 'kTk........kTTTk', 'kTk........kToTk', 'kTk........kTTTk',
    'kTkkkkkkkkkkTTTk', 'kTTTTTTTTTTTTTTk', '.kkkkkkkkkkkkkk.', '..kk........kk..'], 'tv'),
  console: sprite(['kkkkkk', 'kBBBrk', 'kkkkkk'], 'console'),
  sofa: sprite([
    '....' + 'k'.repeat(20) + '....',
    ...Array(5).fill('...kl' + 'a'.repeat(19) + 'k...'),
    '.kkk' + 'A'.repeat(20) + 'kkk.', 'kllk' + 'A'.repeat(20) + 'kllk', 'klak' + 'l'.repeat(20) + 'kalk',
    'klak' + 'a'.repeat(20) + 'kalk', 'kAAk' + 'k'.repeat(20) + 'kAAk', 'k' + 'A'.repeat(26) + 'k', '.kk' + '.'.repeat(22) + 'kk.'], 'sofa'),
  note: sprite(['..ww', '..w.', '..w.', 'www.', 'ww..'], 'note'),
  z: sprite(['zzzz', '..z.', '.z..', 'zzzz'], 'z'),
};

let BB = null;
export function draw(ctx, spr, x, y, flip = false) {
  if (BB) { BB[0] = Math.min(BB[0], x); BB[1] = Math.min(BB[1], y); BB[2] = Math.max(BB[2], x + spr.w); BB[3] = Math.max(BB[3], y + spr.h); }
  for (let j = 0; j < spr.h; j++) {
    const row = spr.rows[j];
    for (let i = 0; i < row.length; i++) {
      const ch = row[i]; if (ch === '.' || ch === ' ') continue;
      ctx.fillStyle = PAL[ch] || ch; ctx.fillRect(Math.round(x + (flip ? spr.w - 1 - i : i)), Math.round(y + j), 1, 1);
    }
  }
}

export const SEAT = CHIBI.SEAT;
const CW = CHIBI.W;
function part(ctx, rows, x, y, flip = false) {
  const w = rows[0].length;
  if (BB) { BB[0] = Math.min(BB[0], x); BB[1] = Math.min(BB[1], y); BB[2] = Math.max(BB[2], x + w); BB[3] = Math.max(BB[3], y + rows.length); }
  for (let j = 0; j < rows.length; j++) {
    const row = rows[j];
    for (let i = 0; i < row.length; i++) {
      const ch = row[i]; if (ch === '.') continue;
      ctx.fillStyle = CPAL[ch]; ctx.fillRect(Math.round(x + (flip ? w - 1 - i : i)), Math.round(y + j), 1, 1);
    }
  }
}
const HEAD_OF = { open: 'open', blink: 'blink', happy: 'happy', left: 'left', sleep: 'sleep', wide: 'wide', talk: 'talk', grin: 'grin' };
function drawSavi(ctx, x, y, o = {}) {
  const pose = o.pose || 'sit', t = o.t || 0;
  const breath = o.breath ?? (Math.sin(t * 2.3) > .55 ? 1 : 0);
  const up = y + (pose === 'sleep' ? 1 : 0) + breath;
  if (pose === 'stand') part(ctx, CPARTS.legs_stand, x, y + 35);
  else if (pose === 'cross') part(ctx, CPARTS.cross, x, y + 35);
  else {
    const swing = o.swing ? Math.sin(t * 3.2) : 0;
    part(ctx, CPARTS.shin, x + 9, y + 36 - (swing > .3 ? 1 : 0));
    part(ctx, CPARTS.shin, x + 15, y + 36 - (swing < -.3 ? 1 : 0), true);
    part(ctx, CPARTS.thighs, x, y + 35);
  }
  part(ctx, CPARTS['torso_' + (o.torso || 'rest')], x, up + 25);
  const hy = up + (o.bob || 0);
  part(ctx, CPARTS['head_' + (HEAD_OF[o.head] || 'open')], x, hy);
  if (o.phones) part(ctx, CPARTS.phones, x, hy + 3);
  if (o.torso === 'wave') part(ctx, CPARTS['arm_up' + (Math.abs(Math.floor(t * 4)) % 2)], x + 20, up + 15);
}

function drawFox(ctx, x, y, o = {}) {
  const t = o.t || 0;
  if (o.pose === 'sleep') { part(ctx, CPARTS.fox_curl, x + 2, y + 12 + (Math.sin(t * 1.5) > .3 ? 0 : 0)); return; }
  const breath = o.breath ?? (Math.sin(t * 2.3) > .55 ? 1 : 0);
  const wag = o.wag ?? (Math.sin(t * (o.happy ? 9 : 2.6)) > .35 ? 1 : Math.sin(t * (o.happy ? 9 : 2.6)) < -.35 ? 2 : 0);
  if (o.pose === 'sit') part(ctx, CPARTS['fox_hang' + (Math.sin(t * 1.7) > 0 ? 0 : 1)], x + 17, y + 24);
  else part(ctx, CPARTS['fox_tail' + wag], x + 17, y + 12);
  part(ctx, CPARTS['fox_body_' + (o.torso || 'rest')], x, y + 14);
  const hy = y + breath + (o.bob || 0);
  part(ctx, CPARTS['fox_head_' + (HEAD_OF[o.head] || 'open')], x, hy);
  if (o.phones) part(ctx, CPARTS.fox_phones, x, hy + 3);
  if (o.torso === 'wave') part(ctx, CPARTS.fox_paw_up, x + 22, hy + 5 - (Math.floor(t * 4) % 2));
}
export const CHARS = {
  fox: { W: FOX.W, sit: FOX.SEAT, floor: FOX.SEAT, stand: FOX.SEAT, floorPose: 'floor', pad: [7, 21], hh: [8, 17], cable: [11, 22], z: [20, 4], note: 4, puff: 18, draw: drawFox },
  savi: { W: CHIBI.W, sit: CHIBI.SEAT, floor: 39, stand: CHIBI.STAND_H, floorPose: 'cross', pad: [10, 32], hh: [11, 29], cable: [12, 34], z: [22, 2], note: 8, puff: 22, draw: drawSavi },
};
export function drawChar(ctx, x, y, o = {}) { (CHARS[o.char] || CHARS.fox).draw(ctx, x, y, o); }

export const ACTIVITIES = {
  sit: { ru: 'просто сидит', places: ['corner', 'window'] },
  music: { ru: 'слушает музыку', places: ['corner', 'window'] },
  handheld: { ru: 'играет в портативку', places: ['corner', 'window'] },
  console: { ru: 'играет в приставку', places: ['corner'] },
  tv: { ru: 'смотрит мультики на диване', places: ['corner'] },
  campfire: { ru: 'греется у костра', places: ['corner'] },
  sleep: { ru: 'спит', places: ['corner', 'window'] },
};

export async function loadSheet(name) {
  const meta = await fetch('/api/pixel_sheets/' + encodeURIComponent(name)).then(r => r.json());
  if (!meta || meta.error) return null;
  const img = new Image(); img.src = '/avatars/pixel/' + encodeURIComponent(meta.file) + '?v=' + (meta.mtime || 0);
  await img.decode();
  footLines(meta, img);
  return { ...meta, img };
}
export function footLines(meta, img) {
  try {
    const cv = document.createElement('canvas'); cv.width = img.naturalWidth; cv.height = img.naturalHeight;
    const g = cv.getContext('2d', { willReadFrequently: true }); g.drawImage(img, 0, 0);
    for (const a of Object.values(meta.anims || {})) {
      const x0 = (a.col || 0) * meta.frame_w, y0 = (a.row || 0) * meta.frame_h;
      const d = g.getImageData(x0, y0, meta.frame_w, meta.frame_h).data;
      let bottom = -1;
      for (let y = meta.frame_h - 1; y >= 0 && bottom < 0; y--)
        for (let x = 0; x < meta.frame_w; x++) if (d[(y * meta.frame_w + x) * 4 + 3] > 40) { bottom = y; break; }
      if (bottom >= 0) a.foot = bottom + 1;
    }
  } catch {  }
}
function drawSheet(ctx, sh, anim, t, x, seatY, flip, floor = false) {
  const pick = (...n) => n.map(k => sh.anims?.[k]).find(a => a && a.frames > 0);
  const a = pick(anim, anim === 'sleep' ? 'sit' : 'idle', 'idle', 'sit') || { row: 0, frames: 1 };
  const fw = sh.frame_w, fh = sh.frame_h, f = Math.floor(t * (a.fps || sh.fps || 6)) % a.frames;
  const seat = floor ? (a.foot ?? sh.seat ?? fh) : (a.seat ?? sh.seat ?? fh), dx = Math.round(x - fw / 2);
  let dy = Math.round(seatY - seat);
  if (sh.single) {
    if (anim === 'wave' || anim === 'walk') dy -= Math.abs(Math.sin(t * 7)) > .5 ? 2 : 0;
    else if (anim !== 'sleep') dy += Math.sin(t * 2.3) > .55 ? 1 : 0;
  }
  if (BB) { BB[0] = Math.min(BB[0], dx); BB[1] = Math.min(BB[1], dy); BB[2] = Math.max(BB[2], dx + fw); BB[3] = Math.max(BB[3], dy + fh); }
  ctx.save();
  if (flip) { ctx.translate(dx * 2 + fw, 0); ctx.scale(-1, 1); }
  ctx.drawImage(sh.img, ((a.col || 0) + f) * fw, a.row * fh, fw, fh, dx, dy, fw, fh);
  ctx.restore();
  return { top: dy };
}

export class PixelScene {
  constructor(canvas, { size = 1 } = {}) {
    this.cv = canvas; this.SW = 86; this.SH = 72; this.FY = 50;
    this.low = document.createElement('canvas'); this.low.width = this.SW; this.low.height = this.SH;
    this.ctx = this.low.getContext('2d');
    this.activity = 'sit'; this.place = 'corner'; this.t = 0; this.parts = []; this.blinkT = 2.5; this.blink = 0;
    this.mood = null; this.moodUntil = 0; this.quirk = null; this.quirkUntil = 0; this.char = 'fox'; this.waveUntil = 0; this.lookT = 0; this.spawnT = 0; this.screen = 0; this.screenT = 0;
    this.bb = [0, 0, 0, 0];
    this.resize(size);
  }
  resize(size = 1) {
    const dpr = window.devicePixelRatio || 1;
    this.P = Math.max(2, Math.round(2.7 * dpr * size));
    this.dpr = dpr;
    this.cv.width = this.SW * this.P; this.cv.height = this.SH * this.P;
    this.cv.style.width = this.SW * this.P / dpr + 'px'; this.cv.style.height = this.SH * this.P / dpr + 'px';
  }
  setActivity(a) { if (ACTIVITIES[a] && a !== this.activity) { this.activity = a; this.parts = this.parts.filter(p => p.type === 'puff'); } }
  setPlace(p) { this.place = p; if (!ACTIVITIES[this.activity].places.includes(p)) this.activity = 'sit'; }
  wave(sec = 1.8) { this.waveUntil = this.t + sec; }
  setMood(m, sec = 3) { this.mood = m; this.moodUntil = this.t + sec; }
  puff() {
    const { cx, cy } = this.layout();
    for (let i = 0; i < 18; i++) {
      const a = Math.random() * Math.PI * 2, v = 6 + Math.random() * 14;
      this.parts.push({ type: 'puff', x: cx + this.width() / 2, y: cy + this.geo().puff, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 4, life: 0, max: .5 + Math.random() * .4 });
    }
  }
  geo() { return CHARS[this.char] || CHARS.fox; }
  width() { return this.sheet ? this.sheet.frame_w : this.geo().W; }
  layout() {
    const a = this.activity, FY = this.FY, G = this.geo(), W = this.width();
    const cx = this.place === 'window' ? Math.round((this.SW - W) / 2) : this.SW - W - 5;
    let cy = FY - G.sit, pose = 'sit';
    if (a === 'tv' && !this.sheet) { cy = FY - 4 - G.sit; pose = 'sofa'; }
    else if (this.place !== 'window') { cy = FY - G.floor; pose = G.floorPose; }
    return { cx, cy, FY, pose, W };
  }
  anchorY() { return this.FY * this.P / this.dpr; }
  margin() { return Math.max(46, (this.width() / 2 + 4) * this.P / this.dpr); }
  anchorX() { const { cx, W } = this.layout(); return (cx + W / 2) * this.P / this.dpr; }
  bounds() { const k = this.P / this.dpr, b = this.bb; return [b[0] * k, b[1] * k, (b[2] - b[0]) * k, (b[3] - b[1]) * k]; }
  charTop() { return (this.layout().cy - 1) * this.P / this.dpr; }

  update(dt) {
    dt = Math.max(0, Math.min(.1, dt || 0));
    this.t += dt; const t = this.t, a = this.activity;
    this.blinkT -= dt; if (this.blinkT < 0) { this.blink = .14; this.blinkT = 2 + Math.random() * 3.5; }
    this.blink = Math.max(0, this.blink - dt);
    this.spawnT -= dt; this.screenT -= dt;
    this.quirkT = (this.quirkT ?? 9) - dt;
    if (this.quirkT < 0 && a !== 'sleep') {
      this.quirk = ['yawn', 'hum', 'smile', 'look', 'smile'][Math.floor(Math.random() * 5)];
      this.quirkUntil = t + (this.quirk === 'hum' ? 3 : 1.6); this.quirkT = 9 + Math.random() * 14;
      if (this.quirk === 'hum') this.spawnT = 0;
    }
    const { cx, cy } = this.layout();
    if (this.spawnT < 0) {
      if (a === 'music' || (this.quirk === 'hum' && t < this.quirkUntil)) { this.parts.push({ type: 'note', x: cx + (Math.random() < .5 ? -3 : this.width()), y: cy + this.geo().note, vx: (Math.random() - .5) * 6, vy: -7, life: 0, max: 2.2 }); this.spawnT = .9; }
      else if (a === 'sleep') { this.parts.push({ type: 'z', x: cx + this.geo().z[0], y: cy + this.geo().z[1], vx: 3, vy: -5, life: 0, max: 2.6 }); this.spawnT = 1.4; }
      else if (a === 'campfire') { this.parts.push({ type: 'spark', x: cx - 9 + Math.random() * 4, y: this.FY - 8, vx: (Math.random() - .5) * 5, vy: -9 - Math.random() * 6, life: 0, max: .8 + Math.random() * .6 }); this.spawnT = .18; }
      else this.spawnT = 1;
    }
    if (this.screenT < 0) { this.screen = (this.screen + 1) % 6; this.screenT = a === 'console' ? .25 : .7; }
    if (Math.random() < dt * .08 && (a === 'tv' || a === 'console' || a === 'handheld')) this.setMood('happy', 1.5);
    for (const p of this.parts) { p.life += dt; p.x += p.vx * dt; p.y += p.vy * dt; if (p.type === 'puff') { p.vx *= .9; p.vy *= .9; } }
    this.parts = this.parts.filter(p => p.life < p.max);
  }

  render() {
    const c = this.ctx, t = this.t, a = this.activity, { cx, cy, FY } = this.layout();
    c.clearRect(0, 0, this.SW, this.SH);
    BB = [1e9, 1e9, -1e9, -1e9];
    if (this.held) {
      if (this.sheet) drawSheet(c, this.sheet, 'walk', t, cx + this.width() / 2, FY, false, true);
      else drawChar(c, cx, FY - this.geo().stand, { char: this.char, pose: this.char === 'fox' ? 'floor' : 'stand', head: Math.sin(t * 3) > 0 ? 'grin' : 'wide', torso: 'rest', t, breath: 0, happy: true, bob: Math.sin(t * 6) > 0 ? 1 : 0 });
      this.finish(c); return;
    }
    if (a === 'tv' && !this.sheet) { draw(c, PROPS.sofa, cx - 4, FY - 12); }
    if (a === 'tv' || a === 'console') {
      const tx = cx - 24, ty = FY - 14;
      draw(c, PROPS.tv, tx, ty); this.drawScreen(c, tx + 3, ty + 6, a);
      if (a === 'console') { draw(c, PROPS.console, tx + 16, FY - 3); this.cable(c, tx + 21, FY - 2, cx + this.geo().cable[0], cy + this.geo().cable[1]); }
    }
    if (a === 'campfire') draw(c, PROPS.fire[Math.floor(t * 7) % 3], cx - 16, FY - 9);
    const q = t < this.quirkUntil ? this.quirk : null;
    const head = (this.blink > 0 || a === 'sleep') ? (a === 'sleep' ? 'sleep' : 'blink')
      : (this.mood === 'happy' && t < this.moodUntil) ? (Math.sin(t * 5) > 0 ? 'happy' : 'grin')
      : q === 'yawn' ? 'wide' : q === 'hum' ? (Math.sin(t * 4) > 0 ? 'happy' : 'grin') : q === 'smile' ? 'happy' : q === 'look' ? 'left'
      : a === 'music' && Math.sin(t * 1.1) > .7 ? 'talk'
      : (a === 'tv' || a === 'console' || (a === 'campfire' && Math.sin(t * .4) > .6)) ? 'left'
      : (Math.sin(t * .23) > .97 ? 'left' : 'open');
    const waving = t < this.waveUntil && a !== 'sleep';
    const torso = waving ? 'wave' : (a === 'console' || a === 'handheld' || a === 'campfire') ? 'hold' : 'rest';
    const bob = a === 'music' || q === 'hum' ? (Math.sin(t * 7) > 0 ? 1 : 0) : a === 'sleep' ? (Math.sin(t * 1.5) > .3 ? 1 : 0) : 0;
    const { pose } = this.layout(), G = this.geo();
    if (this.sheet) {
      const onEdge = pose === 'sit';
      const anim = waving ? 'wave' : a === 'sleep' ? 'sleep' : onEdge ? 'sit' : 'idle';
      drawSheet(c, this.sheet, anim, t, cx + this.width() / 2, FY, false, !onEdge || a === 'sleep');
    } else drawChar(c, cx, cy, { char: this.char, pose: this.char === 'fox' && a === 'sleep' ? 'sleep' : pose, head, torso, bob, t,
      swing: a === 'sit' || a === 'music', phones: a === 'music', happy: (this.mood === 'happy' && t < this.moodUntil) || q === 'hum' });
    if (!waving && !this.sheet && a === 'console') draw(c, PROPS.gamepad, cx + G.pad[0], cy + G.pad[1] + (Math.sin(t * 9) > .6 ? 1 : 0));
    if (!waving && !this.sheet && a === 'handheld') {
      draw(c, PROPS.handheld, cx + G.hh[0], cy + G.hh[1]);
      c.fillStyle = PAL[Math.sin(t * 5) > 0 ? 'V' : 'v']; c.fillRect(cx + G.hh[0] + 1 + (Math.floor(t * 3) % 3), cy + G.hh[1] + 2, 1, 1);
    }
    this.finish(c);
  }

  finish(c) {
    for (const p of this.parts) {
      const k = 1 - p.life / p.max;
      if (p.type === 'note') { c.globalAlpha = Math.min(1, k * 2); draw(c, PROPS.note, p.x, p.y); }
      else if (p.type === 'z') { c.globalAlpha = Math.min(1, k * 2); draw(c, PROPS.z, p.x, p.y); }
      else if (p.type === 'spark') { c.globalAlpha = k; c.fillStyle = k > .5 ? PAL.y : PAL.o; c.fillRect(Math.round(p.x), Math.round(p.y), 1, 1); }
      else if (p.type === 'puff') { c.globalAlpha = k * .9; c.fillStyle = k > .5 ? '#e8e6f0' : '#a9a7b5'; const s = k > .6 ? 2 : 1; c.fillRect(Math.round(p.x), Math.round(p.y), s, s); }
      c.globalAlpha = 1;
    }
    this.bb = [Math.max(0, BB[0]), Math.max(0, BB[1]), Math.min(this.SW, BB[2]), Math.min(this.SH, BB[3])];
    BB = null;
    const out = this.cv.getContext('2d');
    out.imageSmoothingEnabled = false;
    out.clearRect(0, 0, this.cv.width, this.cv.height);
    out.drawImage(this.low, 0, 0, this.cv.width, this.cv.height);
  }

  drawScreen(c, x, y, a) {
    const s = this.screen, t = this.t;
    if (a === 'console') {
      c.fillStyle = '#1d2b53'; c.fillRect(x, y, 8, 4);
      c.fillStyle = '#00b543'; c.fillRect(x, y + 3, 8, 1);
      c.fillStyle = '#ff004d'; c.fillRect(x + (s % 6) + 1, y + 2 - (s % 3 === 0 ? 1 : 0), 1, 1);
      c.fillStyle = '#ffec27'; c.fillRect(x + 6 - (s % 4), y + 1, 1, 1);
    } else {
      c.fillStyle = s < 3 ? '#29adff' : '#ff77a8'; c.fillRect(x, y, 8, 4);
      c.fillStyle = '#ffec27'; c.fillRect(x + 6, y, 2, 1);
      c.fillStyle = '#00e436'; c.fillRect(x, y + 3, 8, 1);
      c.fillStyle = s < 3 ? '#ffccaa' : '#ffffff'; c.fillRect(x + 1 + Math.floor(Math.abs(Math.sin(t * 1.3)) * 5), y + 1 + (Math.sin(t * 6) > 0 ? 1 : 0), 2, 2);
    }
    c.fillStyle = 'rgba(255,255,255,.18)'; c.fillRect(x, y, 1, 1);
  }
  cable(c, x1, y1, x2, y2) {
    c.fillStyle = PAL.k;
    for (let i = 0; i <= 1; i += .05) { const x = x1 + (x2 - x1) * i, y = y1 + (y2 - y1) * i + Math.sin(i * Math.PI) * 3; c.fillRect(Math.round(x), Math.round(Math.min(y, this.FY + 1)), 1, 1); }
  }
}
