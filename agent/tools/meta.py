"""tool_search: the model sees only the tools picked for the request; this finds the others (Tool Search)."""
from . import S, tool


@tool("tool_search", "Найти инструмент, которого нет в списке: query — что нужно сделать (например «громкость дискорда», "
                     "«напоминание», «презентация»). Найденные инструменты станут доступны на следующем шаге.",
      {"query": S}, ["query"])
async def tool_search(query: str) -> str:
    from .. import toolpick
    from . import REGISTRY
    names = toolpick.search(query)
    if not names:
        return f"Под «{query}» инструментов не нашлось — ответь сам или используй web_search."
    rows = [f"- {n}: {REGISTRY[n]['schema']['function']['description'][:160]}" for n in names if n in REGISTRY]
    return "Теперь доступны (вызывай нужный):\n" + "\n".join(rows) + "\n[[tools:" + ",".join(names) + "]]"
