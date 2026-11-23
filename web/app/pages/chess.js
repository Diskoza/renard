import { api, post, esc, h, toast } from '../core.js';

const GLYPH = { p: '♟', n: '♞', b: '♝', r: '♜', q: '♛', k: '♚' };
let root, st = null, sel = null, busy = false, hint = '', voiceOn = false;

export async function mount(el) {
  root = el;
  try { voiceOn = localStorage.getItem('nxChessVoice') === '1'; } catch (e) {  }
  root.appendChild(h(`<div class="page-pad"><div class="chess-wrap">
    <div class="chess-board" id="board"></div>
    <div class="chess-side">
      <h1 style="margin:0 0 6px">Шахматы</h1>
      <div class="sub" id="cInfo"></div>
      <div class="chess-say" id="cSay"></div>
      <div class="chess-moves" id="cMoves"></div>
      <div class="row" style="gap:6px;flex-wrap:wrap">
        <button class="btn" id="cUndo">↶ Переходить</button><button class="btn" id="cHint">💡 Подсказка</button>
        <label class="sub" style="display:flex;gap:6px;align-items:center"><input type="checkbox" id="cVoice" ${voiceOn ? 'checked' : ''}> комментарии голосом</label></div>
      <div class="card" style="margin-top:12px"><b>Новая партия</b>
        <div class="row" style="gap:6px;margin-top:8px"><select class="txt" id="cColor"><option value="1">я белыми</option><option value="0">я чёрными</option></select>
          <select class="txt" id="cLevel">${['новичок', 'любитель', 'клубный', 'сильный', 'максимум'].map((n, i) => `<option value="${i + 1}" ${i === 1 ? 'selected' : ''}>${n}</option>`).join('')}</select>
          <button class="btn ok" id="cNew">Играть</button></div></div>
    </div></div></div>`));
  root.querySelector('#cNew').onclick = async () => { st = await post('/api/chess/new', { white: root.querySelector('#cColor').value === '1', level: +root.querySelector('#cLevel').value }); sel = null; hint = ''; paint(true); };
  root.querySelector('#cUndo').onclick = async () => { st = await post('/api/chess/undo'); sel = null; hint = ''; paint(); };
  root.querySelector('#cHint').onclick = async () => { const r = await post('/api/chess/hint'); hint = r.hint || ''; st = r; paint(); };
  root.querySelector('#cVoice').onchange = (e) => { voiceOn = e.target.checked; try { localStorage.setItem('nxChessVoice', voiceOn ? '1' : '0'); } catch (err) {  } };
  st = await api('/api/chess');
  paint();
}
export function show() { if (root) api('/api/chess').then(s => { st = s; paint(); }); }

function sqName(f, r) { return 'abcdefgh'[f] + (r + 1); }
function parseFen(fen) {
  const rows = fen.split(' ')[0].split('/'), out = {};
  rows.forEach((row, i) => { let f = 0; for (const ch of row) { if (/\d/.test(ch)) f += +ch; else { out[sqName(f, 7 - i)] = ch; f++; } } });
  return out;
}
async function speak(text) {
  if (!voiceOn || !text) return;
  try { const r = await fetch('/api/voice/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: text.replace(/[🎉🙂]/g, '') }) });
    if (r.ok) new Audio(URL.createObjectURL(await r.blob())).play(); } catch (e) {  }
}

function paint(say = false) {
  if (!st) return;
  const pieces = parseFen(st.fen), board = root.querySelector('#board');
  const files = st.user_white ? [0, 1, 2, 3, 4, 5, 6, 7] : [7, 6, 5, 4, 3, 2, 1, 0];
  const ranks = st.user_white ? [7, 6, 5, 4, 3, 2, 1, 0] : [0, 1, 2, 3, 4, 5, 6, 7];
  const targets = sel ? st.legal.filter(m => m.startsWith(sel)).map(m => m.slice(2, 4)) : [];
  const last = st.last ? [st.last.slice(0, 2), st.last.slice(2, 4)] : [];
  const kingSq = st.check ? Object.entries(pieces).find(([, p]) => p === (st.fen.split(' ')[1] === 'w' ? 'K' : 'k'))?.[0] : '';
  board.innerHTML = ranks.map(r => files.map(f => {
    const sq = sqName(f, r), p = pieces[sq], dark = (f + r) % 2 === 0;
    const cls = ['sq', dark ? 'd' : 'l', sel === sq ? 'sel' : '', targets.includes(sq) ? (p ? 'cap' : 'dot') : '', last.includes(sq) ? 'last' : '',
      kingSq === sq ? 'chk' : '', hint && (hint.slice(0, 2) === sq || hint.slice(2, 4) === sq) ? 'hint' : ''].join(' ');
    const coord = (f === files[0] ? `<i class="rk">${r + 1}</i>` : '') + (r === ranks[7] ? `<i class="fl">${'abcdefgh'[f]}</i>` : '');
    return `<div class="${cls}" data-sq="${sq}">${p ? `<span class="pc ${p === p.toUpperCase() ? 'w' : 'b'}">${GLYPH[p.toLowerCase()]}</span>` : ''}${coord}</div>`;
  }).join('')).join('');
  board.querySelectorAll('.sq').forEach(el => el.onclick = () => click(el.dataset.sq, pieces));
  root.querySelector('#cInfo').innerHTML = `Ты ${st.user_white ? 'белыми' : 'чёрными'} · уровень Renard: <b>${esc(st.level_name)}</b> · движок: ${esc(st.engine)}` +
    (st.result ? ` · <b>итог ${esc(st.result)}</b>` : st.turn_user ? ' · <b>твой ход</b>' : ' · думаю…');
  root.querySelector('#cSay').textContent = st.comment || 'Твой ход!';
  const san = st.san || [];
  root.querySelector('#cMoves').innerHTML = san.reduce((a, m, i) => a + (i % 2 === 0 ? `<span class="n">${i / 2 + 1}.</span>` : '') + `<span>${esc(m)}</span>`, '') || '<span class="sub">ходов ещё нет</span>';
  if (say) speak(st.comment);
}

async function click(sq, pieces) {
  if (busy || !st.turn_user) return;
  const p = pieces[sq], mine = p && ((p === p.toUpperCase()) === st.user_white);
  if (sel && st.legal.some(m => m.startsWith(sel + sq))) {
    busy = true; hint = '';
    const from = sel; sel = null;
    pieces[sq] = pieces[from]; delete pieces[from];
    st = { ...st, fen: st.fen, turn_user: false, last: from + sq }; paint();
    const r = await post('/api/chess/move', { uci: from + sq }).catch(e => ({ error: e.message }));
    busy = false;
    if (r.error && !r.fen) { toast(r.error, 'err'); st = await api('/api/chess'); paint(); return; }
    st = r; paint(true);
    if (r.mood) post('/api/avatar', { emotion: r.mood }).catch(() => {});
    return;
  }
  sel = mine ? sq : null; paint();
}
