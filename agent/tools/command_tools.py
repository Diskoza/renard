"""The AI creates commands itself (like Astra «Создай команду…»): from its last answer, from everything done in
this conversation, or from steps it lists — with a phrase, a hotkey and / or a schedule as triggers."""
import json
import re
import time

from . import S, tool
from .. import commands as C
from ..logs import quiet


def session_steps(agent, session: str) -> list[dict]:
    """Every replayable step done in this conversation since the last saved command, without exact repeats in a row."""
    out = []
    for e in (agent.action_log.get(session, []) if agent else []):
        if time.time() - e["ts"] > 3 * 3600:
            continue
        for s in e["steps"]:
            if not out or (out[-1]["tool"], out[-1].get("args")) != (s["tool"], s.get("args")):
                out.append(s)
    return out


def _parse_steps(steps) -> list:
    if isinstance(steps, list):
        return steps
    s = (steps or "").strip()
    if not s:
        return []
    try:
        v = json.loads(s)
        return v if isinstance(v, list) else [v]
    except json.JSONDecodeError:
        return [x.strip() for x in re.split(r"[;\n]", s) if x.strip()]


def describe(c: dict) -> str:
    nodes = C._nodes(c)
    trig, acts = [], []
    for n in nodes.values():
        d = n.get("data", {})
        if n["name"] == "trigger_phrase":
            trig.append("фраза «" + d.get("phrases", "").split(",")[0].strip() + "»")
        elif n["name"] == "trigger_hotkey":
            trig.append("клавиши " + d.get("combo", ""))
        elif n["name"] == "trigger_schedule":
            trig.append("расписание " + d.get("when", ""))
        elif n["name"] == "renard_tool":
            try:
                acts.append(C.step_label(d.get("tool", ""), json.loads(d.get("args") or "{}")))
            except json.JSONDecodeError:
                acts.append(d.get("tool", ""))
        else:
            acts.append(C.NODES.get(n["name"], {}).get("title", n["name"]))
    return f"{', '.join(trig)} → {' → '.join(acts)}"


async def create(name: str, phrases: str = "", hotkey: str = "", schedule: str = "", source: str = "", steps=None,
                 ctx: dict | None = None) -> tuple[dict | None, str]:
    agent, session = (ctx or {}).get("agent"), (ctx or {}).get("session") or ""
    src = (source or "").lower().strip()
    if not src:
        src = "steps" if steps else "last"
    if src in ("session", "all", "conversation", "разговор"):
        raw = session_steps(agent, session)
        if not raw:
            return None, "В этом разговоре я ещё ничего не делал на ПК — сначала попроси действия, потом собери из них команду."
    elif src in ("last", "это", "this"):
        la = (agent.last_actions.get(session) if agent else None) or {}
        raw = la.get("steps") or []
        if not raw:
            return None, ("Нечего сохранять: в последнем ответе не было действий. Перечисли шаги в steps или сначала "
                          "попроси меня что-то сделать.")
    else:
        raw = _parse_steps(steps)
    blocks = [b for b in (C.to_block(s) for s in raw) if b]
    if not blocks:
        return None, ("Не получилось разобрать шаги. Пример steps: [{\"block\":\"open_url\",\"url\":\"https://youtube.com\"}, "
                      "{\"tool\":\"volume\",\"args\":{\"action\":\"set\",\"amount\":30}}]")
    triggers = []
    ph = ", ".join(p.strip().lower() for p in re.split(r"[,\n]", phrases or "") if p.strip())
    if ph:
        triggers.append(("trigger_phrase", {"phrases": ph}))
    if (hotkey or "").strip():
        triggers.append(("trigger_hotkey", {"combo": hotkey.strip().lower().replace(" ", "")}))
    if (schedule or "").strip():
        from .. import scheduler
        try:
            scheduler.parse(schedule)
        except ValueError as e:
            return None, str(e)
        triggers.append(("trigger_schedule", {"when": schedule.strip()}))
    if not triggers:
        triggers.append(("trigger_phrase", {"phrases": (name or "моя команда").strip().lower()}))
    c = C.build(name or ph.split(",")[0] or "Команда", triggers, blocks)
    if src in ("session", "all", "conversation", "разговор") and agent:
        agent.action_log.pop(session, None)
    if agent:
        agent.last_actions.pop(session, None)
        try:
            await agent.command_runner.broadcast({"type": "commands_changed"})
        except Exception:
            quiet()
    return c, ""


@tool("make_command",
      "Создать команду-автоматизацию (вкладка «Команды»): потом она выполняется мгновенно, без ИИ. Вызывай, когда просят "
      "«сделай команду / автоматизацию / горячую клавишу на …», «каждый день в 9 делай …», «запомни это / всё что мы делали "
      "как команду». name — название; phrases — фразы запуска через запятую; hotkey — сочетание (ctrl+alt+m); "
      "schedule — расписание: daily 08:30 | weekdays 09:00 | every 60m | weekly sat 10:00; "
      "source: last — действия твоего последнего ответа | session — всё, что делали в этом разговоре | steps — шаги из steps. "
      "steps — JSON-список: инструменты Renard {\"tool\":\"music\",\"args\":{\"action\":\"play\",\"query\":\"lofi\"}} или блоки "
      "{\"block\":\"open_url\",\"url\":\"…\"} {\"block\":\"open_app\",\"name\":\"spotify\"} {\"block\":\"say\",\"text\":\"…\"} "
      "{\"block\":\"notify\",\"text\":\"…\"} {\"block\":\"wait\",\"seconds\":\"5\"} {\"block\":\"keys\",\"combo\":\"ctrl+s\"} "
      "{\"block\":\"type_text\",\"text\":\"…\"} {\"block\":\"ask_ai\",\"prompt\":\"…\"} {\"block\":\"selected_text\"} "
      "{\"block\":\"ai_text\",\"task\":\"переведи на английский\",\"text\":\"{last}\"} {\"block\":\"paste_text\",\"text\":\"{last}\"} "
      "{\"block\":\"power\",\"action\":\"shutdown\",\"minutes\":\"30\"} {\"block\":\"focus\",\"mode\":\"on\"} "
      "{\"block\":\"http\",\"method\":\"POST\",\"url\":\"…\",\"body\":\"…\"}. {last} — результат предыдущего шага.",
      {"name": S, "phrases": S, "hotkey": S, "schedule": S, "source": S, "steps": S}, ["name"])
async def make_command(name: str, phrases: str = "", hotkey: str = "", schedule: str = "", source: str = "", steps="",
                       ctx: dict | None = None) -> str:
    c, err = await create(name, phrases, hotkey, schedule, source, steps, ctx)
    if not c:
        return err
    warn = f" ⚠ {c['schedule_errors'][0]}" if c.get("schedule_errors") else ""
    return (f"Создал команду «{c['name']}»: {describe(c)}.{warn} Она работает сразу, без нейросети; поменять или "
            f"выключить — во вкладке «Команды».")
