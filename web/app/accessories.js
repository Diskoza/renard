export const ACCESSORIES = {
  beanie: 'шапка', santa: 'новогодняя шапка', cap: 'кепка', headphones: 'наушники', glasses: 'очки',
  sunglasses: 'тёмные очки', crown: 'корона', cat_ears: 'кошачьи ушки', flower: 'цветок', scarf: 'шарф',
  earbuds: 'вкладыши', headphones_neck: 'наушники на шее',
};
const HEAD_SLOT = { beanie: 'top', santa: 'top', cap: 'top', crown: 'top', cat_ears: 'top', glasses: 'eyes', sunglasses: 'eyes',
  headphones: 'ears', earbuds: 'ears', headphones_neck: 'ears' };
export const accSlot = (n) => HEAD_SLOT[n] || n;

export function measureHead(THREE, vrm) {
  const hum = vrm.humanoid, head = hum.getRawBoneNode('head');
  if (!head) return null;
  vrm.update(0); vrm.scene.updateMatrixWorld(true);
  const desc = new Set(); head.traverse(o => desc.add(o));
  const box = new THREE.Box3(), v = new THREE.Vector3(), face = [], all = [];
  vrm.scene.traverse(m => {
    if (!m.isSkinnedMesh || !m.geometry.attributes.skinIndex) return;
    const si = m.geometry.attributes.skinIndex, sw = m.geometry.attributes.skinWeight, n = si.count;
    const bones = m.skeleton.bones, step = n > 60000 ? 2 : 1;
    for (let i = 0; i < n; i += step) {
      let best = 0, bw = -1;
      for (let j = 0; j < 4; j++) { const w = sw.getComponent(i, j); if (w > bw) { bw = w; best = si.getComponent(i, j); } }
      if (!desc.has(bones[best])) continue;
      m.getVertexPosition(i, v); v.applyMatrix4(m.matrixWorld); box.expandByPoint(v); all.push(v.x, v.y, v.z);
      if (bones[best] === head) face.push(v.x, v.y, v.z);
    }
  });
  if (box.isEmpty()) return null;
  const size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
  const le = hum.getRawBoneNode('leftEye'), re = hum.getRawBoneNode('rightEye');
  let eyeY = box.min.y + size.y * .42, eyeDist = size.x * .36, eyeZ = box.max.z;
  if (le && re) {
    const a = le.getWorldPosition(new THREE.Vector3()), b = re.getWorldPosition(new THREE.Vector3());
    eyeY = (a.y + b.y) / 2; eyeDist = Math.max(.03, Math.abs(a.x - b.x)); eyeZ = Math.max(a.z, b.z) + size.z * .12;
  }
  eyeDist = Math.max(eyeDist, size.x * .4);
  let front = -Infinity; const fr = [-Infinity, -Infinity];
  for (let i = 0; i < face.length; i += 3) {
    if (Math.abs(face[i + 1] - eyeY) > size.y * .07) continue;
    const dx = face[i] - c.x;
    if (Math.abs(dx) < eyeDist * .9) front = Math.max(front, face[i + 2]);
    for (const [k, s] of [[0, -1], [1, 1]]) if (Math.abs(dx - s * eyeDist / 2) < eyeDist * .25) fr[k] = Math.max(fr[k], face[i + 2]);
  }
  if (!isFinite(front)) front = Math.min(box.max.z, eyeZ + size.z * .1);
  const lensZ = fr.map(z => (isFinite(z) ? z : front) + size.z * .025);
  const ears = [null, null];
  for (let i = 0; i < face.length; i += 3) {
    const y = face[i + 1];
    if (y > eyeY - size.y * .02 || y < eyeY - size.y * .22) continue;
    const k = face[i] < c.x ? 0 : 1, dx = Math.abs(face[i] - c.x);
    if (!ears[k] || dx > ears[k].dx) ears[k] = { dx, x: face[i], y, z: face[i + 2] };
  }
  const earY = ears[0] && ears[1] ? (ears[0].y + ears[1].y) / 2 : eyeY - size.y * .1;
  let sideHalf = 0, earZ = 0, nz = 0;
  for (let i = 0; i < all.length; i += 3) {
    if (Math.abs(all[i + 1] - earY) > size.y * .05) continue;
    sideHalf = Math.max(sideHalf, Math.abs(all[i] - c.x));
  }
  for (const e of ears) if (e) { earZ += e.z; nz++; }
  earZ = nz ? earZ / nz : c.z;
  const neck = hum.getRawBoneNode('neck') || head;
  return { head, neck, box, size, c, eyeY, eyeDist, eyeZ, front: front + size.z * .02, lensZ, ears, earY, earZ,
           sideHalf: sideHalf || size.x * .5,
           headRest: head.matrixWorld.clone(), neckRest: neck.matrixWorld.clone(), neckPos: neck.getWorldPosition(new THREE.Vector3()) };
}

const mat = (THREE, color, o = {}) => new THREE.MeshLambertMaterial({ color, ...o });

const BUILD = {
  beanie(THREE, h, col = 0x3f6fb5) {
    const g = new THREE.Group(), r = Math.max(h.size.x, h.size.z) * .55, base = h.box.max.y - h.size.y * .3;
    const dome = new THREE.Mesh(new THREE.SphereGeometry(r, 28, 14, 0, Math.PI * 2, 0, Math.PI / 2), mat(THREE, col));
    dome.scale.set(1, .95, h.size.z / h.size.x * .98); dome.position.set(h.c.x, base, h.c.z);
    const band = new THREE.Mesh(new THREE.CylinderGeometry(r * 1.04, r * 1.06, h.size.y * .13, 28, 1, true), mat(THREE, 0x2a4f8a, { side: THREE.DoubleSide }));
    band.scale.z = dome.scale.z; band.position.set(h.c.x, base + h.size.y * .04, h.c.z);
    const pom = new THREE.Mesh(new THREE.SphereGeometry(r * .24, 14, 10), mat(THREE, 0xf2f2f2));
    pom.position.set(h.c.x, base + r * .95 + r * .12, h.c.z);
    g.add(dome, band, pom); return g;
  },
  santa(THREE, h) {
    const g = new THREE.Group(), r = Math.max(h.size.x, h.size.z) * .53, base = h.box.max.y - h.size.y * .28;
    const cone = new THREE.Mesh(new THREE.ConeGeometry(r, h.size.y * .95, 28, 1, true), mat(THREE, 0xc8202a, { side: THREE.DoubleSide }));
    cone.position.set(h.c.x, base + h.size.y * .47, h.c.z); cone.rotation.z = -.35; cone.position.x += h.size.y * .15;
    const band = new THREE.Mesh(new THREE.TorusGeometry(r * 1.0, r * .14, 10, 30), mat(THREE, 0xf4f4f4));
    band.rotation.x = Math.PI / 2; band.scale.y = h.size.z / h.size.x; band.position.set(h.c.x, base + h.size.y * .02, h.c.z);
    const pom = new THREE.Mesh(new THREE.SphereGeometry(r * .2, 12, 10), mat(THREE, 0xf4f4f4));
    pom.position.set(h.c.x + h.size.y * .47, base + h.size.y * .85, h.c.z);
    g.add(cone, band, pom); return g;
  },
  cap(THREE, h) {
    const g = new THREE.Group(), r = Math.max(h.size.x, h.size.z) * .54, base = h.box.max.y - h.size.y * .26;
    const dome = new THREE.Mesh(new THREE.SphereGeometry(r, 28, 12, 0, Math.PI * 2, 0, Math.PI / 2), mat(THREE, 0x222428));
    dome.scale.set(1, .7, h.size.z / h.size.x); dome.position.set(h.c.x, base, h.c.z);
    const visor = new THREE.Mesh(new THREE.CylinderGeometry(r * .75, r * .75, r * .05, 24, 1, false, -Math.PI / 2, Math.PI), mat(THREE, 0xd97757));
    visor.scale.z = 1.1; visor.position.set(h.c.x, base + r * .02, h.c.z + h.size.z * .38);
    g.add(dome, visor); return g;
  },
  headphones(THREE, h) {
    const g = new THREE.Group(), earY = (h.earY ?? h.eyeY - h.size.y * .08) + h.size.y * .04, th = h.size.x * .11;
    const half = (h.sideHalf ?? h.size.x * .5) + th * .15, R = h.box.max.y - earY, z = (h.earZ ?? h.c.z) + h.size.z * .1;
    const band = new THREE.Mesh(new THREE.TorusGeometry(R, h.size.x * .03, 8, 32, Math.PI), mat(THREE, 0x1d1d1f));
    band.scale.x = half / R; band.position.set(h.c.x, earY, z);
    g.add(band);
    for (const s of [-1, 1]) {
      const cup = new THREE.Mesh(new THREE.CylinderGeometry(h.size.y * .115, h.size.y * .115, th, 24), mat(THREE, 0xd97757));
      cup.rotation.z = Math.PI / 2; cup.position.set(h.c.x + s * half, earY, z); g.add(cup);
      const pad = new THREE.Mesh(new THREE.TorusGeometry(h.size.y * .1, h.size.x * .022, 8, 20), mat(THREE, 0x1d1d1f));
      pad.rotation.y = Math.PI / 2; pad.position.set(h.c.x + s * (half - th * .5), earY, z); g.add(pad);
    }
    return g;
  },
  earbuds(THREE, h) {
    const g = new THREE.Group(), white = mat(THREE, 0xf4f4f6), r = h.size.x * .026;
    for (const [k, s] of [[0, -1], [1, 1]]) {
      const e = h.ears?.[k];
      const x = e ? e.x - s * r * .55 : h.c.x + s * h.size.x * .38, y = e ? e.y : h.eyeY - h.size.y * .1;
      const z = e ? e.z - r * .4 : h.c.z;
      const bud = new THREE.Mesh(new THREE.SphereGeometry(r, 14, 10), white);
      bud.scale.set(.75, 1, 1); bud.position.set(x, y, z); g.add(bud);
      const stem = new THREE.Mesh(new THREE.CylinderGeometry(r * .32, r * .26, h.size.y * .07, 8), white);
      stem.position.set(x + s * r * .2, y - h.size.y * .04, z + r * .5); stem.rotation.x = -.15; g.add(stem);
    }
    return g;
  },
  headphones_neck(THREE, h) {
    const g = new THREE.Group(), p = h.neckPos, r = h.size.x * .45, y = p.y + h.size.y * .06;
    const band = new THREE.Mesh(new THREE.TorusGeometry(r, h.size.x * .035, 8, 28, Math.PI), mat(THREE, 0x1d1d1f));
    band.rotation.x = Math.PI / 2; band.rotation.z = Math.PI; band.scale.y = h.size.z / h.size.x * 1.1;
    band.position.set(p.x, y + h.size.y * .04, p.z); g.add(band);
    for (const s of [-1, 1]) {
      const cup = new THREE.Mesh(new THREE.CylinderGeometry(h.size.y * .11, h.size.y * .11, h.size.x * .1, 20), mat(THREE, 0xd97757));
      cup.rotation.order = 'YZX'; cup.rotation.z = Math.PI / 2 - s * .45; cup.rotation.y = -s * .5;
      cup.position.set(p.x + s * r * .78, y - h.size.y * .04, p.z + h.size.z * .22);
      g.add(cup);
    }
    return g;
  },
  glasses(THREE, h, dark = false) {
    const g = new THREE.Group(), rr = h.eyeDist * .4, frameM = mat(THREE, dark ? 0x111111 : 0x2b2b2b);
    for (const [k, s] of [[0, -1], [1, 1]]) {
      const lens = new THREE.Group();
      const rim = new THREE.Mesh(new THREE.TorusGeometry(rr, rr * .09, 8, 28), frameM); rim.scale.y = .85; lens.add(rim);
      if (dark) { const glass = new THREE.Mesh(new THREE.CircleGeometry(rr, 28), mat(THREE, 0x0b0b10, { transparent: true, opacity: .85 }));
        glass.scale.y = .85; lens.add(glass); }
      lens.position.set(h.c.x + s * h.eyeDist / 2, h.eyeY, h.lensZ[k]); lens.rotation.y = s * .22;
      g.add(lens);
      const ox = h.c.x + s * (h.eyeDist / 2 + rr * .95), oz = h.lensZ[k] - rr * .2, ear = h.c.z - h.size.z * .05;
      const len = Math.max(.01, oz - ear);
      const arm = new THREE.Mesh(new THREE.BoxGeometry(rr * .09, rr * .09, len), frameM);
      arm.position.set(ox + s * h.size.x * .03, h.eyeY + rr * .2, (oz + ear) / 2); arm.rotation.y = -s * .08; g.add(arm);
    }
    const bridge = new THREE.Mesh(new THREE.TorusGeometry(Math.max(.004, h.eyeDist / 2 - rr * .95), rr * .08, 6, 12, Math.PI), frameM);
    bridge.position.set(h.c.x, h.eyeY + rr * .05, Math.max(...h.lensZ) + .002); g.add(bridge);
    return g;
  },
  sunglasses(THREE, h) { return BUILD.glasses(THREE, h, true); },
  crown(THREE, h) {
    const g = new THREE.Group(), r = h.size.x * .3, y = h.box.max.y - h.size.y * .04, gold = mat(THREE, 0xf2c14e);
    const ring = new THREE.Mesh(new THREE.CylinderGeometry(r, r * .95, h.size.y * .12, 24, 1, true), mat(THREE, 0xf2c14e, { side: THREE.DoubleSide }));
    ring.position.set(h.c.x, y, h.c.z); g.add(ring);
    for (let i = 0; i < 6; i++) {
      const a = i / 6 * Math.PI * 2, p = new THREE.Mesh(new THREE.ConeGeometry(r * .2, h.size.y * .13, 4), gold);
      p.position.set(h.c.x + Math.cos(a) * r, y + h.size.y * .12, h.c.z + Math.sin(a) * r); g.add(p);
    }
    return g;
  },
  cat_ears(THREE, h) {
    const g = new THREE.Group();
    for (const s of [-1, 1]) {
      const ear = new THREE.Mesh(new THREE.ConeGeometry(h.size.x * .13, h.size.y * .3, 4), mat(THREE, 0x2a2a2e));
      ear.position.set(h.c.x + s * h.size.x * .28, h.box.max.y - h.size.y * .02, h.c.z); ear.rotation.z = -s * .35; ear.rotation.y = Math.PI / 4;
      const inner = new THREE.Mesh(new THREE.ConeGeometry(h.size.x * .07, h.size.y * .18, 4), mat(THREE, 0xe7a1b0));
      inner.position.copy(ear.position); inner.position.z += h.size.x * .04; inner.position.y -= h.size.y * .03; inner.rotation.copy(ear.rotation);
      g.add(ear, inner);
    }
    return g;
  },
  flower(THREE, h) {
    const g = new THREE.Group(), x = h.c.x + h.size.x * .42, y = h.box.max.y - h.size.y * .22, z = h.c.z + h.size.z * .15, r = h.size.x * .06;
    for (let i = 0; i < 5; i++) {
      const a = i / 5 * Math.PI * 2, p = new THREE.Mesh(new THREE.SphereGeometry(r, 10, 8), mat(THREE, 0xf6a6c1));
      p.scale.set(1, 1, .45); p.position.set(x, y + Math.sin(a) * r * 1.3, z + Math.cos(a) * r * 1.3); g.add(p);
    }
    const mid = new THREE.Mesh(new THREE.SphereGeometry(r * .8, 10, 8), mat(THREE, 0xf2c14e)); mid.position.set(x + r * .2, y, z); g.add(mid);
    return g;
  },
  scarf(THREE, h) {
    const g = new THREE.Group(), p = h.neckPos, r = h.size.x * .36;
    const ring = new THREE.Mesh(new THREE.TorusGeometry(r, r * .3, 10, 28), mat(THREE, 0xc8202a));
    ring.rotation.x = Math.PI / 2; ring.scale.y = h.size.z / h.size.x * 1.05; ring.position.set(p.x, p.y - h.size.y * .05, p.z);
    const tail = new THREE.Mesh(new THREE.BoxGeometry(r * .55, h.size.y * .7, r * .18), mat(THREE, 0xc8202a));
    tail.position.set(p.x + r * .45, p.y - h.size.y * .42, p.z + r * .95); tail.rotation.z = .12;
    g.add(ring, tail); return g;
  },
};

export function makeAccessory(THREE, name, h) {
  const b = BUILD[name]; if (!b || !h) return null;
  const g = b(THREE, h);
  const toNeck = name === 'scarf' || name === 'headphones_neck';
  g.applyMatrix4(new THREE.Matrix4().copy(toNeck ? h.neckRest : h.headRest).invert());
  (toNeck ? h.neck : h.head).add(g);
  g.name = 'acc:' + name;
  return g;
}

export function disposeAccessory(g) {
  if (!g) return;
  g.removeFromParent();
  g.traverse(o => { o.geometry?.dispose(); [].concat(o.material || []).forEach(m => m.dispose()); });
}
