"""Skill tools for the model: load a skill's instructions, search/install from Hermes/OpenClaw."""
from .. import skills
from . import S, tool


@tool("use_skill", "Загрузить инструкции навыка по имени (из списка навыков в системном промпте). "
      "Вызывай ПЕРЕД выполнением задачи, если есть подходящий навык", {"name": S}, ["name"])
def use_skill(name: str) -> str:
    return skills.load(name)


@tool("skill_search", "Найти навыки в каталогах Hermes Agent или OpenClaw (source: hermes | openclaw)",
      {"query": S, "source": S}, ["query"], modes=("medium", "high"))
def skill_search(query: str, source: str = "hermes") -> str:
    try:
        hits = skills.search(query, source)
    except Exception as e:
        return f"Ошибка поиска: {e}"
    return ("Найдено:\n" + "\n".join(f"{source}:{h}" for h in hits)) if hits else "Ничего не найдено."


@tool("skill_install", "Установить навык: 'hermes:<имя>', 'openclaw:<автор>/<имя>' или 'github:<owner>/<repo>/<путь>'",
      {"spec": S}, ["spec"], modes=("medium", "high"), confirm=True)
def skill_install(spec: str) -> str:
    try:
        return skills.install(spec)
    except Exception as e:
        return f"Ошибка установки: {e}"


@tool("skills_list", "Список установленных навыков")
def skills_list() -> str:
    sk = skills.installed()
    return "\n".join(f"- {s['name']} [{s['source']}]: {s['description'][:120]}" for s in sk) or "Навыков нет."
