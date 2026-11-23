"""Tools: long_task (work on a problem for up to N minutes with a self-compacting journal) and task_notes."""
from pathlib import Path

from . import I, S, tool
from ..logs import quiet

LONG_TOOLS = ["probe_app", "pc_script", "pc_script_write", "app_do", "app_guide", "look_at_window", "look_at_screen",
              "open_app", "fetch_page", "web_search", "steam", "school", "telegram", "discord", "image_edit", "find_installed_apps",
              "junk_report", "save_skill", "run_skill", "apply_sandbox",
              "list_dir", "read_file", "write_file", "edit_file", "run_command", "stop_started", "look_at_window",
              "make_document", "convert_document", "install_app", "download_file", "search_files"]

BUILD = r"(?i)(сдела|созда|напиш|разработа|доработа|прокача|улучш|допиш|почин|исправ|zrób|stwórz|popraw|build|make|fix)" \
        r"\w*(?:\s+[\w-]+){0,3}?\s+(приложени|сайт|игр|програм|бот|веб|aplikacj|stron|app|site|game)|" \
        r"продолж\w* разработ|\.exe\b|electron|react|vite|npm |package\.json"


def _specs() -> list[tuple[str, str]]:
    """(name, description) of the tools above that exist — adapter to the registry (checked at install)."""
    from . import REGISTRY
    out = []
    for n in LONG_TOOLS:
        t = REGISTRY.get(n)
        if t is None:
            continue
        f = t["schema"]["function"]
        params = ", ".join(f["parameters"].get("properties", {}))
        out.append((n, f"({params}) " + f["description"][:200]))
    return out


@tool("long_task",
      "Долго и самостоятельно разобраться в задаче (до minutes минут, по умолчанию 30): сам исследует, пробует, ведёт "
      "журнал, сжимает его и продолжает. Для «разберись сам», «выясни почему», «настрой и проверь», сложных проблем на ПК. "
      "resume=«последний» — продолжить прошлую долгую задачу.",
      {"goal": S, "minutes": I, "resume": S}, ["goal"])
async def long_task(goal: str, minutes: int = 30, resume: str = "", ctx: dict | None = None) -> str:
    from .. import worknotes, tools as T
    ctx = ctx or {}
    agent = ctx.get("agent")
    if agent is None:
        return "Долгая задача работает только через агента."
    path = ""
    said = str(ctx.get("user_text") or "")
    if resume and Path(resume).exists():
        path = resume
    else:
        p = worknotes.unfinished(goal + " " + said + " " + (resume or "") + (" продолжи" if resume else ""))
        if p:
            path = str(p)
        elif resume:
            await_note = ctx.get("send")
            if await_note:
                await await_note({"type": "note", "text": "незаконченной задачи нет — начинаю заново"})
    if not path and said and said.strip() not in goal:
        goal = f"{goal}\n(Дословно пользователь: «{said[:400]}»)"

    async def call(name, args):
        return await T.call(name, args, ctx)

    import re
    modes = getattr(agent.llm, "modes", {})
    mode = "study" if "study" in modes else "low"
    old_goal = ""
    if path:
        try:
            old_goal = (re.search(r"^# Задача: (.+)$", Path(path).read_text("utf-8", "replace"), re.M) or [None, ""])[1]
        except Exception:
            quiet()
    if re.search(BUILD, goal + " " + said + " " + old_goal) and "high" in modes:
        mode = "high"
        goal += ("\n(Это постройка проекта: папка — та, что назвал пользователь, иначе workspace\\projects\\<имя>. "
                 "По одному файлу за шаг: write_file → run_command (запуск/проверка, timeout) → прочитай ошибку → "
                 "edit_file. Само приложение (npm start, electron ., npm run dev) запускай run_command с background=true: "
                 "через 15 с результат скажет, есть ли окно и ПУСТОЕ ли оно. «ПУСТОЕ» или «окна нет» = не работает — "
                 "ищи причину (пути к собранным файлам, ошибки в консоли), не пиши, что всё готово. Перед повторным "
                 "запуском или сборкой — stop_started(cwd=папка). .exe для Electron — npm i -D electron-builder, затем "
                 "npx electron-builder --win portable (или nsis); для Python — python -m PyInstaller --onefile. "
                 "Готово = запускается без ошибок и окно показывает интерфейс (проверь look_at_window); в конце README.)")
        minutes = max(int(minutes or 30), 40)
    return await worknotes.long_task(agent, goal, ctx, _specs(), call, minutes=max(2, min(int(minutes or 30), 120)),
                                     mode=mode, resume=path)


@tool("task_notes",
      "Журналы долгих задач: action=list — последние; action=read name=… — прочитать журнал (что выяснил, что пробовал).",
      {"action": S, "name": S, "n": I}, ["action"])
async def task_notes(action: str = "list", name: str = "", n: int = 5, ctx: dict | None = None) -> str:
    from .. import worknotes
    files = worknotes.latest(max(1, min(n or 5, 20)))
    if action.startswith("list") or not name:
        return "Журналы долгих задач:\n" + "\n".join(f"- {p.stem}" for p in files) if files else "Долгих задач ещё не было."
    hit = next((p for p in worknotes.NOTES.glob("*.md") if name.lower() in p.stem.lower()), None)
    return hit.read_text("utf-8")[:6000] if hit else f"Нет журнала «{name}»."
