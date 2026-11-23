import { prefs } from './core.js';

const FRAG = `precision mediump float;
uniform vec2 res; uniform float t; uniform vec3 c0, c1, c2;
float h(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float n(vec2 p){ vec2 i = floor(p), f = fract(p); f = f*f*(3.0-2.0*f);
  return mix(mix(h(i), h(i+vec2(1,0)), f.x), mix(h(i+vec2(0,1)), h(i+vec2(1,1)), f.x), f.y); }
float fbm(vec2 p){ float v = 0.0, a = 0.5; for (int i = 0; i < 5; i++) { v += a * n(p); p = p * 2.03 + 7.1; a *= 0.5; } return v; }
void main(){
  vec2 uv = gl_FragCoord.xy / res.xy; vec2 p = uv * vec2(res.x / res.y, 1.0) * 2.2;
  vec2 q = vec2(fbm(p + t * 0.05), fbm(p + vec2(5.2, 1.3) - t * 0.04));
  vec2 r = vec2(fbm(p + 3.0 * q + vec2(1.7, 9.2) + t * 0.03), fbm(p + 3.0 * q + vec2(8.3, 2.8) - t * 0.035));
  float f = fbm(p + 3.5 * r);
  vec3 col = mix(c0, c1, smoothstep(0.25, 0.85, f));
  col = mix(col, c2, smoothstep(0.55, 1.0, length(r) * 0.75) * 0.8);
  col *= 0.75 + 0.35 * smoothstep(0.2, 0.9, f);
  float vig = smoothstep(1.25, 0.25, length(uv - 0.5) * 1.4);
  gl_FragColor = vec4(col * (0.55 + 0.45 * vig), 1.0);
}`;
const hex = (s) => { const n = parseInt((s || '#000').replace('#', ''), 16); return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255]; };

export function startBackground(canvas) {
  const gl = canvas.getContext('webgl', { antialias: false, alpha: false, preserveDrawingBuffer: false });
  if (!gl) return;
  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; };
  const pr = gl.createProgram();
  gl.attachShader(pr, sh(gl.VERTEX_SHADER, 'attribute vec2 a; void main(){ gl_Position = vec4(a, 0.0, 1.0); }'));
  gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, FRAG)); gl.linkProgram(pr); gl.useProgram(pr);
  const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(pr, 'a'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const U = (n) => gl.getUniformLocation(pr, n);
  const uRes = U('res'), uT = U('t'), uc = [U('c0'), U('c1'), U('c2')];
  let last = 0, time = 0, prev = performance.now();
  function size() { const s = 0.5; canvas.width = Math.max(2, innerWidth * s | 0); canvas.height = Math.max(2, innerHeight * s | 0); gl.viewport(0, 0, canvas.width, canvas.height); }
  addEventListener('resize', size); size();
  function frame(now) {
    requestAnimationFrame(frame);
    const ui = prefs.ui || {};
    if (document.hidden || (ui.background || 'smoke') !== 'smoke' || now - last < 33) { prev = now; return; }
    last = now;
    time += (now - prev) / 1000 * (ui.animations === false ? 0 : (ui.bg_speed ?? 1)); prev = now;
    const cols = ui.bg_colors || ['#1A1918', '#2A2350', '#3A2A2A'];
    gl.uniform2f(uRes, canvas.width, canvas.height); gl.uniform1f(uT, time);
    cols.slice(0, 3).forEach((c, i) => gl.uniform3fv(uc[i], hex(c)));
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
  requestAnimationFrame(frame);
}
