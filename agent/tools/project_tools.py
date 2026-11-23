"""Tools of the current project (the chat belongs to a project): search its knowledge, remember inside it."""
from . import I, S, tool


def _pid(ctx) -> str:
    return getattr((ctx or {}).get("agent"), "current_project", "") or ""


@tool("project_search", "Поиск по знаниям текущего проекта (загруженные файлы и папки проекта): query — что найти. "
                        "Только в чате проекта.", {"query": S, "k": I}, ["query"])
async def project_search(query: str, k: int = 6, ctx: dict | None = None) -> str:
    from .. import projects
    pid = _pid(ctx)
    if not pid:
        return "Этот чат не в проекте. Ищи файлы через search_files."
    hits = projects.search(pid, query, max(1, min(int(k or 6), 12)))
    if not hits:
        return f"В знаниях проекта ничего про «{query}» не нашёл."
    return "\n\n".join(f"### {h['file']} (часть {h['i'] + 1})\n{h['text']}" for h in hits)


@tool("project_remember", "Запомнить факт в памяти ТЕКУЩЕГО проекта (решение, стек, договорённость, правило проекта)",
      {"fact": S}, ["fact"])
async def project_remember(fact: str, ctx: dict | None = None) -> str:
    from .. import projects
    pid = _pid(ctx)
    if not pid:
        return "Этот чат не в проекте — используй remember."
    return projects.remember(pid, fact)
