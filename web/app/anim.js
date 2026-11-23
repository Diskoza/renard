import * as THREE from 'three';

const RIG = {
  mixamorigHips: 'hips', mixamorigSpine: 'spine', mixamorigSpine1: 'chest', mixamorigSpine2: 'upperChest',
  mixamorigNeck: 'neck', mixamorigHead: 'head',
  mixamorigLeftShoulder: 'leftShoulder', mixamorigLeftArm: 'leftUpperArm', mixamorigLeftForeArm: 'leftLowerArm', mixamorigLeftHand: 'leftHand',
  mixamorigRightShoulder: 'rightShoulder', mixamorigRightArm: 'rightUpperArm', mixamorigRightForeArm: 'rightLowerArm', mixamorigRightHand: 'rightHand',
  mixamorigLeftUpLeg: 'leftUpperLeg', mixamorigLeftLeg: 'leftLowerLeg', mixamorigLeftFoot: 'leftFoot', mixamorigLeftToeBase: 'leftToes',
  mixamorigRightUpLeg: 'rightUpperLeg', mixamorigRightLeg: 'rightLowerLeg', mixamorigRightFoot: 'rightFoot', mixamorigRightToeBase: 'rightToes',
};
for (const side of ['Left', 'Right']) {
  const s = side.toLowerCase();
  const f = { Thumb: ['Metacarpal', 'Proximal', 'Distal'], Index: ['Proximal', 'Intermediate', 'Distal'],
    Middle: ['Proximal', 'Intermediate', 'Distal'], Ring: ['Proximal', 'Intermediate', 'Distal'], Pinky: ['Proximal', 'Intermediate', 'Distal'] };
  for (const [m, parts] of Object.entries(f))
    parts.forEach((p, i) => { RIG[`mixamorig${side}Hand${m}${i + 1}`] = `${s}${m === 'Pinky' ? 'Little' : m}${p}`; });
}

let catalogP = null;
export function catalog() {
  catalogP = catalogP || fetch('/anims/catalog.json', { cache: 'no-store' }).then(r => r.ok ? r.json() : []).catch(() => []);
  return catalogP;
}

export const GESTURE_CLIPS = {
  wave: ['Waving', 'Waving Gesture', 'Standing Greeting'], nod: ['Head Nod Yes', 'Thoughtful Head Nod'],
  shake: ['Shaking Head No', 'No', 'Annoyed Head Shake'], bow: ['Quick Formal Bow', 'Quick Informal Bow'],
  think: ['Thinking'], shrug: ['Shrugging'], clap: ['Clapping', 'Standing Clap'], stretch: ['Arm Stretching', 'Neck Stretching'],
  point: ['Pointing Forward', 'Pointing'], celebrate: ['Cheering', 'Victory', 'Standing Fist Pump'], jump: ['Joyful Jump', 'Jump'],
  happy: ['Happy', 'Excited'], sad: ['Sad Idle', 'Defeated', 'Disappointed'], angry: ['Angry', 'Angry Gesture'],
  surprised: ['Surprised'], relaxed: ['Breathing Idle'],
  shy: ['Bashful'],
};
export const GESTURE_OPTS = { shy: { seconds: 3 } };

export const SEATED = /\bsitting\b|\bseated\b|\bgaming\b|sit to type|type to sit|sitting pose/i;
export const SIT_CLIPS = {
  happy: ['Sitting Laughing', 'Sitting Thumbs Up'], celebrate: ['Cheering While Sitting', 'Sitting Victory', 'Sitting Fist Pump'],
  clap: ['Sitting Clap'], angry: ['Sitting Angry', 'Sitting Yell'], surprised: ['Sitting Disbelief'], sad: ['Sitting Dazed'],
  point: ['Sitting And Pointing'], shake: ['Sitting Disapproval'], talk: ['Sitting Talking'], wave: ['Sitting Thumbs Up'],
};
const LOWER = /hips|Leg|Foot|Toes/;

const mat = (c, o = {}) => new THREE.MeshStandardMaterial({ color: c, roughness: .55, metalness: .05, ...o });
const PROPS = {
  cup: { hand: 'rightHand', auto: true, pos: [-.075, -.035, .045], rot: [0, 0, Math.PI / 2], make() {
    const g = new THREE.Group();
    const body = new THREE.Mesh(new THREE.CylinderGeometry(.038, .032, .095, 20, 1, true), mat(0xf2efe8, { side: THREE.DoubleSide }));
    const bottom = new THREE.Mesh(new THREE.CircleGeometry(.032, 20), mat(0xf2efe8)); bottom.rotation.x = Math.PI / 2; bottom.position.y = -.047;
    const tea = new THREE.Mesh(new THREE.CircleGeometry(.035, 20), mat(0x6b3a1e)); tea.rotation.x = -Math.PI / 2; tea.position.y = .03;
    const handle = new THREE.Mesh(new THREE.TorusGeometry(.022, .006, 8, 16, Math.PI), mat(0xf2efe8));
    handle.rotation.z = -Math.PI / 2; handle.position.x = .04;
    g.add(body, bottom, tea, handle); return g; } },
  phone: { hand: 'rightHand', auto: true, pos: [-.08, -.025, .02], rot: [Math.PI / 2, 0, 0], make() {
    const g = new THREE.Group();
    g.add(new THREE.Mesh(new THREE.BoxGeometry(.072, .145, .009), mat(0x1c1c22)));
    const scr = new THREE.Mesh(new THREE.PlaneGeometry(.064, .134), mat(0x3a6fd8, { emissive: 0x16306a, emissiveIntensity: .8 }));
    scr.position.z = .0047; g.add(scr); return g; } },
  gamepad: { hand: 'rightHand', pos: [-.06, -.04, .07], rot: [0, 0, 0], make() {
    const g = new THREE.Group();
    const body = new THREE.Mesh(new THREE.BoxGeometry(.16, .025, .07), mat(0x2a2a30)); g.add(body);
    for (const x of [-.06, .06]) { const grip = new THREE.Mesh(new THREE.CylinderGeometry(.022, .022, .025, 14), mat(0x2a2a30));
      grip.position.set(x, 0, .035); g.add(grip); }
    for (const [x, c] of [[.045, 0xd94040], [.03, 0x40a0d9]]) { const b = new THREE.Mesh(new THREE.CylinderGeometry(.006, .006, .01, 10), mat(c));
      b.position.set(x, .016, -.005); g.add(b); }
    return g; } },
  mic: { hand: 'rightHand', auto: true, aim: 'mouth', pos: [-.07, -.03, .0], rot: [Math.PI / 2, 0, 0], make() {
    const g = new THREE.Group();
    const h = new THREE.Mesh(new THREE.CylinderGeometry(.015, .011, .15, 14), mat(0x202024)); h.position.y = .01; g.add(h);
    const ring = new THREE.Mesh(new THREE.CylinderGeometry(.019, .016, .02, 16), mat(0x5c5c64, { metalness: .5 })); ring.position.y = .09; g.add(ring);
    const head = new THREE.Mesh(new THREE.SphereGeometry(.028, 16, 12), mat(0x9a9aa2, { metalness: .6, roughness: .35 }));
    head.scale.y = 1.15; head.position.y = .12; g.add(head); return g; } },
  tablet: { hand: 'leftHand', pos: [.09, -.03, .06], rot: [Math.PI / 2, 0, 0], make() {
    const g = new THREE.Group();
    g.add(new THREE.Mesh(new THREE.BoxGeometry(.18, .25, .01), mat(0x2b2b30)));
    const scr = new THREE.Mesh(new THREE.PlaneGeometry(.165, .232), mat(0x9fd3ff, { emissive: 0x335577, emissiveIntensity: .7 }));
    scr.position.z = .0052; g.add(scr); return g; } },
  guitar: { hand: 'chest', pos: [.17, .1, .15], rot: [0, 0, -0.9], scale: .8, make() {
    const g = new THREE.Group(), wood = mat(0xb5652b);
    const b1 = new THREE.Mesh(new THREE.CylinderGeometry(.16, .16, .08, 24), wood); b1.rotation.x = Math.PI / 2; b1.position.y = -.42;
    const b2 = new THREE.Mesh(new THREE.CylinderGeometry(.12, .12, .08, 24), wood); b2.rotation.x = Math.PI / 2; b2.position.y = -.25;
    const neck = new THREE.Mesh(new THREE.BoxGeometry(.05, .45, .025), mat(0x5a3418)); neck.position.y = .02;
    const hole = new THREE.Mesh(new THREE.CircleGeometry(.04, 20), mat(0x1a0f08)); hole.position.set(0, -.33, .041);
    g.add(b1, b2, neck, hole); return g; } },
};
const GRIP = { mic: [1.25, 1.35, .9, .6], cup: [1.0, 1.15, .8, .4] };
const PROP_OF = [[/drink/i, 'cup'], [/tablet/i, 'tablet'], [/\btext|phone|calling|cell/i, 'phone'], [/\bgaming/i, 'gamepad'],
  [/\bsing|\brapping/i, 'mic'], [/guitar/i, 'guitar']];
export const propFor = name => (PROP_OF.find(([rx]) => rx.test(name || '')) || [])[1] || '';

function toClip(asset, vrm) {
  const src = THREE.AnimationClip.findByName(asset.animations, 'mixamo.com') || asset.animations[0];
  if (!src) throw new Error('в файле нет анимации');
  const tracks = [], restInv = new THREE.Quaternion(), parentRest = new THREE.Quaternion(), q = new THREE.Quaternion(), v = new THREE.Vector3();
  const hipsNode = asset.getObjectByName('mixamorigHips');
  const motionHips = hipsNode ? hipsNode.position.y : 100;
  const restHips = vrm.humanoid.normalizedRestPose?.hips?.position;
  const vrmHips = restHips ? Math.abs(restHips[1])
    : Math.abs(vrm.humanoid.getNormalizedBoneNode('hips').getWorldPosition(v).y - vrm.scene.getWorldPosition(new THREE.Vector3()).y)
      / (vrm.scene.scale.y || 1);
  const scale = vrmHips / motionHips;
  const v0 = vrm.meta?.metaVersion === '0';
  for (const tr of src.tracks) {
    const [rig, prop] = tr.name.split('.');
    const bone = RIG[rig], node = bone && vrm.humanoid.getNormalizedBoneNode(bone), rigNode = asset.getObjectByName(rig);
    if (!node || !rigNode) continue;
    rigNode.getWorldQuaternion(restInv).invert();
    rigNode.parent.getWorldQuaternion(parentRest);
    if (tr instanceof THREE.QuaternionKeyframeTrack) {
      const vals = tr.values.slice();
      for (let i = 0; i < vals.length; i += 4) {
        q.fromArray(vals, i).premultiply(parentRest).multiply(restInv).toArray(vals, i);
      }
      tracks.push(new THREE.QuaternionKeyframeTrack(`${node.name}.${prop}`, tr.times, vals.map((x, i) => v0 && i % 2 === 0 ? -x : x)));
    } else if (tr instanceof THREE.VectorKeyframeTrack && bone === 'hips' && prop === 'position') {
      tracks.push(new THREE.VectorKeyframeTrack(`${node.name}.${prop}`, tr.times,
        tr.values.map((x, i) => (v0 && i % 3 !== 1 ? -x : x) * scale)));
    }
  }
  return new THREE.AnimationClip(src.name, src.duration, tracks);
}

export function makeClipPlayer(vrm) {
  const mixer = new THREE.AnimationMixer(vrm.scene);
  const cache = new Map();
  let act = null, entry = null, w = 0, target = 0, fade = .35, touched = new Set(), hipsRest = null;
  const saveQ = new Map(), hips = vrm.humanoid.getNormalizedBoneNode('hips');
  const handOf = new WeakMap(), upperOf = new WeakMap();
  const upperNodes = new Set(Object.values(RIG).filter(b => !LOWER.test(b))
    .map(b => vrm.humanoid.getNormalizedBoneNode(b)?.name).filter(Boolean));
  const withoutOf = new Map();
  function without(clip, bones) {
    const key = clip.uuid + bones.join();
    if (!withoutOf.has(key)) {
      const drop = new Set(bones.map(b => vrm.humanoid.getNormalizedBoneNode(b)?.name).filter(Boolean));
      withoutOf.set(key, new THREE.AnimationClip(clip.name, clip.duration, clip.tracks.filter(t => !drop.has(t.name.split('.')[0]))));
    }
    return withoutOf.get(key);
  }
  function upper(clip) {
    if (!upperOf.has(clip))
      upperOf.set(clip, new THREE.AnimationClip(clip.name + ' (upper)', clip.duration,
        clip.tracks.filter(t => upperNodes.has(t.name.split('.')[0]))));
    return upperOf.get(clip);
  }
  function liftedHand(clip) {
    if (handOf.has(clip)) return handOf.get(clip);
    const L = vrm.humanoid.getNormalizedBoneNode('leftHand'), R = vrm.humanoid.getNormalizedBoneNode('rightHand');
    if (!L || !R) return 'rightHand';
    const nodes = [...new Set(clip.tracks.map(t => t.name.split('.')[0]))].map(n => vrm.scene.getObjectByName(n)).filter(Boolean);
    const saved = nodes.map(n => [n.quaternion.clone(), n.position.clone()]);
    const m = new THREE.AnimationMixer(vrm.scene), a = m.clipAction(clip), v = new THREE.Vector3();
    let l = -1e9, r = -1e9;
    a.play();
    for (let i = 1; i <= 9; i++) {
      m.setTime(clip.duration * i / 10); vrm.scene.updateMatrixWorld(true);
      l = Math.max(l, L.getWorldPosition(v).y); r = Math.max(r, R.getWorldPosition(v).y);
    }
    a.stop(); m.uncacheRoot(vrm.scene);
    nodes.forEach((n, i) => { n.quaternion.copy(saved[i][0]); n.position.copy(saved[i][1]); });
    vrm.scene.updateMatrixWorld(true);
    const h = l > r + .05 ? 'leftHand' : 'rightHand';
    handOf.set(clip, h);
    return h;
  }
  const GQ = new THREE.Quaternion(), GE = new THREE.Euler();
  function grip(handName, k, w) {
    const pre = handName.startsWith('left') ? 'left' : 'right', s = pre === 'right' ? 1 : -1;
    for (const f of ['Index', 'Middle', 'Ring', 'Little']) {
      ['Proximal', 'Intermediate', 'Distal'].forEach((seg, i) => {
        const n = vrm.humanoid.getNormalizedBoneNode(pre + f + seg);
        if (n) n.quaternion.slerp(GQ.setFromEuler(GE.set(0, 0, s * k[i])), w);
      });
    }
    const th = vrm.humanoid.getNormalizedBoneNode(pre + 'ThumbDistal') || vrm.humanoid.getNormalizedBoneNode(pre + 'ThumbIntermediate');
    if (th) th.quaternion.slerp(GQ.setFromEuler(GE.set(0, -s * k[3], 0)), w);
  }
  const AV = new THREE.Vector3(), AM = new THREE.Vector3(), AF = new THREE.Vector3(), AQ = new THREE.Quaternion(), AY = new THREE.Vector3(0, 1, 0);
  function aimProp(pr) {
    const head = vrm.humanoid.getNormalizedBoneNode('head'), hand = pr.obj.parent;
    if (!head || !hand) return;
    vrm.scene.updateMatrixWorld(true);
    head.getWorldPosition(AM);
    AF.set(0, 0, vrm.meta?.metaVersion === '0' ? -1 : 1).applyQuaternion(vrm.scene.getWorldQuaternion(AQ));
    AM.addScaledVector(AF, .14).y -= .04;
    pr.obj.getWorldPosition(AV);
    const dir = AM.sub(AV).normalize();
    const want = new THREE.Quaternion().setFromUnitVectors(AY, dir);
    pr.obj.quaternion.copy(hand.getWorldQuaternion(AQ).invert().multiply(want));
  }
  const p = {
    playing: () => target > 0 ? entry : p.loading,
    async load(e) {
      if (cache.has(e.file)) return cache.get(e.file);
      const { FBXLoader } = await import('three/addons/loaders/FBXLoader.js');
      const clip = toClip(await new FBXLoader().loadAsync(e.file), vrm);
      cache.set(e.file, clip);
      return clip;
    },
    async play(what, o = {}) {
      const cat = await catalog();
      let e = typeof what === 'object' ? what : cat.find(x => x.id === what || x.name.toLowerCase() === String(what).toLowerCase());
      if (!e) return false;
      if (o.auto && (p.loading || (target > 0 && entry && !entry.auto))) return false;
      p.loading = e;
      let clip;
      try { clip = await p.load(e); } finally { if (p.loading === e) p.loading = null; }
      if (o.auto && target > 0 && entry && !entry.auto) return false;
      e = { ...e, auto: !!o.auto, upper: !!o.upper, tag: o.tag || '' };
      if (o.upper) clip = upper(clip);
      if (o.skip) clip = without(clip, o.skip);
      if (act) act.fadeOut(.25);
      act = mixer.clipAction(clip);
      const once = !(o.loop ?? e.loop), reps = once && clip.duration < 1.2 ? Math.max(2, Math.ceil(3 / clip.duration)) : 1;
      act.reset(); act.setLoop(once && reps === 1 ? THREE.LoopOnce : THREE.LoopRepeat, once ? reps : Infinity);
      act.clampWhenFinished = true; act.timeScale = o.speed || 1; act.play();
      entry = e; fade = o.fade ?? .35; target = 1;
      const pk = o.prop ?? propFor(e.name);
      p.setProp(pk, PROPS[pk]?.auto ? liftedHand(clip) : undefined);
      touched = new Set(clip.tracks.map(t => t.name.split('.')[0]));
      if (!hipsRest && hips) {
        const rp = vrm.humanoid.normalizedRestPose?.hips?.position;
        hipsRest = rp ? new THREE.Vector3(...rp) : hips.position.clone();
      }
      p.until = o.seconds ? performance.now() / 1000 + o.seconds
        : reps > 1 ? performance.now() / 1000 + clip.duration * reps - fade : 0;
      return true;
    },
    async playOneOf(names, o) {
      const cat = await catalog();
      const hit = names.map(n => cat.find(x => x.name === n)).filter(Boolean);
      return hit.length ? p.play(hit[Math.floor(Math.random() * hit.length)], o) : false;
    },
    async playDance(bpm, o = {}) {
      const body = (window.nxBody || 'male');
      const all = (await catalog()).filter(x => x.cat === 'dance' && x.auto !== false && (body !== 'male' || !x.female));
      const fit = x => { const r = [.5, 1, 2].map(k => bpm / (x.bpm * k)); const best = r.reduce((a, b) => Math.abs(Math.log(b)) < Math.abs(Math.log(a)) ? b : a);
        return { x, ratio: best, err: Math.abs(Math.log(best)) }; };
      const scored = bpm ? all.filter(x => x.bpm).map(fit).sort((a, b) => a.err - b.err) : [];
      const pool = scored.filter(s => s.err < Math.log(1.25)).slice(0, 5);
      const pick = pool.length ? pool[Math.floor(Math.random() * pool.length)] : null;
      if (!pick) return p.play(all[Math.floor(Math.random() * all.length)], { loop: true, ...o });
      return p.play(pick.x, { loop: true, speed: Math.max(.8, Math.min(1.25, pick.ratio)), ...o });
    },
    async playCategory(c, o) {
      const cat = (await catalog()).filter(x => x.cat === c);
      return cat.length ? p.play(cat[Math.floor(Math.random() * cat.length)], o) : false;
    },
    stop(f = .4) { fade = f; target = 0; },
    prop: null,
    setProp(kind, side) {
      if (p.prop) { p.prop.obj.removeFromParent(); p.prop.obj.traverse(o => { o.geometry?.dispose(); o.material?.dispose?.(); }); p.prop = null; }
      const d = PROPS[kind];
      const mirror = !!(d && side && side !== d.hand);
      const hand = d && vrm.humanoid.getNormalizedBoneNode(mirror ? side : d.hand);
      if (!hand) return;
      const inner = d.make();
      inner.position.set(mirror ? -d.pos[0] : d.pos[0], d.pos[1], d.pos[2]);
      inner.rotation.set(d.rot[0], mirror ? -d.rot[1] : d.rot[1], mirror ? -d.rot[2] : d.rot[2]); inner.scale.setScalar(d.scale || 1);
      const obj = new THREE.Group(); obj.add(inner);
      if (vrm.meta?.metaVersion === '0') obj.rotation.y = Math.PI;
      hand.add(obj);
      if (d.aim) {
        obj.position.copy(inner.position).applyEuler(obj.rotation); inner.position.set(0, 0, 0); inner.rotation.set(0, 0, 0);
      }
      p.prop = { kind, obj, hand: mirror ? side : d.hand, aim: d.aim };
    },
    apply(dt) {
      if (!act || (w === 0 && target === 0)) return false;
      if (act.getClip().duration && act.loop === THREE.LoopOnce && act.time >= act.getClip().duration - fade) target = 0;
      if (p.until && performance.now() / 1000 > p.until) { target = 0; p.until = 0; }
      w += Math.sign(target - w) * Math.min(Math.abs(target - w), dt / Math.max(.05, fade));
      const nodes = [...touched].map(n => vrm.scene.getObjectByName(n)).filter(Boolean);
      for (const n of nodes) saveQ.set(n, (saveQ.get(n) || new THREE.Quaternion()).copy(n.quaternion));
      const hp = hips ? hips.position.clone() : null;
      mixer.update(dt);
      for (const n of nodes) n.quaternion.slerpQuaternions(saveQ.get(n), n.quaternion.clone(), w);
      if (hips && hp && hipsRest) {
        const y = hipsRest.y + (hips.position.y - hipsRest.y);
        hips.position.set(hp.x, hp.y + (y - hp.y) * w, hp.z);
      }
      if (p.prop && GRIP[p.prop.kind]) grip(p.prop.hand, GRIP[p.prop.kind], w);
      if (p.prop?.aim) aimProp(p.prop);
      if (w === 0 && target === 0) {
        for (const n of nodes) {
          if (/Thumb|Index|Middle|Ring|Little|Toe/i.test(n.name)) n.quaternion.identity();
          else if (saveQ.has(n)) n.quaternion.copy(saveQ.get(n));
        }
        if (hips && hipsRest && touched.has(hips.name)) hips.position.copy(hipsRest);
        act.stop(); act = null; entry = null;
        p.setProp('');
      }
      return true;
    },
  };
  return p;
}
