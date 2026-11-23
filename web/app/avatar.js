import { prefs, state } from './core.js';
import { ACCESSORIES, accSlot, measureHead, makeAccessory, disposeAccessory } from './accessories.js';
import { GESTURE_CLIPS, GESTURE_OPTS, SIT_CLIPS, SEATED, catalog } from './anim.js';
export { ACCESSORIES };

export const ACTIONS = { wave: 2.4, jump: 1.0, dance: 8, nod: 1.3, shake: 1.3, bow: 1.8, think: 3.5, shrug: 1.6, clap: 2.2,
  stretch: 2.6, point: 2.2, celebrate: 2.0, catch: 2.4, shiver: 1.8, brush: 1.6, balance: 2.0,
  puton: 2.6, earbuds: 3.6, neckoff: 2.4, shy: 3.0 };
export const ACTION_RU = { wave: 'помахать', jump: 'прыжок', dance: 'танец', nod: 'кивнуть', shake: 'покачать головой', bow: 'поклон',
  think: 'задуматься', shrug: 'пожать плечами', clap: 'хлопать', stretch: 'потянуться', point: 'показать', celebrate: 'ликовать',
  catch: 'поймать снежинку', shiver: 'поёжиться', brush: 'стряхнуть снег', balance: 'балансировать',
  puton: 'надеть наушники', earbuds: 'вставить вкладыши', neckoff: 'снять наушники на шею', shy: 'смутиться' };
const A_REST = [0, 0, 1.22, 0], A_EAR = [-1.2, 0, 1.0, 2.7], A_OVER = [-1.3, 0, .45, 2.5], A_NECK = [-1.3, 0, .95, 2.9],
  A_POCKET = [.3, .5, 1.1, 1.4];
const smooth = k => k * k * (3 - 2 * k);
function keyArms(B, side, u, keys) {
  let i = 0;
  while (i < keys.length - 2 && u > keys[i + 1][0]) i++;
  const [u0, a] = keys[i], [u1, b] = keys[i + 1], k = smooth(Math.min(1, Math.max(0, (u - u0) / ((u1 - u0) || 1))));
  const m = j => a[j] + (b[j] - a[j]) * k, s = side > 0 ? 'right' : 'left';
  B(s + 'UpperArm', m(0), side * m(1), side * m(2)); B(s + 'LowerArm', 0, side * m(3));
}
export const DANCE_RU = { groove: 'грув', sway: 'покачивание', robot: 'робот', hype: 'прыжки', wave: 'волна' };
export const EMOTIONS = ['neutral', 'happy', 'sad', 'angry', 'surprised', 'relaxed'];
export const EMOTION_RU = { neutral: 'спокойствие', happy: 'радость', sad: 'грусть', angry: 'злость', surprised: 'удивление', relaxed: 'умиротворение' };
const BADGE = { happy: '😊', sad: '😢', angry: '😠', surprised: '😮', relaxed: '😌', think: '🤔', clap: '👏', celebrate: '🎉', sleep: '💤', point: '👉' };

export function applyAvatarEvent(ctl, ev) {
  if (!ctl || !ev) return;
  const al = { hello: 'wave', yes: 'nod', no: 'shake' }, a = al[ev.action] || ev.action;
  if (ev.emotion) ctl.emote(ev.emotion, 6);
  if (ev.face && ctl.showFace) ctl.showFace(ev.face, ev.seconds || 6);
  if (ev.red !== undefined && ctl.setRed) ctl.setRed(ev.red);
  if (ev.anim && ctl.anim) ctl.anim(ev.anim, { seconds: ev.seconds || undefined }).catch(() => {});
  if (a === 'sit' || a === 'sleep') ctl.setMode(a);
  else if (a === 'stand' || a === 'wake' || a === 'stop') ctl.setMode('stand');
  else if (ACTIONS[a]) { if (ctl.mode !== 'stand' && !['wave', 'nod', 'shake', 'think', 'clap'].includes(a)) ctl.setMode('stand'); ctl.act(a, { style: ev.style, user: true }); }
}

export function companionCfg() {
  const c = prefs.companion || {};
  const bake = new URLSearchParams(location.search).get('bake');
  if (bake) return { ...c, kind: 'vrm', file: bake, vrm: bake };
  return { ...c, kind: c.kind || 'fox2d', file: c.file || c.vrm || '' };
}

function makeCtl() {
  const c = {
    mode: 'stand', dir: 0, gesture: null, emotion: 'neutral', emoUntil: 0, dragVx: 0, lookX: 0, lookY: 0, phase: 0, modeT: 0,
    setMode(m) { if (m !== c.mode) { c.mode = m; c.modeT = performance.now() / 1000; if (m === 'sit') c.sitYaw = Math.random() < .5 ? -.8 : .8; } },
    act(name, o = {}) {
      if (!ACTIONS[name]) return;
      const style = name === 'dance' ? (DANCES.includes(o.style) ? o.style : DANCES[Math.floor(Math.random() * DANCES.length)]) : undefined;
      c.gesture = { name, t0: performance.now() / 1000, dur: o.dur || ACTIONS[name], style };
      if (c.clips && c.mode === 'stand') {
        const auto = !o.user;
        const p = name === 'dance' ? c.clips.playDance(c.bpm || 0, { seconds: o.dur || 12, auto })
          : GESTURE_CLIPS[name] ? c.clips.playOneOf(GESTURE_CLIPS[name], { auto, ...(GESTURE_OPTS[name] || {}) }) : null;
        if (!p && !auto && c.clips.playing()) c.clips.stop(.25);
        p && p.catch(e => console.warn('clip', e));
      }
    },
    emote(name, sec = 5) {
      c.emotion = EMOTIONS.includes(name) ? name : 'neutral'; c.emoUntil = performance.now() / 1000 + sec;
      if (c.clips && c.mode === 'stand' && !c.clips.playing() && GESTURE_CLIPS[name] && name !== 'relaxed')
        c.clips.playOneOf(GESTURE_CLIPS[name], { auto: true }).catch(() => {});
      else if (c.clips && c.mode === 'sit' && !c.clips.playing() && SIT_CLIPS[name])
        c.clips.playOneOf(SIT_CLIPS[name], { auto: true, upper: true }).catch(() => {});
    },
    async anim(what, o = {}) {
      if (!c.clips) return false;
      const cat = await catalog();
      const e = cat.find(x => x.id === what || x.name.toLowerCase() === String(what).toLowerCase());
      if (e ? SEATED.test(e.name) : what === 'sit') {
        if (c.mode !== 'sit') (c.requestMode || c.setMode)('sit');
        return e ? c.clips.play(e, { ...o, upper: true }) : c.clips.playCategory('sit', { ...o, upper: true });
      }
      if (c.mode !== 'stand') (c.requestMode || c.setMode)('stand');
      return (await c.clips.play(what, o)) || c.clips.playCategory(what, o);
    },
    face(d) { c.dir = Math.sign(d || 0); },
    look(x, y) { c.lookX = Math.max(-1, Math.min(1, x)); c.lookY = Math.max(-1, Math.min(1, y)); },
  };
  return c;
}

export function renderAvatar(box, { cfg = companionCfg(), snapshot = false, view = 'stage' } = {}) {
  box.innerHTML = '';
  const ctl = makeCtl();
  if (cfg.file && (cfg.kind === 'robot' || /\.glb$/i.test(cfg.file))) {
    const cv = document.createElement('canvas'); cv.style.cssText = 'width:100%;height:100%;display:block'; box.appendChild(cv);
    Object.assign(ctl, { stop: () => {}, apply: () => {}, bounds: () => null, anchor: () => box.clientHeight });
    import('./robot.js').then(m => m.startRobot(cv, '/avatars/' + encodeURIComponent(cfg.file),
      { ctl, view, cfg, snapshotName: snapshot ? cfg.file : null }));
    return ctl;
  }
  if (cfg.kind === 'vrm' && cfg.file) {
    const cv = document.createElement('canvas'); cv.style.cssText = 'width:100%;height:100%;display:block'; box.appendChild(cv);
    Object.assign(ctl, { stop: () => {}, apply: () => {}, bounds: () => null, anchor: () => box.clientHeight });
    startVRM(cv, '/avatars/' + encodeURIComponent(cfg.file), { snapshotName: snapshot ? cfg.file : null, ctl, view });
    return ctl;
  }
  return start2D(box, cfg, ctl);
}

function start2D(box, cfg, ctl) {
  const wrap = document.createElement('div'); wrap.className = 'av2d-wrap';
  const img = document.createElement('img');
  img.src = cfg.kind === '2d' && cfg.file ? '/avatars/' + encodeURIComponent(cfg.file) : '/assets/renard_corner.svg';
  img.className = 'avatar2d'; img.draggable = false;
  const badge = document.createElement('div'); badge.className = 'av-badge';
  wrap.append(img, badge); box.appendChild(wrap);
  let alive = true, last = performance.now() / 1000;
  (function tick() {
    if (!alive) return; requestAnimationFrame(tick);
    const t = performance.now() / 1000, dt = Math.min(.1, t - last); last = t;
    const lv = state.level, s = companionCfg().scale ?? 1, flip = companionCfg().flip2d ? -1 : 1;
    let x = 0, y = 0, r = 0, sx = 1, sy = 1, origin = '50% 100%', b = '';
    const br = Math.sin(t * 1.6) * .012;
    sx += br * .5; sy -= br * .3;
    if (state.orb === 'speaking') { sx += lv * .06; sy += lv * .04; r = Math.sin(t * 9) * lv * 3; }
    if (ctl.mode === 'walk') { ctl.phase += dt * 9; y = -Math.abs(Math.sin(ctl.phase)) * 7; r = Math.sin(ctl.phase) * 3; }
    if (ctl.mode === 'sit') { sy *= .96; r = Math.sin(t * 1.3) * 1.5; }
    if (ctl.mode === 'sleep') { r = 7; sy *= .95 + Math.sin(t * 1.1) * .01; b = BADGE.sleep; }
    if (ctl.mode === 'drag') { origin = '50% 0%'; r = Math.max(-25, Math.min(25, -ctl.dragVx * .02)) + Math.sin(t * 3) * 5; }
    if (ctl.mode === 'fall') { sy *= 1.06; sx *= .95; }
    const g = ctl.gesture;
    if (g) {
      const u = (t - g.t0) / g.dur, e = Math.sin(Math.PI * Math.min(1, u));
      if (u >= 1) ctl.gesture = null;
      else if (g.name === 'wave') r += Math.sin(t * 10) * 8 * e;
      else if (g.name === 'jump' || g.name === 'celebrate') { y -= 90 * Math.max(0, Math.sin(Math.PI * Math.min(1, u * 1.15))); if (g.name === 'celebrate') b = BADGE.celebrate; }
      else if (g.name === 'dance') { r += Math.sin(t * 4.2) * 10; y -= Math.abs(Math.sin(t * 8.4)) * 10; }
      else if (g.name === 'nod') { sy *= 1 - .05 * Math.abs(Math.sin(u * Math.PI * 3)); }
      else if (g.name === 'shake') x += Math.sin(u * Math.PI * 8) * 10 * (1 - u);
      else if (g.name === 'bow') { sy *= 1 - .12 * e; r += 4 * e; }
      else if (g.name === 'stretch') { sy *= 1 + .07 * e; sx *= 1 - .03 * e; }
      else if (g.name === 'shrug') y -= 8 * e;
      else if (BADGE[g.name]) b = BADGE[g.name];
      if (g && g.name === 'clap') { sx *= 1 + .03 * Math.abs(Math.sin(t * 14)); }
    }
    if (!b && ctl.emotion !== 'neutral' && t < ctl.emoUntil) b = BADGE[ctl.emotion] || '';
    if (t > ctl.emoUntil) ctl.emotion = 'neutral';
    const dirFlip = (ctl.dir || 1) * flip;
    img.style.transformOrigin = origin;
    img.style.transform = `translate(calc(-50% + ${x}px), ${y}px) rotate(${r}deg) scale(${s * sx * dirFlip}, ${s * sy})`;
    img.style.filter = state.orb === 'listening' ? 'drop-shadow(0 0 18px rgba(255,140,90,.8))'
      : ctl.emotion === 'angry' ? 'drop-shadow(0 0 14px rgba(230,60,40,.7))'
      : ctl.emotion === 'sad' ? 'saturate(.6) drop-shadow(0 8px 18px rgba(0,0,0,.45))' : 'drop-shadow(0 8px 18px rgba(0,0,0,.45))';
    if (badge.textContent !== b) { badge.textContent = b; badge.classList.toggle('on', !!b); }
    if (b) badge.style.top = Math.max(0, box.clientHeight - (parseFloat(getComputedStyle(img).bottom) || 0) - img.offsetHeight * s + y - 40) + 'px';
  })();
  const rel = () => { const br = box.getBoundingClientRect(), ir = img.getBoundingClientRect(); return [ir.left - br.left, ir.top - br.top, ir.width, ir.height]; };
  Object.assign(ctl, {
    stop: () => { alive = false; },
    apply: () => {},
    bounds: () => { const [x, y, w, hh] = rel(); return [x - 10, y - 46, w + 20, hh + 50]; },
    anchor: (m = ctl.mode) => { const br = box.getBoundingClientRect(), H = img.offsetHeight * (companionCfg().scale ?? 1);
      const bottom = br.height - (parseFloat(getComputedStyle(img).bottom) || 0);
      return (m === 'sit' || m === 'sleep') ? bottom - H * .22 : bottom - 2; },
  });
  return ctl;
}

const BONES = ['hips', 'spine', 'chest', 'neck', 'head', 'leftShoulder', 'rightShoulder', 'leftUpperArm', 'rightUpperArm',
  'leftLowerArm', 'rightLowerArm', 'leftHand', 'rightHand', 'leftUpperLeg', 'rightUpperLeg', 'leftLowerLeg', 'rightLowerLeg', 'leftFoot', 'rightFoot'];


const TALK = [
  (add, w) => { add('rightUpperArm', -.5, 0, -.3); add('rightLowerArm', 0, .95 + w * .3); add('head', 0, -.05, 0); },
  (add, w) => { add('leftUpperArm', -.38, 0, .22); add('leftLowerArm', 0, -.85 - w * .25);
                add('rightUpperArm', -.38, 0, -.22); add('rightLowerArm', 0, .85 + w * .25); },
  (add, w) => { add('leftUpperArm', -.55, 0, .38); add('leftLowerArm', 0, -1.0 - w * .3); add('head', 0, .1, .05); },
  (add, w) => { add('rightUpperArm', -.32, 0, -.12); add('rightLowerArm', 0, 1.75 + w * .1); add('head', .05, -.04, 0); },
  (add, w) => { add('leftUpperArm', -.45, -.25, .12); add('rightUpperArm', -.45, .25, -.12);
                add('leftLowerArm', 0, -1.35); add('rightLowerArm', 0, 1.35); add('head', .04 + w * .05, 0, 0); },
  (add, w) => { add('head', 0, 0, .06 + w * .04); add('spine', 0, .06, 0); },
];
const IDLE = {
  look: (B, add, u, e) => { add('head', -.04 * e, .55 * Math.sin(u * Math.PI * 2) * e, 0); add('spine', 0, .12 * Math.sin(u * Math.PI * 2) * e, 0); },
  shift: (B, add, u, e) => { add('hips', 0, 0, .06 * e); add('rightLowerLeg', .22 * e); add('rightUpperLeg', -.08 * e); add('spine', 0, 0, -.05 * e); },
  watch: (B, add, u, e) => { add('leftUpperArm', -.95 * e, 0, .55 * e); add('leftLowerArm', 0, -1.55 * e); add('head', .38 * e, .22 * e, 0); },
  scratch: (B, add, u, e, t) => { add('rightUpperArm', -.55 * e, 0, -1.55 * e); add('rightLowerArm', 0, 1.85 * e + .14 * Math.sin(t * 14) * e); add('head', .06 * e, 0, .14 * e); },
  yawn: (B, add, u, e, t, E) => { add('head', -.25 * e); add('leftUpperArm', -.4 * e, 0, .3 * e); add('leftLowerArm', 0, -1.9 * e); E.aa = Math.max(E.aa || 0, .9 * e); E.relaxed = .6 * e; },
  sigh: (B, add, u, e) => { const up = Math.sin(Math.PI * Math.min(1, u * 1.6)); add('leftShoulder', 0, 0, .14 * up); add('rightShoulder', 0, 0, -.14 * up); add('head', .1 * e); },
};
const IDLE_DUR = { look: 3.2, shift: 4, watch: 2.6, scratch: 2.2, yawn: 2.8, sigh: 2.2 };
export const DANCES = ['groove', 'sway', 'robot', 'hype', 'wave'];

function dance(style, phi, B, add, R, E, c) {
  const k = (1 - Math.cos(phi)) / 2, h = phi / 2, sh = Math.sin(h), ch = Math.cos(h);
  if (style === 'groove') {
    add('leftUpperLeg', -.35 * k); add('rightUpperLeg', -.35 * k); add('leftLowerLeg', .7 * k); add('rightLowerLeg', .7 * k);
    B('leftFoot', -.3 * k); B('rightFoot', -.3 * k);
    R.y -= .055 * k; R.ry = .38 * sh; B('hips', 0, .12 * sh, .1 * ch); B('spine', .06 + .05 * k, -.1 * sh, 0);
    B('leftUpperArm', .5 * sh, 0, -1.0); B('rightUpperArm', -.5 * sh, 0, 1.0); B('leftLowerArm', 0, -1.3, .2); B('rightLowerArm', 0, 1.3, -.2);
    B('head', .14 * k, .12 * sh, .06 * ch); E.happy = .7;
  } else if (style === 'sway') {
    R.x = .13 * sh; R.rz = -.07 * sh; R.ry = .22 * sh; R.y -= .03 * k;
    add('leftUpperLeg', -.4 * Math.max(0, -sh)); add('leftLowerLeg', .8 * Math.max(0, -sh));
    add('rightUpperLeg', -.4 * Math.max(0, sh)); add('rightLowerLeg', .8 * Math.max(0, sh));
    B('leftUpperArm', -.15, 0, .6 + .45 * Math.sin(phi)); B('rightUpperArm', -.15, 0, -.6 - .45 * Math.sin(phi + 1.4));
    B('leftLowerArm', 0, -.2, .5 * Math.sin(phi + .7)); B('rightLowerArm', 0, .2, -.5 * Math.sin(phi + 2.1));
    B('head', 0, .1 * sh, .16 * sh); B('hips', 0, 0, -.08 * sh); E.relaxed = .6; E.happy = .5;
  } else if (style === 'robot') {
    const i = Math.floor(phi / Math.PI) % 4; R.k = 30;
    const L = [[0, 1.45], [0, -1.45], [-1.3, 0], [0, 1.45]][i], Rr = [[0, -1.45], [-1.3, 0], [0, 1.45], [0, 1.45]][i];
    B('leftUpperArm', 0, 0, L[0]); B('leftLowerArm', 0, 0, L[1]); B('rightUpperArm', 0, 0, -Rr[0]); B('rightLowerArm', 0, 0, -Rr[1]);
    B('head', 0, [.35, -.35, 0, .2][i], [0, 0, .15, 0][i]); B('spine', 0, [-.15, .15, 0, -.1][i], 0); R.ry = [-.25, .25, 0, .1][i];
    add('leftLowerLeg', i % 2 ? .35 : 0); add('rightLowerLeg', i % 2 ? 0 : .35); add('leftUpperLeg', i % 2 ? -.15 : 0); add('rightUpperLeg', i % 2 ? 0 : -.15);
    R.y -= .02 * (i % 2);
  } else if (style === 'hype') {
    const air = Math.max(0, Math.sin(h)); R.y += .12 * air * air; R.k = 20; R.ry = .25 * Math.sin(phi / 4);
    const crouch = Math.max(0, -Math.sin(h)) * .8;
    add('leftUpperLeg', -.5 * crouch - .2 * air); add('rightUpperLeg', -.5 * crouch - .2 * air);
    add('leftLowerLeg', 1.0 * crouch + .35 * air); add('rightLowerLeg', 1.0 * crouch + .35 * air);
    B('rightUpperArm', -.2, 0, -.6 - .9 * air); B('rightLowerArm', 0, 1.6 - 1.2 * air); B('leftUpperArm', .2, 0, -1.1); B('leftLowerArm', 0, -1.4);
    B('head', -.12 * air + .1 * crouch); E.happy = 1;
  } else {
    B('leftUpperArm', 0, 0, .3 * Math.sin(phi)); B('rightUpperArm', 0, 0, -.3 * Math.sin(phi + 1.6));
    B('leftLowerArm', 0, 0, .7 * Math.sin(phi + .8)); B('rightLowerArm', 0, 0, -.7 * Math.sin(phi + 2.4));
    B('leftShoulder', 0, 0, .12 * Math.sin(phi + .4)); B('rightShoulder', 0, 0, -.12 * Math.sin(phi + 2.0));
    add('leftUpperLeg', -.25 * k); add('rightUpperLeg', -.25 * k); add('leftLowerLeg', .5 * k); add('rightLowerLeg', .5 * k);
    B('head', 0, 0, .14 * Math.sin(phi + 1.2)); B('chest', 0, 0, .08 * Math.sin(phi + 1.2)); R.y -= .04 * k; R.ry = .2 * sh; E.happy = .8;
  }
}

function pose(c, t, dt, P, R, E) {
  const B = (n, x = 0, y = 0, z = 0) => { P[n] = [x, y, z]; };
  const add = (n, x = 0, y = 0, z = 0) => { const v = P[n] || (P[n] = [0, 0, 0]); v[0] += x; v[1] += y; v[2] += z; };
  const br = Math.sin(t * 1.6), speaking = state.orb === 'speaking', lv = state.level;
  const T = performance.now() / 1000;
  R.x = 0; R.y = 0; R.ry = 0; R.rz = 0; R.k = 10;
  if (c.mode === 'walk') {
    const speed = c.walkSpeed || 90, leg = Math.max(50, c.legPx || 120);
    const cad = Math.min(2.4, 1.45 + speed / 170);
    const stride = speed / cad;
    const amp = Math.max(.14, Math.min(.6, Math.asin(Math.min(.95, stride / (2 * leg * .9)))));
    c.phase += dt * Math.PI * cad;
    const s = Math.sin(c.phase), co = Math.cos(c.phase);
    const lu = -amp * s, ru = amp * s, ll = .1 + 1.5 * amp * Math.max(0, co), rl = .1 + 1.5 * amp * Math.max(0, -co);
    B('leftUpperLeg', lu); B('rightUpperLeg', ru); B('leftLowerLeg', ll); B('rightLowerLeg', rl);
    B('leftFoot', -(lu + ll) * .55); B('rightFoot', -(ru + rl) * .55);
    B('leftUpperArm', .85 * amp * s, 0, -1.25); B('rightUpperArm', -.85 * amp * s, 0, 1.25);
    B('leftLowerArm', 0, -.3 - .25 * Math.max(0, -s)); B('rightLowerArm', 0, .3 + .25 * Math.max(0, s));
    B('hips', 0, .12 * s * amp, .035 * s); B('spine', .05, -.1 * s * amp, 0); B('head', 0, -c.dir * .32, -.02 * s);
    R.y = .03 * amp * Math.abs(co) - .012; R.ry = c.dir * 1.15; R.k = 18;
  } else if (c.mode === 'sit' || c.mode === 'sleep') {
    const sleep = c.mode === 'sleep';
    const k1 = sleep ? 0 : .24 * Math.sin(t * 1.25), k2 = sleep ? 0 : .24 * Math.sin(t * 1.25 + 2.3);
    B('leftUpperLeg', -1.45, 0, .1); B('rightUpperLeg', -1.45, 0, -.1);
    B('leftLowerLeg', 1.32 + k1); B('rightLowerLeg', 1.32 + k2);
    if (sleep) {
      B('leftUpperArm', 0, -.35, -1.2); B('rightUpperArm', 0, .35, 1.2); B('leftLowerArm', 0, -1.25); B('rightLowerArm', 0, 1.25);
      B('spine', .22 + br * .02); B('chest', .1); B('head', .45, 0, .15); E.relaxed = .5; E.blink = 1;
    } else {
      B('leftUpperArm', .5, 0, -1.22); B('rightUpperArm', .5, 0, 1.22); B('leftLowerArm', 0, -.2); B('rightLowerArm', 0, .2);
      B('leftShoulder', 0, 0, .06); B('rightShoulder', 0, 0, -.06);
      B('spine', -.05 + br * .015); B('chest', .03); B('head', .04, 0, .05 * Math.sin(t * .4));
    }
    R.ry = (c.dir || c.sitYaw || .7) * .42;
  } else if (c.mode === 'drag') {
    const pend = Math.max(-.6, Math.min(.6, -c.dragVx * .0015));
    B('leftUpperArm', 0, 0, -.45); B('rightUpperArm', 0, 0, .45); B('leftLowerArm', 0, -.4); B('rightLowerArm', 0, .4);
    B('leftUpperLeg', pend * .6 + Math.sin(t * 3) * .12, 0, .05); B('rightUpperLeg', pend * .6 - Math.sin(t * 3 + 1) * .12, 0, -.05);
    B('leftLowerLeg', .35); B('rightLowerLeg', .35); R.rz = pend * .25; E.surprised = .7; R.k = 14;
  } else if (c.mode === 'fall') {
    B('leftUpperArm', 0, 0, .9); B('rightUpperArm', 0, 0, -.9); B('leftUpperLeg', -.4); B('rightUpperLeg', -.3);
    B('leftLowerLeg', .8); B('rightLowerLeg', .7); E.surprised = 1; R.k = 16;
  } else {
    B('leftUpperArm', .05, 0, -1.36 - br * .025); B('rightUpperArm', .05, 0, 1.36 + br * .025);
    B('leftLowerArm', 0, -.22); B('rightLowerArm', 0, .22); B('leftHand', 0, 0, -.12); B('rightHand', 0, 0, .12);
    B('spine', br * .015); B('chest', Math.sin(t * 1.6 + .5) * .01); B('hips', 0, 0, Math.sin(t * .5) * .015);
    R.ry = c.dir * .9;
    if (speaking) {
      if (!c.talk || T > c.talk.until) {
        let i = Math.floor(Math.random() * TALK.length); if (c.talk && i === c.talk.i) i = (i + 1) % TALK.length;
        c.talk = { i, until: T + 1.2 + Math.random() * 1.5 };
      }
      TALK[c.talk.i](add, Math.sin(t * 4.3) * Math.min(1, lv * 2.5));
      if (lv - (c.prevLv || 0) > .1 && T - (c.beatT || 0) > .3) c.beatT = T;
      add('head', .11 * Math.exp(-(T - (c.beatT || 0)) * 7));
      add('spine', 0, .03 * Math.sin(t * .9), 0);
    }
    c.prevLv = lv;
    if (state.orb === 'thinking') {
      if (Math.floor(T / 4) % 3 === 0) { B('rightUpperArm', -1.0, 0, 1.05); B('rightLowerArm', 0, 2.2); }
      add('head', -.1, .1 * Math.sin(T * .7), .1);
    }
    if (state.orb === 'listening') { add('head', -.04 + .06 * Math.max(0, Math.sin(T * 2.4)) ** 8, 0, .06); add('spine', .04); }
  }
  const quiet = (c.mode === 'stand' || c.mode === 'sit') && !c.gesture && state.orb === 'idle' && c.emotion === 'neutral';
  if (quiet && !c.idle && T > (c.idleNext || 0)) {
    const talked = T - (state.lastTalk || -1e9) / 1000 < 240 || performance.now() - (state.lastTalk || -1e9) < 240000;
    const pool = talked ? ['look', 'look', 'shift', 'scratch']
      : c.mode === 'sit' ? ['look', 'look', 'sigh', 'scratch', 'yawn'] : ['look', 'look', 'shift', 'shift', 'watch', 'scratch', 'sigh', 'yawn'];
    const name = pool[Math.floor(Math.random() * pool.length)];
    if (name !== 'yawn' || Math.random() < .4) c.idle = { name, t0: T, dur: IDLE_DUR[name] };
    c.idleNext = T + 7 + Math.random() * 9;
  }
  if (c.idle) {
    const u = (T - c.idle.t0) / c.idle.dur;
    if (u >= 1 || !quiet) { c.idle = null; c.idleNext = Math.max(c.idleNext || 0, T + 4); }
    else IDLE[c.idle.name](B, add, u, Math.sin(Math.PI * u) ** .6, t, E);
  }
  const g = c.gesture;
  if (g) {
    const u = (T - g.t0) / g.dur, e = Math.sin(Math.PI * Math.min(1, Math.max(0, u)));
    if (u >= 1) c.gesture = null;
    else switch (g.name) {
      case 'wave': B('rightUpperArm', -.15, 0, -.35); B('rightLowerArm', 0, .3, -1.25 + .38 * Math.sin(t * 10)); add('head', 0, 0, .1); E.happy = .7; R.ry *= .3; break;
      case 'celebrate':
      case 'jump': {
        const crouch = u < .2 ? Math.sin(u / .2 * Math.PI) : u > .85 ? Math.sin((u - .85) / .15 * Math.PI) * .6 : 0;
        const air = u > .2 && u < .85 ? Math.sin((u - .2) / .65 * Math.PI) : 0;
        R.y += air * .32 - crouch * .07; R.k = 22;
        add('leftUpperLeg', -.5 * crouch - .3 * air); add('rightUpperLeg', -.5 * crouch - .3 * air);
        add('leftLowerLeg', 1.0 * crouch + .5 * air); add('rightLowerLeg', 1.0 * crouch + .5 * air);
        if (air > 0 || g.name === 'celebrate') { B('leftUpperArm', 0, 0, g.name === 'celebrate' ? 1.15 : .6); B('rightUpperArm', 0, 0, g.name === 'celebrate' ? -1.15 : -.6); }
        E.happy = g.name === 'celebrate' ? 1 : .6; break;
      }
      case 'dance': {
        const live = c.bpm && T - (c.lastBeat || 0) < 2.5;
        const bpm = live ? c.bpm : 112, phi = live ? (T - c.lastBeat) * bpm / 60 * Math.PI * 2 + Math.PI : (T - g.t0) * bpm / 60 * Math.PI * 2;
        if (c.mode === 'stand') { R.ry *= .25; dance(g.style || 'groove', phi, B, add, R, E, c); }
        else { add('head', .12 * (1 - Math.cos(phi)) / 2, 0, .08 * Math.sin(phi / 2)); E.happy = .6; }
        break;
      }
      case 'nod': B('head', .32 * Math.abs(Math.sin(u * Math.PI * 3)), 0, 0); R.k = 20; break;
      case 'shake': B('head', 0, .42 * Math.sin(u * Math.PI * 4) * (1 - u * .6), 0); R.k = 20; break;
      case 'bow': B('spine', .55 * e); B('chest', .2 * e); B('head', .25 * e); add('leftUpperArm', -.2 * e); add('rightUpperArm', -.2 * e); R.ry = 0; break;
      case 'think': B('rightUpperArm', -1.0, 0, 1.05); B('rightLowerArm', 0, 2.2); B('leftUpperArm', 0, -.9, -.9); B('leftLowerArm', 0, -1.4);
        B('head', -.12, .15, .12); break;
      case 'shrug': B('leftShoulder', 0, 0, .25 * e); B('rightShoulder', 0, 0, -.25 * e); B('leftUpperArm', -.2, 0, -.95); B('rightUpperArm', -.2, 0, .95);
        B('leftLowerArm', 0, -1.3 * e); B('rightLowerArm', 0, 1.3 * e); add('head', 0, 0, .18 * e); E.relaxed = .4; break;
      case 'clap': B('leftUpperArm', 0, -1.0, -.45); B('rightUpperArm', 0, 1.0, .45);
        B('leftLowerArm', 0, -(1.15 + .3 * Math.sin(t * 16))); B('rightLowerArm', 0, 1.15 + .3 * Math.sin(t * 16)); E.happy = .8; R.ry = 0; R.k = 22; break;
      case 'stretch': B('leftUpperArm', 0, 0, 1.3 * e - 1.22 * (1 - e)); B('rightUpperArm', 0, 0, -1.3 * e + 1.22 * (1 - e));
        B('leftLowerArm'); B('rightLowerArm'); B('spine', -.15 * e); B('chest', -.1 * e); B('head', -.2 * e); E.relaxed = .8; E.aa = .5 * e; break;
      case 'point': if ((c.dir || 1) > 0) { B('leftUpperArm', -.4, 0, 0); B('head', 0, .5, 0); } else { B('rightUpperArm', -.4, 0, 0); B('head', 0, -.5, 0); } R.ry = 0; break;
      case 'catch': B('leftUpperArm', -.9, 0, .25); B('rightUpperArm', -.9, 0, -.25); B('leftLowerArm', 0, -.9); B('rightLowerArm', 0, .9);
        B('head', .25 * e, 0, 0); E.happy = .6; E.surprised = .3 * e; break;
      case 'shiver': add('spine', 0, .05 * Math.sin(t * 40) * e, 0); add('head', 0, .04 * Math.sin(t * 37) * e, 0);
        B('leftUpperArm', -.5, -.5, -.8); B('rightUpperArm', -.5, .5, .8); B('leftLowerArm', 0, -1.9); B('rightLowerArm', 0, 1.9); break;
      case 'brush': keyArms(B, 1, u, [[0, A_REST], [.25, A_OVER], [.8, A_OVER], [1, A_REST]]);
        add('rightLowerArm', 0, .35 * Math.sin(t * 18) * e); add('head', .1 * e, 0, .1 * Math.sin(t * 9) * e); R.ry = 0; break;
      case 'puton':
        keyArms(B, 1, u, [[0, A_REST], [.4, A_OVER], [.7, A_EAR], [1, A_REST]]);
        keyArms(B, -1, u, [[0, A_REST], [.4, A_OVER], [.7, A_EAR], [1, A_REST]]);
        add('head', -.08 * e); E.happy = .4; R.ry = 0; break;
      case 'neckoff':
        keyArms(B, 1, u, [[0, A_REST], [.35, A_EAR], [.7, A_NECK], [1, A_REST]]);
        keyArms(B, -1, u, [[0, A_REST], [.35, A_EAR], [.7, A_NECK], [1, A_REST]]);
        add('head', .1 * e); R.ry = 0; break;
      case 'earbuds': {
        keyArms(B, 1, u, [[0, A_REST], [.18, A_POCKET], [.3, A_POCKET], [.5, A_EAR], [.62, A_EAR], [.8, A_REST], [1, A_REST]]);
        keyArms(B, -1, u, [[0, A_REST], [.55, A_REST], [.75, A_EAR], [.88, A_EAR], [1, A_REST]]);
        add('head', .12 * Math.sin(Math.min(1, u / .3) * Math.PI), u > .3 && u < .65 ? .12 : u > .65 ? -.12 * e : 0, 0); R.ry = 0; break;
      }
      case 'shy':
        keyArms(B, 1, u, [[0, A_REST], [.25, A_OVER], [.8, A_OVER], [1, A_REST]]);
        add('head', .28 * e, -.25 * e, .18 * e); add('spine', .06 * e); E.happy = .5 * e; E.relaxed = .4 * e; R.ry = 0; break;
      case 'balance': B('leftUpperArm', 0, 0, .05 + .25 * Math.sin(t * 7)); B('rightUpperArm', 0, 0, -.05 + .25 * Math.sin(t * 7)); B('leftLowerArm'); B('rightLowerArm');
        R.rz = .12 * Math.sin(t * 7) * e; E.surprised = .6; R.k = 16; break;
      case 'pose': window.nxPoseFn?.(B, add, u, e, E, R); break;
    }
  }
  if (T > c.emoUntil) c.emotion = 'neutral';
  const em = c.emotion;
  if (em !== 'neutral') {
    E[em] = Math.max(E[em] || 0, em === 'surprised' ? .9 : .85);
    if (em === 'sad' && !g) { add('head', .22); add('spine', .08); }
    if (em === 'surprised' && !g) add('head', -.08);
    if (em === 'happy' && !g) add('head', 0, 0, .06);
    if (em === 'angry' && !g && c.mode === 'stand') { B('leftUpperArm', .35, 0, -.9); B('rightUpperArm', .35, 0, .9); B('leftLowerArm', 0, -1.7); B('rightLowerArm', 0, 1.7); }
  }
  if (c.bpm && T - (c.lastBeat || 0) < 2.5 && !g && !speaking && (c.mode === 'stand' || c.mode === 'sit')) {
    const k = Math.exp(-(T - c.lastBeat) * 6);
    const deep = c.listen ? 1.8 : 1;
    add('head', .1 * k * deep, 0, .03 * deep * Math.sin((T - c.lastBeat) * c.bpm / 60 * Math.PI));
    if (c.listen) {
      const cyc = (T - (c.listenT || 0)) % 9;
      E.blink = Math.max(E.blink || 0, cyc > 7.6 ? .1 : .92); E.relaxed = Math.max(E.relaxed || 0, .55);
    }
    if (c.mode === 'stand') { add('leftLowerLeg', .12 * k); add('rightLowerLeg', .12 * k); R.y -= .008 * k; }
    else { add('leftLowerLeg', .15 * k); }
  }
  if (c.wobble) { const w = c.wobble * Math.exp(-(T - (c.wobbleT || 0)) * 2.5); R.rz += w * Math.sin(T * 9); if (Math.abs(w) > .04) { add('leftUpperArm', 0, 0, .5); add('rightUpperArm', 0, 0, -.5); } }
  if (companionCfg().look !== false && c.mode !== 'sleep' && !c.idle) add('head', -c.lookY * .2, c.lookX * .45 * (g ? .3 : 1), 0);
}

export async function startVRM(canvas, url, { snapshotName = null, ctl = makeCtl(), view = 'stage' } = {}) {
  const THREE = await import('three');
  const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js');
  const { VRMLoaderPlugin, VRMUtils } = await import('@pixiv/three-vrm');
  const c = companionCfg();
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: c.msaa !== false });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
  const scene = new THREE.Scene();
  const cam = new THREE.PerspectiveCamera(30, 1, .1, 20);
  if (view === 'desktop') { cam.position.set(0, .95, 4.2); cam.lookAt(0, .95, 0); }
  else { cam.position.set(0, 1.0, 3.8); cam.lookAt(0, 0.88, 0); }
  scene.add(new THREE.AmbientLight(0xffffff, .7)); const dl = new THREE.DirectionalLight(0xffffff, 1.4); dl.position.set(1, 2, 2); scene.add(dl);
  const loader = new GLTFLoader(); loader.register(p => new VRMLoaderPlugin(p));
  let vrm = null, alive = true, blinkT = 2, sign = 1, needSnap = !!snapshotName, baseRy = 0, hipsY = .9;
  canvas.addEventListener('pointermove', e => { if (view === 'desktop') return; const r = canvas.getBoundingClientRect();
    ctl.look((e.clientX - r.left) / r.width * 2 - 1, -((e.clientY - r.top) / r.height * 2 - 1)); });
  canvas.addEventListener('pointerleave', () => { if (view !== 'desktop') ctl.look(0, 0); });
  const cur = {}, P = {}, R = {}, E = {};
  const lookTarget = new THREE.Object3D(), sac = { x: 0, y: 0, next: 0 };
  let headInfo = null, accKey = '';
  const acc = {};
  function syncAccessories() {
    const want = {};
    for (const n of [...(ctl.weatherAcc || []), ...(companionCfg().accessories || []), ...(ctl.autoAcc || [])]) if (ACCESSORIES[n]) want[accSlot(n)] = n;
    const key = JSON.stringify(want);
    if (key === accKey || !headInfo) return;
    accKey = key;
    for (const s of Object.keys(acc)) if (acc[s].name !== want[s]) { disposeAccessory(acc[s].obj); delete acc[s]; }
    for (const [s, n] of Object.entries(want)) if (!acc[s]) acc[s] = { name: n, obj: makeAccessory(THREE, n, headInfo) };
  }
  let springWind = 0, springBase = null;
  function springs(dt) {
    const sbm = vrm?.springBoneManager;
    if (!sbm || !sbm.joints?.size) return;
    springBase = springBase || [...sbm.joints].map(j => [j, j.settings.gravityPower || 0, j.settings.dragForce || 0, j.settings.stiffness]);
    const vx = ctl.mode === 'drag' ? (ctl.dragVx || 0) : ctl.mode === 'walk' ? (ctl.dir || 0) * (ctl.walkSpeed || 90) : 0;
    springWind += (Math.max(-1, Math.min(1, -vx / 350)) - springWind) * Math.min(1, dt * 4);
    const w = springWind;
    for (const [j, g0, d0, s0] of springBase) {
      j.settings.gravityPower = Math.max(g0, .15) + Math.abs(w) * .9;
      j.settings.gravityDir.set(w * 1.6, -1, 0).normalize();
      j.settings.dragForce = Math.max(d0, .35);
      j.settings.stiffness = s0 * .7;
    }
  }
  const shCanvas = document.createElement('canvas'); shCanvas.width = shCanvas.height = 64;
  { const g = shCanvas.getContext('2d'), gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    gr.addColorStop(0, 'rgba(0,0,0,.55)'); gr.addColorStop(.55, 'rgba(0,0,0,.25)'); gr.addColorStop(1, 'rgba(0,0,0,0)'); g.fillStyle = gr; g.fillRect(0, 0, 64, 64); }
  const shadow = new THREE.Mesh(new THREE.PlaneGeometry(1, 1),
    new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(shCanvas), transparent: true, depthWrite: false }));
  shadow.rotation.x = -Math.PI / 2; shadow.position.y = .002; shadow.renderOrder = -1; scene.add(shadow);
  try {
    const gltf = await loader.loadAsync(url); vrm = gltf.userData.vrm;
    VRMUtils.removeUnnecessaryVertices(gltf.scene); VRMUtils.rotateVRM0(vrm); scene.add(vrm.scene);
    baseRy = vrm.scene.rotation.y;
    cam.add(lookTarget); scene.add(cam); if (vrm.lookAt) vrm.lookAt.target = lookTarget;
    const hum = vrm.humanoid, la = hum.getNormalizedBoneNode('leftUpperArm');
    if (la) {
      la.rotation.z = -1.2; vrm.update(0); vrm.scene.updateMatrixWorld(true);
      const hand = hum.getRawBoneNode('leftHand') || hum.getRawBoneNode('leftLowerArm'), sh = hum.getRawBoneNode('leftUpperArm');
      const ph = new THREE.Vector3(), ps = new THREE.Vector3();
      if (hand && sh) { hand.getWorldPosition(ph); sh.getWorldPosition(ps); if (ph.y > ps.y) sign = -1; }
      la.rotation.z = 0;
    }
    const hp = hum.getRawBoneNode('hips'); if (hp) { const v = new THREE.Vector3(); hp.getWorldPosition(v); hipsY = v.y; }
    try { headInfo = measureHead(THREE, vrm); } catch (e) { console.warn('accessories: head not measured', e); }
    canvas.dataset.engine = 'ready';
    canvas.dataset.sign = sign;
    ctl.vrm = vrm; ctl.scene3 = scene; ctl.cam = cam;
    try { const { makeClipPlayer } = await import('./anim.js'); ctl.clips = makeClipPlayer(vrm); }
    catch (e) { console.warn('mocap clips off', e); }
  } catch (e) { canvas.dataset.engine = 'ошибка: ' + e.message; console.error(e); }

  const v3 = new THREE.Vector3();
  const toScreen = (x, y, z) => { v3.set(x, y, z).project(cam); return [(v3.x + 1) / 2 * canvas.clientWidth, (1 - v3.y) / 2 * canvas.clientHeight]; };
  const clock = new THREE.Clock(); let last = 0;
  function apply() {
    const cc = companionCfg(); if (!vrm) return;
    vrm.scene.scale.setScalar(cc.scale ?? 1);
    vrm.scene.traverse(o => { if (o.material) [].concat(o.material).forEach(m => { if ('outlineWidthFactor' in m) m.outlineWidthFactor = (cc.outline ?? 0) / 1000; }); });
  }
  function frame(now) {
    if (!alive) return; requestAnimationFrame(frame);
    if (!canvas.isConnected) { alive = false; renderer.dispose(); return; }
    if (!canvas.offsetParent && !needSnap || now - last < 1000 / (companionCfg().fps || 30)) return; last = now;
    const w = canvas.clientWidth || 300, hgt = canvas.clientHeight || 400;
    if (canvas.width !== Math.round(w * renderer.getPixelRatio())) { renderer.setSize(w, hgt, false); cam.aspect = w / hgt; cam.updateProjectionMatrix(); }
    const dt = Math.min(.1, clock.getDelta()), t = clock.elapsedTime;
    if (vrm) {
      for (const k in P) delete P[k]; for (const k in E) delete E[k];
      const sc = companionCfg().scale ?? 1;
      ctl.legPx = toScreen(0, 0, 0)[1] - toScreen(0, hipsY * sc, 0)[1];
      pose(ctl, t, dt, P, R, E);
      syncAccessories();
      const k = 1 - Math.exp(-dt * R.k);
      for (const n of BONES) {
        const node = vrm.humanoid.getNormalizedBoneNode(n); if (!node) continue;
        const tg = P[n] || [0, 0, 0], cv = cur[n] || (cur[n] = [0, 0, 0]);
        for (let i = 0; i < 3; i++) cv[i] += (tg[i] - cv[i]) * k;
        node.rotation.set(sign * cv[0], cv[1], sign * cv[2]);
      }
      cur.root = cur.root || { x: 0, y: 0, ry: 0, rz: 0 };
      for (const q of ['x', 'y', 'ry', 'rz']) cur.root[q] += ((R[q] || 0) - cur.root[q]) * k;
      vrm.scene.position.x = cur.root.x; vrm.scene.position.y = cur.root.y; vrm.scene.rotation.y = baseRy + cur.root.ry; vrm.scene.rotation.z = cur.root.rz;
      if (ctl.clips) {
        const pl = ctl.clips.playing();
        if (pl && ctl.mode !== 'stand' && !(ctl.mode === 'sit' && pl.upper)) ctl.clips.stop(.25);
        ctl.clips.apply(dt);
      }
      const onFloor = ctl.mode === 'stand' || ctl.mode === 'walk';
      shadow.visible = onFloor && companionCfg().shadow !== false;
      if (shadow.visible) {
        const air = Math.max(0, cur.root.y) * 3, w = .62 * sc * (1 - Math.min(.6, air));
        shadow.scale.set(w, w * .8, 1); shadow.position.x = cur.root.x; shadow.material.opacity = .9 * (1 - Math.min(.7, air));
      }
      const T = performance.now() / 1000;
      if (T > sac.next) { sac.x = (Math.random() - .5) * .16; sac.y = (Math.random() - .5) * .1; sac.next = T + .7 + Math.random() * 2.2; }
      const think = state.orb === 'thinking' || ctl.gesture?.name === 'think';
      lookTarget.position.set(think ? .45 : ctl.lookX * .9 + sac.x, think ? .35 : ctl.lookY * .6 + sac.y, 0);
      const em = vrm.expressionManager;
      if (em) {
        blinkT -= dt; const bl = blinkT < .12 ? Math.sin((blinkT / .12) * Math.PI) : 0;
        if (blinkT < 0) blinkT = state.orb === 'speaking' ? 1.2 + Math.random() * 2 : 2 + Math.random() * 3.5;
        const lvl = state.orb === 'speaking' ? Math.min(1, state.level * 2.2) : 0, vis = Math.floor(T * 7.3) % 3;
        const tgt = { blink: Math.max(E.blink || 0, bl), aa: Math.max(E.aa || 0, lvl * (vis === 0 ? 1 : .5)),
          oh: lvl * (vis === 1 ? .75 : 0), ih: lvl * (vis === 2 ? .6 : 0),
          happy: E.happy || 0, sad: E.sad || 0, angry: E.angry || 0, surprised: E.surprised || 0, relaxed: E.relaxed || 0 };
        cur.expr = cur.expr || {};
        for (const [n, val] of Object.entries(tgt)) {
          const smooth = n === 'blink' ? val : ['aa', 'oh', 'ih'].includes(n) ? (cur.expr[n] || 0) + (val - (cur.expr[n] || 0)) * Math.min(1, dt * 22) : (cur.expr[n] || 0) + (val - (cur.expr[n] || 0)) * Math.min(1, dt * 6);
          if (!cur.exprName) {
            cur.exprName = {};
            const have = em.expressions.map(x => x.expressionName), low = Object.fromEntries(have.map(x => [x.toLowerCase(), x]));
            const alt = { happy: ['joy', 'fun'], relaxed: ['fun', 'joy'], sad: ['sorrow'], surprised: ['surprise'] };
            for (const k of ['aa', 'ih', 'ou', 'ee', 'oh', 'blink', 'happy', 'sad', 'angry', 'surprised', 'relaxed'])
              cur.exprName[k] = low[k] || (alt[k] || []).map(a => low[a]).find(Boolean) || null;
          }
          cur.expr[n] = smooth; if (cur.exprName[n]) em.setValue(cur.exprName[n], smooth);
        }
      }
      springs(dt);
      vrm.update(dt);
    }
    renderer.render(scene, cam);
    if (needSnap && vrm && t > 1.2) {
      needSnap = false;
      canvas.toBlob(bl => bl && fetch('/api/avatars/thumb?name=' + encodeURIComponent(snapshotName), { method: 'POST', body: bl }), 'image/png');
    }
  }
  requestAnimationFrame(frame); apply();
  const tmp = new THREE.Vector3();
  Object.assign(ctl, {
    stop: () => { alive = false; renderer.dispose(); },
    apply,
    bounds: () => {
      if (!vrm) return null;
      let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      for (const n of ['head', 'leftHand', 'rightHand', 'leftFoot', 'rightFoot', 'leftLowerArm', 'rightLowerArm', 'hips', 'leftToes', 'rightToes']) {
        const b = vrm.humanoid.getRawBoneNode(n); if (!b) continue;
        b.getWorldPosition(tmp); const [sx, sy] = toScreen(tmp.x, tmp.y, tmp.z);
        x0 = Math.min(x0, sx); x1 = Math.max(x1, sx); y0 = Math.min(y0, sy); y1 = Math.max(y1, sy);
        if (n === 'head') { const [, ty] = toScreen(tmp.x, tmp.y + .22 * (companionCfg().scale ?? 1), tmp.z); y0 = Math.min(y0, ty); }
      }
      const pad = 22;
      return [x0 - pad, y0 - pad, x1 - x0 + pad * 2, y1 - y0 + pad * 2];
    },
    anchor: (m = ctl.mode) => {
      const s = companionCfg().scale ?? 1;
      return toScreen(0, (m === 'sit' || m === 'sleep') ? (hipsY - .1) * s : 0, 0)[1];
    },
  });
  return ctl;
}
