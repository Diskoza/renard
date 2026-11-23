import { loadPrefs, connect, on, prefs, api } from '/app/core.js';

const cv = document.getElementById('sky'), g = cv.getContext('2d');
const DEMO = new URLSearchParams(location.search).has('demo');
const C = () => prefs.companion || {};
if (DEMO) document.body.style.background = 'linear-gradient(#2a3d55, #121a26)';
const COL = 3;
const now = () => performance.now() / 1000;
const rnd = (a, b) => a + Math.random() * (b - a);

let W = innerWidth, H = innerHeight, dpr = devicePixelRatio || 1;
function resize() { W = innerWidth; H = innerHeight; dpr = devicePixelRatio || 1; cv.width = W * dpr; cv.height = H * dpr; g.setTransform(dpr, 0, 0, dpr, 0, 0); }
addEventListener('resize', resize); resize();

let scene = { w: W, h: H, floor: H - 48, wins: [], cursor: [-999, -999], down: false, hidden: false }, sceneT = 0;
const body = await new Promise(res => {
  if (DEMO) return res(null);
  let n = 0; const iv = setInterval(() => { if (window.pywebview?.api?.scene) { clearInterval(iv); res(window.pywebview.api); } else if (++n > 50) { clearInterval(iv); res(null); } }, 100);
});
const demo = { wins: [{ id: 1, l: W * .12, r: W * .52, y: H * .34, vis: [[W * .12, W * .52]] }, { id: 2, l: W * .4, r: W * .82, y: H * .52, vis: [[W * .52, W * .82]] }] };
window.nxDemo = demo;
async function poll() {
  try {
    if (body) scene = await body.scene();
    else {
      const wins = demo.wins.map((w, i) => {
        let vis = [[w.l, w.r]];
        for (const o of demo.wins.slice(0, i)) if (o.y <= w.y && w.y <= o.y + H * .3)
          vis = vis.flatMap(([a, b]) => o.r <= a || o.l >= b ? [[a, b]] : [...(o.l > a ? [[a, o.l]] : []), ...(o.r < b ? [[o.r, b]] : [])]);
        return { ...w, vis };
      });
      scene = { w: W, h: H, floor: H - 48, wins, cursor: demo.cursor || [-999, -999], down: false };
    }
    sceneT = now(); syncPiles();
  } catch (e) {}
  setTimeout(poll, busy() ? 80 : 400);
}

let real = { kind: null, temp: 10 }, realT = -1e9;
function wmo(code) {
  if ([71, 73, 75, 77, 85, 86].includes(code)) return 'snow';
  if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82) || code >= 95) return 'rain';
  return null;
}
async function realWeather() {
  if (now() - realT < 900) return; realT = now();
  try { const w = await api('/api/widgets/weather'); real = { kind: wmo(+w.code), temp: +w.temp, text: w.text }; } catch (e) {}
}
function kind() {
  const m = DEMO ? (window.nxDemoKind ?? (new URLSearchParams(location.search).get('demo') || 'snow')) : C().weather || 'off';
  if (m === 'auto') { realWeather(); return real.kind; }
  return m === 'snow' || m === 'rain' ? m : null;
}
const amount = () => Math.max(.1, Math.min(1, +(C().weather_amount ?? .5)));

const flakes = [], drops = [], bits = [];
const MAXF = 900;
function flake(x, y, vx = 0, vy = rnd(25, 60), r = rnd(1, 2.8)) {
  if (flakes.length < MAXF) flakes.push({ x, y, vx, vy, r, ph: rnd(0, 6.3), fr: rnd(.6, 1.6), loose: vy > 80 || Math.abs(vx) > 40 });
}

const piles = new Map();
let floor = new Float32Array(Math.ceil(W / COL) + 1);
const PMAX = 16, FMAX = 24;
function pileFor(w) {
  let p = piles.get(w.id);
  const n = Math.ceil((w.r - w.l) / COL) + 1;
  if (!p) { p = { l: w.l, r: w.r, y: w.y, h: new Float32Array(n), vis: w.vis }; piles.set(w.id, p); }
  else if (p.h.length !== n) {
    const o = p.h, h = new Float32Array(n);
    for (let i = 0; i < n; i++) h[i] = o[Math.min(o.length - 1, Math.round(i * (o.length - 1) / Math.max(1, n - 1)))];
    p.h = h;
  }
  return p;
}
function shed(p, frac, vx = 0, vy = 0, from = 0, to = p.h.length) {
  let budget = 260;
  for (let i = from; i < to; i++) {
    const take = p.h[i] * frac; if (take < .3) continue;
    p.h[i] -= take;
    const x = p.l + i * COL;
    if (!visibleAt(p, x)) continue;
    for (let k = 0; k < Math.min(4, take / 1.4) && budget-- > 0; k++) flake(x + rnd(-1, 1), p.y - rnd(0, take), vx * rnd(.3, .9) + rnd(-25, 25), vy + rnd(0, 60), rnd(1, 2.6));
  }
}
const visibleAt = (p, x) => p.vis.some(([a, b]) => x >= a && x <= b);
let lastSync = 0;
function syncPiles() {
  const t = now(), dt = Math.max(.03, t - lastSync); lastSync = t;
  const seen = new Set();
  for (const w of scene.wins) {
    seen.add(w.id);
    const p = piles.get(w.id);
    if (p) {
      const dx = w.l - p.l, dy = w.y - p.y, v = Math.hypot(dx, dy) / dt;
      p.l = w.l; p.r = w.r; p.y = w.y; p.vis = w.vis;
      if (v > 60 && p.h.some(h => h > .3)) shed(p, Math.min(.9, .35 + v / 2500), -dx / dt * .35, dy < 0 ? -dy / dt * .2 : 30);
    }
    if (kind() === 'snow' || piles.has(w.id)) pileFor(w).vis = w.vis;
  }
  for (const [id, p] of piles) if (!seen.has(id)) {
    p.vis = [[p.l, p.r]]; shed(p, 1, 0, 40); piles.delete(id);
  }
  const n = Math.ceil(W / COL) + 1; if (floor.length !== n) floor = new Float32Array(n);
}

let cur = { x: -999, y: -999, vx: 0, t: 0 };
function mouse(dt) {
  const [x, y] = scene.cursor || [-999, -999];
  const mv = Math.hypot(x - cur.x, y - cur.y);
  cur.vx = (x - cur.x) / Math.max(dt, .016); cur.x = x; cur.y = y;
  if (mv < 1.5) return;
  const push = (h, base, x0) => {
    const i0 = Math.round((x - 14 - x0) / COL), i1 = Math.round((x + 14 - x0) / COL);
    for (let i = Math.max(0, i0); i <= Math.min(h.length - 1, i1); i++) {
      const top = base - h[i]; if (h[i] < .5 || y < top - 6 || y > base + 3) continue;
      const take = h[i] * .7; h[i] -= take;
      const side = Math.sign((x0 + i * COL) - x) || 1;
      for (let k = 0; k < take / 2; k++) flake(x0 + i * COL, top, side * rnd(40, 140) + cur.vx * .15, -rnd(40, 140), rnd(1, 2.2));
    }
  };
  for (const p of piles.values()) if (x >= p.l - 14 && x <= p.r + 14) push(p.h, p.y, p.l);
  push(floor, scene.floor, 0);
}

let spawnAcc = 0, wind = 0, cold = false;
function surfaceHit(x, y0, y1) {
  for (const w of scene.wins) {
    if (x < w.l || x > w.r || !w.vis.some(([a, b]) => x >= a && x <= b)) continue;
    const p = piles.get(w.id), i = Math.round((x - w.l) / COL), top = w.y - (p ? p.h[i] || 0 : 0);
    if (y0 <= top + 1 && y1 >= top) return { p, i, top, w };
  }
  const i = Math.round(x / COL), top = scene.floor - (floor[i] || 0);
  if (y1 >= top && x >= 0 && x <= W) return { p: null, i, top, floor: true };
  return null;
}
function settle(h, i, add, max) {
  for (let k = 0; k < 6 && i > 0 && i < h.length - 1; k++) {
    const l = h[i - 1], r = h[i + 1], c = h[i] + add;
    if (c - Math.min(l, r) < 2.2) break;
    i += l < r ? -1 : 1;
  }
  if (i < 0 || i >= h.length) return;
  h[i] = Math.min(max, h[i] + add * .6);
  if (i > 0) h[i - 1] = Math.min(max, h[i - 1] + add * .2);
  if (i < h.length - 1) h[i + 1] = Math.min(max, h[i + 1] + add * .2);
}
function step(dt) {
  const k = kind(), t = now(), a = amount();
  wind = Math.sin(t * .11) * 18 + Math.sin(t * .37 + 1) * 7 + (C().weather_wind ?? 0);
  if (!scene.hidden) {
    spawnAcc += dt * (k === 'snow' ? 140 * a : k === 'rain' ? 520 * a : 0);
    for (; spawnAcc >= 1; spawnAcc--) {
      if (k === 'snow') flake(rnd(-60, W + 60), rnd(-20, -4));
      else drops.push({ x: rnd(-80, W + 80), y: rnd(-40, -5), vy: rnd(900, 1300), len: rnd(10, 20) });
    }
  }
  mouse(dt);
  const piling = C().weather_piles !== false;
  for (let j = flakes.length - 1; j >= 0; j--) {
    const f = flakes[j];
    const vx = f.loose ? f.vx : wind + f.vx + Math.sin(f.ph + t * f.fr) * 14;
    if (f.loose) { f.vy += 260 * dt; f.vx *= (1 - 1.5 * dt); if (f.vy > 70) { f.loose = false; f.vx = 0; f.vy = rnd(30, 60); } }
    const ny = f.y + f.vy * dt, nx = f.x + vx * dt;
    const c = (Math.abs(cur.x - nx) < 26 && Math.abs(cur.y - ny) < 26);
    if (c) { f.loose = true; f.vx = Math.sign(nx - cur.x || 1) * 90 + cur.vx * .2; f.vy = -40; }
    const hit = f.vy > 0 && surfaceHit(nx, f.y, ny);
    if (hit) {
      if (piling && k === 'snow' && (hit.floor || hit.p)) {
        if (hit.floor) settle(floor, hit.i, f.r * .5, FMAX);
        else if (hit.i <= 1 || hit.i >= hit.p.h.length - 2) { f.loose = false; f.x = nx + (hit.i <= 1 ? -4 : 4); f.y = hit.top + 2; continue; }
        else settle(hit.p.h, hit.i, f.r * .45, PMAX);
      }
      flakes.splice(j, 1); continue;
    }
    f.x = nx; f.y = ny;
    if (f.y > H + 10 || f.x < -120 || f.x > W + 120) flakes.splice(j, 1);
  }
  for (let j = drops.length - 1; j >= 0; j--) {
    const d = drops[j], nx = d.x + wind * 2.5 * dt, ny = d.y + d.vy * dt;
    const hit = surfaceHit(nx, d.y, ny);
    if (hit || ny > H) {
      if (hit && bits.length < 400) for (let q = 0; q < 2; q++) bits.push({ x: nx, y: hit.top, vx: rnd(-70, 70), vy: rnd(-160, -60), life: .35 });
      drops.splice(j, 1); continue;
    }
    d.x = nx; d.y = ny;
  }
  for (let j = bits.length - 1; j >= 0; j--) { const b = bits[j]; b.vy += 700 * dt; b.x += b.vx * dt; b.y += b.vy * dt; if ((b.life -= dt) <= 0) bits.splice(j, 1); }
  const melt = k === 'snow' ? 0 : k === 'rain' ? .25 : (real.temp ?? 5) <= 0 && C().weather === 'auto' ? .004 : .03;
  const ease = (h, max) => {
    for (let i = 0; i < h.length - 1; i++) { const d = h[i] - h[i + 1]; if (Math.abs(d) > 2.5) { const m = (Math.abs(d) - 2.5) * .25 * Math.sign(d); h[i] -= m; h[i + 1] += m; } }
    if (melt) for (let i = 0; i < h.length; i++) h[i] = Math.max(0, h[i] - melt * dt * (1 + h[i] / max));
  };
  for (const p of piles.values()) {
    ease(p.h, PMAX);
    for (const e of [0, p.h.length - 1]) if (p.h[e] > 3 && Math.random() < dt * .8 && visibleAt(p, p.l + e * COL)) {
      p.h[e] -= 1.5; flake(p.l + e * COL + (e ? 2 : -2), p.y - 1, (e ? 1 : -1) * rnd(5, 20), 20, rnd(1, 2));
    }
  }
  ease(floor, FMAX);
  cold = k === 'snow' || (C().weather === 'auto' && real.temp <= 1);
}

function drawPile(h, x0, base, parts) {
  for (const [a, b] of parts) {
    const i0 = Math.max(0, Math.floor((a - x0) / COL)), i1 = Math.min(h.length - 1, Math.ceil((b - x0) / COL));
    let any = false; for (let i = i0; i <= i1; i++) if (h[i] > .4) { any = true; break; }
    if (!any) continue;
    g.beginPath(); g.moveTo(Math.max(a, x0 + i0 * COL), base);
    for (let i = i0; i <= i1; i++) g.lineTo(Math.min(b, Math.max(a, x0 + i * COL)), base - h[i]);
    g.lineTo(Math.min(b, x0 + i1 * COL), base); g.closePath();
    g.fillStyle = 'rgba(246,249,255,.96)'; g.fill();
    g.strokeStyle = 'rgba(170,190,220,.55)'; g.lineWidth = 1; g.stroke();
  }
}
let empty = false;
function draw() {
  const busyNow = flakes.length || drops.length || bits.length || [...piles.values()].some(p => p.h.some(v => v > .4)) || floor.some(v => v > .4);
  if (!busyNow) { if (!empty) { g.clearRect(0, 0, W, H); empty = true; } return; }
  empty = false;
  g.clearRect(0, 0, W, H);
  if (DEMO) for (const w of [...scene.wins].reverse()) { g.fillStyle = w.id === 1 ? '#2b3a4a' : '#3d2f2a'; g.fillRect(w.l, w.y, w.r - w.l, H * .3); g.fillStyle = '#ffffff22'; g.fillRect(w.l, w.y, w.r - w.l, 28); }
  if (DEMO) { g.fillStyle = '#1b1b1f'; g.fillRect(0, scene.floor, W, H - scene.floor); }
  for (const w of [...scene.wins].reverse()) { const p = piles.get(w.id); if (p) drawPile(p.h, p.l, p.y, p.vis); }
  drawPile(floor, 0, scene.floor, [[0, W]]);
  g.fillStyle = 'rgba(255,255,255,.92)';
  g.beginPath();
  for (const f of flakes) { g.moveTo(f.x + f.r, f.y); g.arc(f.x, f.y, f.r, 0, 6.283); }
  g.fill();
  if (drops.length) {
    g.strokeStyle = 'rgba(200,218,240,.7)'; g.lineWidth = 1.4; g.beginPath();
    const sk = wind * 2.5 / 1100;
    for (const d of drops) { g.moveTo(d.x, d.y); g.lineTo(d.x - sk * d.len, d.y - d.len); }
    g.stroke();
  }
  if (bits.length) { g.fillStyle = 'rgba(200,220,240,.7)'; for (const b of bits) g.fillRect(b.x, b.y, 1.6, 1.6); }
}
const busy = () => flakes.length > 0 || drops.length > 0 || !!kind();

let last = now();
function frame() {
  const t = now(), dt = Math.min(.05, t - last); last = t;
  if (!scene.hidden) { step(dt); draw(); }
  setTimeout(() => requestAnimationFrame(frame), busy() || !empty ? 20 : 500);
}

const bc = 'BroadcastChannel' in window ? new BroadcastChannel('nx-weather') : null;
setInterval(() => {
  const k = kind();
  const near = flakes.filter(f => !f.loose).length;
  bc?.postMessage({ kind: k, amount: amount(), cold, temp: real.temp, falling: near, floor: floor.reduce((s, v) => s + v, 0) / floor.length });
}, 2000);

window.nxWeather = { flakes, drops, piles, get floor() { return floor; }, get scene() { return scene; }, kind, step, draw };
if (!DEMO) { await loadPrefs(); on('prefs', (p) => { if (p && p.type === 'prefs') loadPrefs(); }); connect(); }
else { try { await loadPrefs(); } catch (e) {} }
poll(); frame();
