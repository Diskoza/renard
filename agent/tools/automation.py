"""Tools: scheduled tasks / reminders, node commands, MCP connectors."""
import json

from . import S, tool


@tool("schedule_task",
      "Запланировать задачу или напоминание. kind: reminder (просто напомнить текстом) или agent (выполнить запрос "
      "ИИ по расписанию, например «сводка погоды»). when: 'in 15m' | 'in 2h' | '18:30' | 'daily 08:00' | "
      "'weekdays 07:30' | 'weekly mon,fri 18:00' | 'every 30m' | 'once 2026-10-26 09:00'. text — что напомнить / что сделать",
      {"text": S, "when": S, "kind": S, "name": S}, ["text", "when"])
def schedule_task(text: str, when: str, kind: str = "reminder", name: str = "") -> str:
    from .. import scheduler
    kind = "agent" if kind not in ("reminder", "command") else kind
    t = scheduler.upsert({"name": name or text[:40], "kind": kind, "prompt": text, "when": when})
    return f"Запланировал «{t['name']}» ({t['describe']}). Виден во вкладке «Чаты» → «Запланированные задачи»."


@tool("list_tasks", "Список запланированных задач и напоминаний")
def list_tasks() -> str:
    from .. import scheduler
    items = scheduler.all_tasks()
    if not items:
        return "Запланированных задач нет."
    return "\n".join(f"- [{t['id']}] {t['name']} — {t.get('describe', '')}{'' if t.get('enabled') else ' (выкл)'}" for t in items)


@tool("cancel_task", "Отменить (удалить) запланированную задачу по id или названию", {"task": S}, ["task"])
def cancel_task(task: str) -> str:
    from .. import scheduler
    for t in scheduler.all_tasks():
        if task in (t["id"], t["name"]) or task.lower() in t["name"].lower():
            scheduler.delete(t["id"])
            return f"Удалил задачу «{t['name']}»."
    return f"Не нашёл задачу «{task}»."


@tool("run_user_command", "Запустить команду пользователя из вкладки «Команды» по названию", {"name": S}, ["name"])
async def run_user_command(name: str, ctx: dict | None = None) -> str:
    from .. import commands
    for c in commands.all_commands():
        if name.lower() in c["name"].lower():
            runner = (ctx or {}).get("agent").command_runner
            log = await runner.run(c["id"])
            return f"Команда «{c['name']}»: " + "; ".join(log)
    return "Нет такой команды. Есть: " + ", ".join(c["name"] for c in commands.all_commands())


@tool("mcp_tools", "Список инструментов подключённого сервиса (коннектора MCP)", {"server": S}, ["server"])
def mcp_tools(server: str) -> str:
    from ..mcp_client import HUB
    s = HUB.servers.get(server)
    if not s:
        return f"Коннектора {server} нет. Подключены: {', '.join(HUB.servers) or 'нет'}"
    return "\n".join(f"- {t['name']}: {t['description'][:160]} | args: {json.dumps(t['schema'].get('properties', {}), ensure_ascii=False)[:300]}"
                     for t in s.tools) or f"{server}: инструментов нет ({s.status})"


@tool("mcp_call", "Вызвать инструмент подключённого сервиса (коннектора MCP). args — JSON-объект аргументов",
      {"server": S, "tool": S, "args": {"type": "object"}}, ["server", "tool"])
async def mcp_call(server: str, tool: str, args: dict | str | None = None) -> str:
    from ..mcp_client import HUB
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            return "args должен быть JSON-объектом"
    s = HUB.servers.get(server)
    if not s:
        return f"Коннектора {server} нет. Подключены: {', '.join(HUB.servers) or 'нет'}"
    names = [t["name"] for t in s.tools]
    if tool not in names:
        cand = [n for n in names if n in tool or tool in n] or (names if len(names) == 1 else [])
        if len(cand) != 1:
            return (f"У {server} нет инструмента {tool}. Есть: " +
                    "; ".join(f"{t['name']}({', '.join(t['schema'].get('properties', {}))})" for t in s.tools) +
                    ". Вызови mcp_call снова с правильным именем.")
        tool = cand[0]
    browse_click = server in ("browser", "devtools") and _re.search(r"(?i)click|hover", tool) and not MCP_FINAL.search(
        json.dumps(args or {}, ensure_ascii=False))
    if MCP_WRITE.search(tool) and not MCP_SAFE.search(tool) and not browse_click:
        import uuid
        tok = uuid.uuid4().hex[:8]
        MCP_PENDING[tok] = (server, tool, args or {})
        return (f"Действие «{server}.{tool}» меняет данные / действует от имени пользователя. Спроси его коротко, что именно "
                f"сделаешь ({json.dumps(args or {}, ensure_ascii=False)[:200]}), и только после «да» вызови "
                f"mcp_call_confirm(token=\"{tok}\").")
    res = await s.call(tool, args or {})
    return res[:12000]


import re as _re
MCP_WRITE = _re.compile(r"(?i)create|update|delete|remove|send|post|reply|draft|push|merge|commit|write|edit|move|archive|"
                        r"label|modify|insert|upload|execute|apply|deploy|comment|click|type|fill|press|select_option|"
                        r"drag|file_upload|handle_dialog|evaluate|run_code|install|invite|share|cancel|book|pay")
MCP_SAFE = _re.compile(r"(?i)^(get|list|search|read|query|fetch|find|browser_snapshot|browser_navigate|browser_navigate_back|"
                       r"browser_take_screenshot|browser_console_messages|browser_network_requests|browser_tabs|browser_wait_for|"
                       r"browser_close|browser_resize|take_|list_|get_|navigate_page|new_page|select_page|wait_for|"
                       r"performance_|emulate)")
MCP_FINAL = _re.compile(r"(?i)send|submit|buy|pay|order|checkout|delete|remove|confirm|publish|post|sign ?out|log ?out|"
                        r"subscribe|unsubscribe|follow|отправ|купить|куп|оплат|заказ|удал|подтверд|опубликов|выйти|подпис|"
                        r"wyślij|kup|zapłać|usuń|potwierdź|wyloguj")
MCP_PENDING: dict = {}


@tool("mcp_call_confirm", "Выполнить действие коннектора, на которое пользователь ответил «да» (token из mcp_call)",
      {"token": S}, ["token"])
async def mcp_call_confirm(token: str) -> str:
    from ..mcp_client import HUB
    p = MCP_PENDING.pop((token or "").strip(), None)
    if not p:
        return "Нет такого ожидающего действия (или уже выполнено)."
    server, tool_name, args = p
    s = HUB.servers.get(server)
    if not s:
        return f"Коннектор {server} не запущен."
    return (await s.call(tool_name, args))[:12000]
