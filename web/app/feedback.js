import { h, post, toast, esc } from './core.js';

export function feedbackBar(info) {
  const bar = h(`<div class="fb">
    <button class="fb-b" data-r="1" title="Хороший ответ">👍</button>
    <button class="fb-b" data-r="-1" title="Плохой ответ — объясни, что не так">👎</button>
    <span class="fb-note"></span></div>`);
  const note = bar.querySelector('.fb-note');
  let current = 0, lessonId = '';
  const mark = (rating) => bar.querySelectorAll('.fb-b').forEach(b => b.classList.toggle('on', +b.dataset.r === rating));
  const undo = async () => {
    await post('/api/feedback/undo', { user: info.user || '', session: info.session || '', lesson_id: lessonId }).catch(() => {});
    current = 0; lessonId = ''; mark(0); note.textContent = 'Отменено';
    bar.querySelectorAll('.fb-form,.fb-draft').forEach(x => x.remove());
  };
  const draftCard = (d) => {
    const c = h(`<div class="fb-draft"><div class="fb-dh">📘 Черновик урока — проверь и сохрани</div>
      <label>Когда<input class="fb-w" value="${esc(d.when || '')}"></label>
      <label>Делать<input class="fb-d" value="${esc(d.do || '')}"></label>
      <label>Не делать<input class="fb-n" value="${esc(d.dont || '')}"></label>
      <div class="fb-row"><button class="btn sm primary fb-save">Сохранить урок</button><button class="btn sm fb-drop">Не надо</button></div></div>`);
    c.querySelector('.fb-save').onclick = async () => {
      const lesson = { ...d, when: c.querySelector('.fb-w').value.trim(), do: c.querySelector('.fb-d').value.trim(),
        dont: c.querySelector('.fb-n').value.trim() };
      const r = await post('/api/lessons', lesson).catch(e => ({ error: e.message }));
      if (r.error) { toast('Не сохранилось: ' + r.error); return; }
      lessonId = r.lesson.id; c.remove();
      note.innerHTML = `📘 Урок сохранён: ${esc(r.lesson.when)} — ${esc(r.lesson.do)}`;
    };
    c.querySelector('.fb-drop').onclick = () => { c.remove(); note.textContent = '👎 учтён, урок не сохранён'; };
    return c;
  };
  const send = async (rating, reason = '') => {
    const r = await post('/api/feedback', { rating, reason, user: info.user || '', answer: info.answer || '',
      session: info.session || '', msg: info.msg || '', tools: info.used || [] }).catch(e => ({ error: e.message }));
    if (r.error) { toast('Не сохранилось: ' + r.error); return r; }
    current = rating; mark(rating);
    if (r.draft) { note.textContent = ''; bar.appendChild(draftCard(r.draft)); }
    else if (rating > 0) note.textContent = 'Спасибо, запомнил как хороший пример (нажми ещё раз — отменить)';
    else note.textContent = '👎 учтён (нажми ещё раз — отменить)';
    return r;
  };
  bar.querySelector('[data-r="1"]').onclick = () => (current === 1 ? undo() : send(1));
  bar.querySelector('[data-r="-1"]').onclick = () => {
    if (current === -1) { undo(); return; }
    if (bar.querySelector('.fb-form')) return;
    const form = h(`<div class="fb-form"><input class="fb-in" placeholder="Что не так? Например: «не переспрашивай, сразу отправляй»">
      <button class="btn sm primary fb-send">Научить</button><button class="btn sm fb-skip">Просто 👎</button></div>`);
    bar.appendChild(form);
    const inp = form.querySelector('.fb-in'); inp.focus();
    const go = async (reason) => { form.remove(); note.textContent = reason ? 'Готовлю черновик урока…' : ''; await send(-1, reason); };
    form.querySelector('.fb-send').onclick = () => go(inp.value.trim());
    form.querySelector('.fb-skip').onclick = () => go('');
    inp.onkeydown = (e) => { if (e.key === 'Enter') go(inp.value.trim()); if (e.key === 'Escape') form.remove(); };
  };
  return bar;
}

export function codeCopy(root) {
  root.querySelectorAll('pre').forEach(pre => {
    if (pre.querySelector(':scope > .code-copy')) return;
    const b = document.createElement('button');
    b.className = 'code-copy'; b.textContent = 'Копировать';
    b.onclick = async (e) => {
      e.stopPropagation();
      const text = (pre.querySelector('code') || pre).innerText.replace(/Копировать$|Скопировано ✓$/, '').trimEnd();
      try { await navigator.clipboard.writeText(text); }
      catch { const t = document.createElement('textarea'); t.value = text; document.body.appendChild(t); t.select(); document.execCommand('copy'); t.remove(); }
      b.textContent = 'Скопировано ✓'; setTimeout(() => (b.textContent = 'Копировать'), 1500);
    };
    pre.appendChild(b);
  });
}

export async function lessonsPanel(root) {
  const r = await fetch('/api/lessons').then(x => x.json()).catch(() => ({ lessons: [] }));
  root.innerHTML = r.lessons.length ? '' : '<p class="muted">Уроков пока нет. Поставь 👎 и объясни, что не так, — появятся здесь.</p>';
  for (const l of r.lessons.slice().reverse()) {
    const row = h(`<div class="lesson"><div><b>Когда</b> ${esc((l.when || '').replace(/^когда\s+/i, ''))}<br><b>Делать:</b> ${esc(l.do)}${l.dont ? `<br><b>Не делать:</b> ${esc(l.dont)}` : ''}
      <div class="muted">${esc(l.created || '')} · повторялся ${l.count || 1}× · слова: ${esc(l.triggers || '')}</div></div>
      <button class="btn sm fb-del">Удалить</button></div>`);
    row.querySelector('.fb-del').onclick = async () => {
      await fetch('/api/lessons/' + encodeURIComponent(l.id), { method: 'DELETE' }); row.remove();
    };
    root.appendChild(row);
  }
}
