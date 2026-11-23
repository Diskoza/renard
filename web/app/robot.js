import { state } from './core.js';
import { FACES, EMO_FACE, drawFace } from './robotface.js';

const EARS = {
  sad: [.5, .35], cry: [.55, .4], sleep: [.45, .3], shy: [.3, .2], broken: [.35, .1, 0, .35],
  angry: [.22, .5],
  happy: [-.06, -.04, .06], laugh: [-.08, -.06, .1], hello: [-.06, -.04, .08], love: [-.05, -.08, .05],
  tender: [.02, -.04, .03], wow: [-.04, -.06, .04], money: [-.06, -.04, .05],
  shocked: [-.12, -.14], big_eyes: [-.1, -.12], alert: [-.14, -.1],
  question: [.04, 0, 0, .32], suspicious: [.12, .2, 0, -.22], sly: [.08, .12, 0, .18],
  calm: [.08, .05], neutral: [.05, 0], logo: [0, 0],
};
const ENGINES = { sad: -.13, cry: -.14, sleep: -.1, shy: -.06, angry: .05, happy: .1, laugh: .12, hello: .09, love: .06,
  shocked: .15, big_eyes: .1, alert: .14, wow: .06 };

export async function startRobot(canvas, url, { ctl, view = 'stage', cfg = {}, snapshotName = null } = {}) {
  let needSnap = !!snapshotName;
  const THREE = await import('three');
  const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js');
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
  const scene = new THREE.Scene();
  const cam = new THREE.PerspectiveCamera(30, 1, .1, 20);
  if (view === 'desktop') { cam.position.set(0, .95, 4.2); cam.lookAt(0, .95, 0); } else { cam.position.set(0, 1.0, 3.8); cam.lookAt(0, .88, 0); }
  scene.add(new THREE.AmbientLight(0xffffff, 1.1)); const dl = new THREE.DirectionalLight(0xffffff, 1.2); dl.position.set(1, 2, 3); scene.add(dl);
  const root = new THREE.Group(); scene.add(root);
  let model = null, alive = true;
  const parts = { ears: [], sides: [], nozzles: [] };
  const fc = document.createElement('canvas'); fc.width = fc.height = 160;
  const fctx = fc.getContext('2d');
  const ftex = new THREE.CanvasTexture(fc); ftex.colorSpace = THREE.SRGBColorSpace; ftex.generateMipmaps = false;
  ftex.minFilter = THREE.LinearFilter; ftex.magFilter = THREE.LinearFilter;
  const face = { name: 'neutral', until: 0, red: !!cfg.red, blinkT: 3, shown: '' };

  const glowTex = (() => {
    const c = document.createElement('canvas'); c.width = c.height = 64; const g = c.getContext('2d');
    const r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    r.addColorStop(0, 'rgba(255,255,255,1)'); r.addColorStop(.25, 'rgba(150,245,255,.9)'); r.addColorStop(1, 'rgba(40,180,255,0)');
    g.fillStyle = r; g.fillRect(0, 0, 64, 64); return new THREE.CanvasTexture(c);
  })();
  const pixTex = (() => {
    const c = document.createElement('canvas'); c.width = c.height = 16; const g = c.getContext('2d');
    g.fillStyle = 'rgba(120,240,255,.35)'; g.fillRect(0, 0, 16, 16); g.fillStyle = '#c8fbff'; g.fillRect(3, 3, 10, 10);
    const t = new THREE.CanvasTexture(c); t.magFilter = THREE.NearestFilter; return t;
  })();
  const glowMat = (op) => new THREE.SpriteMaterial({ map: glowTex, color: 0x9ff6ff, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, opacity: op });
  const particles = [];
  for (let i = 0; i < 36; i++) {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: pixTex, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true }));
    s.visible = false; scene.add(s); particles.push({ s, life: 0, v: new THREE.Vector3() });
  }
  let pIdx = 0;
  const emit = (pos, dir, speed, size) => {
    const p = particles[pIdx++ % particles.length];
    p.s.position.copy(pos); p.v.copy(dir).multiplyScalar(speed).add(new THREE.Vector3((Math.random() - .5) * .15, (Math.random() - .5) * .1, (Math.random() - .5) * .15));
    p.life = 1; p.size = size; p.s.visible = true;
  };

  const pivotAt = (obj, pick) => {
    const b = new THREE.Box3().setFromObject(obj), p = new THREE.Object3D();
    root.add(p); p.position.copy(root.worldToLocal(pick(b))); p.updateMatrixWorld(true); p.attach(obj);
    p.userData = { side: Math.sign(p.position.x) || 1, a: 0, v: 0, b: 0, bv: 0 };
    return p;
  };
  const group = (prefix) => { let g = null; model.traverse(o => { if (!g && new RegExp(`^${prefix}_\\d+$`).test(o.name || '') && !new RegExp(`^${prefix}_`).test(o.parent?.name || '')) g = o; }); return g; };
  try {
    const gltf = await new GLTFLoader().loadAsync(url);
    model = gltf.scene;
    model.traverse(o => { if (o.material) [].concat(o.material).forEach(m => { if (m.map) { m.map.magFilter = THREE.NearestFilter; m.map.minFilter = THREE.NearestFilter; } }); });
    model.rotation.y = Math.PI;
    root.add(model); root.updateMatrixWorld(true);
    let box = new THREE.Box3().setFromObject(model);
    const s = 1.3 / (box.max.y - box.min.y || 1);
    model.scale.setScalar(s); root.updateMatrixWorld(true);
    box = new THREE.Box3().setFromObject(model);
    const c = box.getCenter(new THREE.Vector3());
    model.position.x -= c.x; model.position.z -= c.z; model.position.y -= box.min.y - .18;
    root.updateMatrixWorld(true);
    const V = (x, y, z) => new THREE.Vector3(x, y, z);
    const scr = model.getObjectByName('body_0'), bot = model.getObjectByName('body_1'), top = model.getObjectByName('body_2');
    let plane = null;
    if (scr) {
      const sb = new THREE.Box3().setFromObject(scr);
      const y0 = bot ? new THREE.Box3().setFromObject(bot).max.y : sb.min.y, y1 = top ? new THREE.Box3().setFromObject(top).min.y : sb.max.y;
      plane = new THREE.Mesh(new THREE.PlaneGeometry(sb.max.x - sb.min.x, y1 - y0), new THREE.MeshBasicMaterial({ map: ftex, toneMapped: false }));
      plane.position.set((sb.min.x + sb.max.x) / 2, (y0 + y1) / 2, sb.max.z + .004);
    } else {
      const eyes = []; model.traverse(o => { if (/^eyes/i.test(o.name || '')) eyes.push(o); });
      if (eyes.length) {
        const eb = new THREE.Box3(); eyes.forEach(e => eb.expandByObject(e));
        const w = (eb.max.x - eb.min.x) * 1.55;
        plane = new THREE.Mesh(new THREE.PlaneGeometry(w, w), new THREE.MeshBasicMaterial({ map: ftex, toneMapped: false }));
        const ec = eb.getCenter(V()); plane.position.set(ec.x, ec.y, eb.max.z + .004);
      }
    }
    if (plane) {
      model.traverse(o => { if (/^eyes/i.test(o.name || '')) o.visible = false; });
      root.add(plane); model.attach(plane);
    }
    ['ear1', 'ear2'].forEach(n => { const g = group(n); if (g) parts.ears.push(pivotAt(g, b => V((b.min.x + b.max.x) / 2, b.min.y, (b.min.z + b.max.z) / 2))); });
    ['engine1', 'engine2'].forEach(n => {
      const g = group(n); if (!g) return;
      const p = pivotAt(g, b => V(Math.abs(b.min.x) < Math.abs(b.max.x) ? b.min.x : b.max.x, (b.min.y + b.max.y) / 2, (b.min.z + b.max.z) / 2));
      const b = new THREE.Box3().setFromObject(g);
      const glow = new THREE.Sprite(glowMat(.75)); glow.position.copy(V((b.min.x + b.max.x) / 2 + p.userData.side * .02, b.max.y - .08, b.min.z));
      root.add(glow); p.attach(glow);
      parts.sides.push(p); parts.nozzles.push({ glow, size: .16, dir: V(0, -.25, -1).normalize(), speed: .5, rate: 5 });
    });
    const b3 = group('engine3');
    if (b3) {
      const b = new THREE.Box3().setFromObject(b3);
      const glow = new THREE.Sprite(glowMat(.9)); glow.position.set((b.min.x + b.max.x) / 2, b.min.y - .02, (b.min.z + b.max.z) / 2);
      root.add(glow); model.attach(glow);
      parts.nozzles.push({ glow, size: .26, dir: V(0, -1, 0), speed: .9, rate: 14, main: true });
    }
    canvas.dataset.engine = 'ready';
    ctl.robot = { model, FACES };
  } catch (e) { canvas.dataset.engine = 'ошибка: ' + e.message; console.error(e); }

  ctl.showFace = (name, sec = 6) => { if (FACES[name]) { face.name = name; face.until = performance.now() / 1000 + sec; } };
  ctl.setRed = (on) => { face.red = !!on; };
  const v3 = new THREE.Vector3(), wp = new THREE.Vector3(), wd = new THREE.Vector3(), q = new THREE.Quaternion();
  const toScreen = (x, y, z) => { v3.set(x, y, z).project(cam); return [(v3.x + 1) / 2 * canvas.clientWidth, (1 - v3.y) / 2 * canvas.clientHeight]; };
  const spring = (u, target, dt, k = 140, d = 13) => { u.v += (k * (target - u.a) - d * u.v) * dt; u.a += u.v * dt; return u.a; };
  const clock = new THREE.Clock(); let last = 0, ry = 0, spinV = 0, emitAcc = 0;
  function frame(now) {
    if (!alive) return; requestAnimationFrame(frame);
    if (!canvas.isConnected) { alive = false; renderer.dispose(); return; }
    if (now - last < 1000 / 30) return; last = now;
    const w = canvas.clientWidth || 300, h = canvas.clientHeight || 400;
    if (canvas.width !== Math.round(w * renderer.getPixelRatio())) { renderer.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix(); }
    const dt = Math.min(.1, clock.getDelta()), t = clock.elapsedTime, T = performance.now() / 1000;
    if (model) {
      root.scale.setScalar(cfg.scale ?? 1);
      const g = ctl.gesture, gu = g ? (T - g.t0) / g.dur : 1;
      if (g && gu >= 1) ctl.gesture = null;
      const emo = T < ctl.emoUntil ? ctl.emotion : 'neutral';
      face.blinkT -= dt;
      const blink = face.blinkT < .12;
      if (face.blinkT < 0) face.blinkT = 2.5 + Math.random() * 3.5;
      let fname = T < face.until ? face.name : EMO_FACE[emo] || 'neutral';
      if (ctl.mode === 'sleep') fname = 'sleep';
      else if (T >= face.until && emo === 'neutral') {
        if (state.orb === 'thinking') fname = 'calm';
        else if (state.orb === 'listening') fname = 'big_eyes';
      }
      if (g && T >= face.until) fname = { celebrate: 'laugh', clap: 'happy', wave: 'hello', shrug: 'question', think: 'calm', shy: 'shy' }[g.name] || fname;
      const red = face.red || (fname === 'angry' && cfg.redAngry !== false);
      if (fname !== face.shown) {
        face.shown = fname;
        parts.ears.forEach((p, i) => { p.userData.v += (i ? 1 : -1) * 1.6; });
        parts.sides.forEach(p => { p.userData.v -= 1.2; });
      }
      let y = .05 * Math.sin(t * 1.7), rz = .025 * Math.sin(t * 1.1), x = 0, rx = 0;
      if (ctl.mode === 'sit' || ctl.mode === 'sleep') y = -.1 + .02 * Math.sin(t * 1.2);
      if (ctl.mode === 'walk') rz += -.12 * (ctl.dir || 0);
      if (ctl.mode === 'drag') rz += Math.max(-.5, Math.min(.5, -(ctl.dragVx || 0) * .0015));
      if (g?.name === 'jump' || g?.name === 'celebrate') y += .45 * Math.max(0, Math.sin(Math.PI * Math.min(1, gu)));
      if (g?.name === 'shake') x += .08 * Math.sin(gu * Math.PI * 8) * (1 - gu);
      if (g?.name === 'wave' || g?.name === 'clap') rz += .12 * Math.sin(gu * Math.PI * 6) * (1 - gu);
      if (g?.name === 'shrug') rz += .1 * Math.sin(Math.PI * Math.min(1, gu)), y += .05 * Math.sin(Math.PI * Math.min(1, gu));
      if (g?.name === 'nod' || g?.name === 'bow') rx = .25 * Math.sin(Math.PI * Math.min(1, gu * 2));
      if (fname === 'sad' || fname === 'cry') rx += .08, y -= .04;
      if (fname === 'shocked' || fname === 'alert') y += .03;
      const busy = state.orb === 'thinking' || g?.name === 'think' || g?.name === 'dance' || g?.name === 'celebrate';
      spinV += ((busy ? 3.2 : 0) - spinV) * Math.min(1, dt * 2.5);
      ry += spinV * dt;
      if (!busy) ry += (Math.round(ry / (Math.PI * 2)) * Math.PI * 2 - ry) * Math.min(1, dt * 3);
      const look = ctl.dir ? ctl.dir * .5 : ctl.lookX * .35;
      root.position.set(x, y, 0); root.rotation.y = ry + look; root.rotation.z = rz;
      root.rotation.x += (rx - root.rotation.x) * Math.min(1, dt * 6);
      const [spread, back, bounce = 0, tilt = 0] = EARS[fname] || EARS.neutral;
      parts.ears.forEach((p, i) => {
        const u = p.userData, side = u.side;
        const b = bounce ? bounce * Math.max(0, Math.sin(t * 9 + i)) : .015 * Math.sin(t * 1.3 + i * 2);
        const target = spread + b + (i === 0 ? tilt : 0);
        p.rotation.z = -side * spring(u, target, dt);
        u.bv = u.bv || 0; u.bb = u.bb ?? 0;
        u.bv += (140 * (-back - u.bb) - 13 * u.bv) * dt; u.bb += u.bv * dt;
        p.rotation.x = u.bb;
      });
      const pitch = ENGINES[fname] ?? 0;
      parts.sides.forEach((p, i) => {
        const u = p.userData;
        const target = pitch + .02 * Math.sin(t * 1.4 + i * 1.7) + (red ? .03 * Math.sin(t * 17 + i) : 0);
        p.rotation.x = Math.max(-.18, Math.min(.18, spring(u, target, dt, 90, 11)));
      });
      const thrust = 1 + (ctl.mode === 'walk' || ctl.mode === 'drag' ? .6 : 0) + (g?.name === 'jump' || g?.name === 'celebrate' ? 1 : 0) + (busy ? .4 : 0) - (ctl.mode === 'sleep' ? .5 : 0);
      emitAcc += dt;
      parts.nozzles.forEach(n => {
        const fl = .85 + .15 * Math.sin(t * 31 + n.size * 50) + .08 * Math.sin(t * 13);
        n.glow.scale.setScalar(n.size * fl * (.8 + .2 * thrust));
        n.glow.material.color.set(red ? 0xff5040 : 0x9ff6ff);
        if (Math.random() < n.rate * thrust * dt) {
          n.glow.getWorldPosition(wp); n.glow.getWorldQuaternion(q);
          wd.copy(n.dir); if (!n.main) wd.applyQuaternion(q); emit(wp, wd, n.speed * (.7 + .3 * thrust), n.main ? .045 : .03);
        }
      });
      particles.forEach(p => {
        if (p.life <= 0) return;
        p.life -= dt * 1.8; if (p.life <= 0) { p.s.visible = false; return; }
        p.s.position.addScaledVector(p.v, dt); p.s.scale.setScalar(p.size * (.4 + .6 * p.life));
        p.s.material.opacity = p.life; p.s.material.color.set(red ? 0xff6050 : 0xffffff);
      });
      const talk = state.orb === 'speaking' ? Math.min(1, state.level * 2.2) : 0;
      drawFace(fctx, fname, { red, blink, talk, t });
      ftex.needsUpdate = true;
    }
    renderer.render(scene, cam);
    if (needSnap && model && t > 1.2) {
      needSnap = false;
      canvas.toBlob(bl => bl && fetch('/api/avatars/thumb?name=' + encodeURIComponent(snapshotName), { method: 'POST', body: bl }), 'image/png');
    }
  }
  requestAnimationFrame(frame);
  const tmp = new THREE.Box3();
  Object.assign(ctl, {
    stop: () => { alive = false; renderer.dispose(); },
    apply: () => {},
    bounds: () => {
      if (!model) return null;
      tmp.setFromObject(model);
      const pts = [[tmp.min.x, tmp.min.y], [tmp.max.x, tmp.max.y], [tmp.min.x, tmp.max.y], [tmp.max.x, tmp.min.y]].map(([a, b]) => toScreen(a, b, 0));
      const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]), pad = 18;
      return [Math.min(...xs) - pad, Math.min(...ys) - pad, Math.max(...xs) - Math.min(...xs) + pad * 2, Math.max(...ys) - Math.min(...ys) + pad * 2];
    },
    anchor: () => toScreen(0, 0, 0)[1],
  });
  return ctl;
}
