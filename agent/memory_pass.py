"""Background memory pass: after a pause in the conversation, extract facts the USER stated
and append them to notes. Small diffs only, never rewrites whole notes, never stores guesses.
"""
import json
import re

EXTRACT_PROMPT = """Ниже реплики пользователя из разговора. Выпиши ТОЛЬКО долговременные факты, которые пользователь
прямо сказал о себе, своих проектах, железе, планах или о том, как ему удобнее получать ответы.
Не записывай: свои догадки, разовые просьбы («открой хром»), то, что быстро устареет, ответы ассистента.
Файлы: profile.md — о человеке; preferences.md — как отвечать/работать; projects.md — проекты и железо; notes.md — прочее.
Уже записано (не повторяй):
{known}

Ответь строго JSON-массивом, например [{{"fact": "...", "note": "profile.md"}}]. Если фактов нет — [].

Реплики пользователя:
{msgs}"""

ALLOWED_NOTES = {"profile.md", "preferences.md", "projects.md", "notes.md"}


async def run_memory_pass(agent, session: str, since_id: int) -> tuple[list[str], int]:
    mem = agent.memory
    rows = mem.db.execute(
        "SELECT id, content FROM messages WHERE session=? AND role='user' AND id>? ORDER BY id", (session, since_id)
    ).fetchall()
    if not rows:
        return [], since_id
    last_id = rows[-1][0]
    msgs = [c for _, c in rows if len(c) > 15 and not c.lower().startswith(("запомни", "забудь"))]
    if not msgs:
        return [], last_id
    known = "\n".join(mem.read_note(n) for n in sorted(ALLOWED_NOTES))[-3000:]
    prompt = EXTRACT_PROMPT.format(known=known, msgs="\n".join(f"- {m[:500]}" for m in msgs[-20:]))
    r = await agent.llm.chat("low", [{"role": "user", "content": prompt}])
    text = r.get("message", {}).get("content", "")
    m = re.search(r"\[.*\]", text, re.S)
    saved = []
    if m:
        try:
            items = json.loads(m.group(0))
        except json.JSONDecodeError:
            items = []
        for it in items[:10]:
            if not isinstance(it, dict):
                continue
            fact = str(it.get("fact", "")).strip()
            note = it.get("note", "notes.md")
            if note not in ALLOWED_NOTES:
                note = "notes.md"
            if 5 < len(fact) < 300:
                res = mem.remember(fact, note, session=session)
                if res.startswith("Запомнил"):
                    saved.append(res)
    return saved, last_id
