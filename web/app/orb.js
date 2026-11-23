import { state, prefs, accentRgb } from './core.js';

const BASE = {
  sleep:     { col: [111, 95, 168], amp: .02, spin: .15, size: .62, glow: .12 },
  idle:      { col: null,           amp: .04, spin: .35, size: .80, glow: .28 },
  listening: { col: [255, 140, 90], amp: .10, spin: .55, size: .86, glow: .50 },
  thinking:  { col: [240, 170, 95], amp: .07, spin: 1.6, size: .78, glow: .42 },
  tool:      { col: [224, 164, 88], amp: .09, spin: 1.1, size: .80, glow: .45 },
  speaking:  { col: [255, 190, 150], amp: .08, spin: .6, size: .84, glow: .55 },
  error:     { col: [226, 109, 90], amp: .12, spin: .3, size: .78, glow: .40 },
};
export const ORB_LABELS = { sleep: 'сплю · VRAM свободна', idle: 'готов', listening: 'слушаю', thinking: 'думаю',
  tool: 'работаю', speaking: 'говорю', error: 'ошибка' };

export class Orb {
  constructor(canvas, opts = {}) {
    this.cv = canvas; this.cx = canvas.getContext('2d'); this.opts = opts;
    this.cur = { col: [217, 119, 87], amp: .04, spin: .35, size: .8, glow: .28 };
    this.ay = 0; this.last = performance.now(); this.alive = true; this.n = 0;
    this.build();
    this.ro = new ResizeObserver(() => this.resize()); this.ro.observe(canvas); this.resize();
    requestAnimationFrame(t => this.frame(t));
  }
  cfg() { return Object.assign({ particles: 1800, size: 1, speed: 1, rings: true, glow: 1, style: 'sphere' }, (prefs.ui || {}).orb || {}, this.opts); }
  build() {
    const c = this.cfg(); const N = Math.max(200, Math.min(6000, c.particles | 0)); this.n = N; this.style = c.style;
    this.P = [];
    for (let i = 0; i < N; i++) {
      if (c.style === 'ring') {
        const a = Math.random() * 6.283, b = (Math.random() - .5) * .5, r = 1 + (Math.random() - .5) * .18;
        this.P.push([Math.cos(a) * r, b * .35, Math.sin(a) * r, Math.random() * 6.28]);
      } else if (c.style === 'galaxy') {
        const arm = i % 3, t = Math.random(), a = t * 7 + arm * 2.094 + (Math.random() - .5) * .5, r = .15 + t * .95;
        this.P.push([Math.cos(a) * r, (Math.random() - .5) * .12 * (1 - t), Math.sin(a) * r, Math.random() * 6.28]);
      } else {
        const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = i * 2.399963229728653;
        this.P.push([Math.cos(th) * r, y, Math.sin(th) * r, Math.random() * 6.28]);
      }
    }
  }
  resize() { const r = devicePixelRatio || 1; this.cv.width = this.cv.clientWidth * r; this.cv.height = this.cv.clientHeight * r; }
  destroy() { this.alive = false; this.ro.disconnect(); }
  frame(now) {
    if (!this.alive) return;
    requestAnimationFrame(t => this.frame(t));
    if (!this.cv.offsetParent) return;
    const c = this.cfg();
    if (c.particles !== this.n || c.style !== this.style) this.build();
    const dt = Math.min(.05, (now - this.last) / 1000); this.last = now;
    const st = BASE[state.orb] || BASE.idle, col = st.col || accentRgb(), k = 1 - Math.pow(.02, dt), cur = this.cur;
    for (const key of ['amp', 'spin', 'size', 'glow']) cur[key] += (st[key] - cur[key]) * k;
    for (let i = 0; i < 3; i++) cur.col[i] += (col[i] - cur.col[i]) * k;
    const level = state.level, loadBoost = state.load.gpu / 100, heat = Math.min(1, state.load.cpu / 100);
    this.ay += dt * (cur.spin + loadBoost * 1.2) * c.speed;
    const ax = (this.style === 'sphere' ? .35 : .45) + Math.sin(now / 4000) * .15;
    const W = this.cv.width, H = this.cv.height, R = Math.min(W, H) * .30 * (cur.size + level * .12) * c.size;
    const ox = W / 2, oy = H / 2, t = now / 1000, cx = this.cx;
    cx.clearRect(0, 0, W, H);
    const [r0, g0, b0] = cur.col.map(Math.round);
    const glow = cur.glow * c.glow;
    const g = cx.createRadialGradient(ox, oy, R * .1, ox, oy, R * 1.9);
    g.addColorStop(0, `rgba(${r0},${g0},${b0},${(glow + level * .5) * .55})`);
    g.addColorStop(.5, `rgba(${r0},${g0 * .7 | 0},${b0 * .6 | 0},${(glow + level * .3) * .18})`);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    cx.fillStyle = g; cx.fillRect(0, 0, W, H);
    if (c.rings) {
      cx.lineWidth = Math.max(1, W / 1400);
      for (let i = 0; i < 3; i++) {
        const rr = R * (1.22 + i * .14 + level * .1), tilt = .28 + i * .18;
        cx.strokeStyle = `rgba(${r0},${g0},${b0},${.10 + (state.orb === 'thinking' ? .12 : 0) - i * .025})`;
        cx.beginPath(); cx.ellipse(ox, oy, rr, rr * tilt, t * (.12 + i * .07) * (i % 2 ? -1 : 1) * c.speed + i, 0, 6.283); cx.stroke();
      }
    }
    const cy_ = Math.cos(this.ay), sy = Math.sin(this.ay), cxr = Math.cos(ax), sxr = Math.sin(ax);
    const amp = cur.amp + level * .16 + loadBoost * .04;
    const wobble = state.orb === 'thinking' ? 3.0 : state.orb === 'listening' ? 2.2 : 1.4;
    const P = this.P, sc = W / 1100;
    for (let i = 0; i < P.length; i++) {
      const p = P[i];
      const d = 1 + amp * Math.sin(t * wobble + p[3] + p[1] * 4) + amp * .6 * Math.sin(t * 1.7 + p[0] * 5 + p[2] * 3);
      const x = p[0] * d, y = p[1] * d, z = p[2] * d;
      const x1 = x * cy_ - z * sy, z1 = x * sy + z * cy_;
      const y1 = y * cxr - z1 * sxr, z2 = y * sxr + z1 * cxr;
      const depth = (z2 + 1.4) / 2.4;
      const a = .22 + depth * .78, sz = (1.0 + depth * 2.2) * sc;
      cx.fillStyle = `rgba(${Math.min(255, r0 + heat * 25 + depth * 30) | 0},${Math.min(255, g0 + depth * 35) | 0},${Math.min(255, b0 + depth * 30) | 0},${a})`;
      cx.fillRect(ox + x1 * R - sz / 2, oy + y1 * R - sz / 2, sz, sz);
    }
    const core = cx.createRadialGradient(ox, oy, 0, ox, oy, R * .55);
    core.addColorStop(0, `rgba(255,230,210,${.10 + level * .35 + (state.orb === 'speaking' ? .08 : 0)})`);
    core.addColorStop(1, 'rgba(255,230,210,0)');
    cx.fillStyle = core; cx.beginPath(); cx.arc(ox, oy, R * .55, 0, 6.283); cx.fill();
    state.level *= Math.pow(.15, dt);
  }
}
