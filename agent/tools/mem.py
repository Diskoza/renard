"""Memory tools exposed to the model."""
from . import S, tool


@tool("memory_read", "Прочитать заметку памяти по имени файла из оглавления (например profile.md). "
      "Для «что мы раньше обсуждали / о чём говорили» — не он, а search_history", {"name": S}, ["name"])
def memory_read(name: str, ctx: dict) -> str:
    return ctx["memory"].read_note(name)


@tool("remember", "Запомнить факт, который пользователь сам сказал о себе/проекте/предпочтениях. "
      "note: profile.md (о человеке), preferences.md (как отвечать), projects.md, notes.md (прочее)",
      {"fact": S, "note": S}, ["fact"])
def remember(fact: str, ctx: dict, note: str = "notes.md") -> str:
    return ctx["memory"].remember(fact, note, session=ctx.get("session", ""))


@tool("search_history", "Найти в прошлых разговорах, что мы раньше обсуждали / о чём говорили / что советовали по теме: "
      "чаты с Renard и старые чаты пользователя с ChatGPT и Claude (импортированы из их экспорта). "
      "query — ключевые слова темы (samba, tailscale, моды 1.21.1), не вся фраза", {"query": S}, ["query"])
def search_history(query: str, ctx: dict) -> str:
    from .. import archive
    hits = ctx["memory"].search_history(query, limit=4, exclude_session=ctx.get("session", ""))
    old = archive.search(query, limit=4)
    parts = []
    if hits:
        parts.append("Чаты с Renard:\n" + "\n".join(f"[{h['date']}] {h['role']}: {h['text']}" for h in hits))
    if old:
        parts.append("Старые чаты (ChatGPT / Claude):\n" + archive.format_hits(old))
    return "\n\n".join(parts) if parts else "В истории ничего не нашёл."
