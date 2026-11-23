"""Scheduled tasks & reminders (data/tasks.json). Checked every 20 s by the server.

kinds:  agent    — run a prompt through Renard (result saved as a chat «Задача: …», notification)
        reminder — just remind (toast + window + Telegram, optionally spoken)
        command  — run a node command from «Команды»
schedule strings (UI and the agent use the same format):
  "once 2026-10-26 09:00" | "in 15m" | "in 2h" | "daily 08:00" | "weekdays 07:30" | "weekly mon,fri 18:00" | "every 30m"
"""
import asyncio
import json
import re
import time
import uuid
from datetime import datetime, timedelta

from .config import DATA_DIR

PATH = DATA_DIR / "tasks.json"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
RU_DAYS = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6}


def _load() -> list[dict]:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(items):
    PATH.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def parse(spec: str) -> dict:
    s = spec.strip().lower()
    s = (s.replace("через", "in").replace("каждый день", "daily").replace("ежедневно", "daily")
          .replace("по будням", "weekdays").replace("каждые", "every").replace("каждый", "every")
          .replace("минут", "m").replace("мин", "m").replace("часа", "h").replace("часов", "h").replace("час", "h"))
    m = re.match(r"^in\s+(\d+)\s*([mh])", s)
    if m:
        delta = timedelta(minutes=int(m.group(1)) * (60 if m.group(2) == "h" else 1))
        return {"type": "once", "at": (datetime.now() + delta).timestamp()}
    m = re.match(r"^every\s+(\d+)\s*([mh])", s)
    if m:
        return {"type": "interval", "every_min": int(m.group(1)) * (60 if m.group(2) == "h" else 1)}
    t = re.search(r"(\d{1,2})[:.](\d{2})", s)
    hhmm = f"{int(t.group(1)):02d}:{t.group(2)}" if t else "09:00"
    if s.startswith("daily"):
        return {"type": "daily", "time": hhmm}
    if s.startswith("weekdays"):
        return {"type": "weekly", "time": hhmm, "days": [0, 1, 2, 3, 4]}
    if s.startswith("weekly"):
        days = [DAYS.index(d) for d in re.findall(r"mon|tue|wed|thu|fri|sat|sun", s)]
        days += [v for k, v in RU_DAYS.items() if re.search(rf"\b{k}", s)]
        return {"type": "weekly", "time": hhmm, "days": sorted(set(days)) or [0]}
    d = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if d or s.startswith("once") or t:
        day = datetime(int(d.group(1)), int(d.group(2)), int(d.group(3))) if d else datetime.now()
        at = day.replace(hour=int(hhmm[:2]), minute=int(hhmm[3:]), second=0, microsecond=0)
        if not d and at < datetime.now():
            at += timedelta(days=1)
        while d and at < datetime.now() - timedelta(hours=1):
            at = at.replace(year=at.year + 1)
        return {"type": "once", "at": at.timestamp()}
    raise ValueError(f"не понял расписание «{spec}». Примеры: in 15m, daily 08:00, weekdays 07:30, every 30m")


def next_run(sch: dict, after: float | None = None) -> float | None:
    now = datetime.fromtimestamp(after or time.time())
    if sch["type"] == "once":
        return sch["at"] if sch["at"] > (after or 0) - 1 else None
    if sch["type"] == "interval":
        return (now + timedelta(minutes=sch["every_min"])).timestamp()
    hh, mm = int(sch["time"][:2]), int(sch["time"][3:])
    for i in range(0, 8):
        d = (now + timedelta(days=i)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        if d <= now:
            continue
        if sch["type"] == "daily" or d.weekday() in sch.get("days", []):
            return d.timestamp()
    return None


def describe(sch: dict) -> str:
    if sch["type"] == "once":
        return "один раз " + datetime.fromtimestamp(sch["at"]).strftime("%d.%m.%Y %H:%M")
    if sch["type"] == "interval":
        return f"каждые {sch['every_min']} мин"
    if sch["type"] == "daily":
        return f"каждый день в {sch['time']}"
    names = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
    if sch.get("days") == [0, 1, 2, 3, 4]:
        return f"по будням в {sch['time']}"
    return ", ".join(names[d] for d in sch.get("days", [])) + f" в {sch['time']}"


def all_tasks() -> list[dict]:
    return _load()


def upsert(data: dict) -> dict:
    items = _load()
    tid = data.get("id") or uuid.uuid4().hex[:8]
    cur = next((t for t in items if t["id"] == tid), None)
    if cur is None:
        cur = {"id": tid, "name": "", "kind": "agent", "prompt": "", "command": "", "enabled": True, "speak": False,
               "telegram": True, "last_run": None, "last_result": "", "created": time.time()}
        items.append(cur)
    for k in ("name", "kind", "prompt", "command", "enabled", "speak", "telegram"):
        if k in data:
            cur[k] = data[k]
    if data.get("when"):
        cur["when"] = data["when"]
        cur["schedule"] = parse(data["when"])
    if "schedule" not in cur:
        raise ValueError("нет расписания")
    cur["next_run"] = next_run(cur["schedule"]) if cur["enabled"] else None
    cur["describe"] = describe(cur["schedule"])
    if not cur["name"]:
        cur["name"] = (cur["prompt"] or cur["command"] or "задача")[:40]
    _save(items)
    return cur


def delete(tid: str) -> bool:
    items = _load()
    new = [t for t in items if t["id"] != tid]
    _save(new)
    return len(new) != len(items)


def _mark(tid: str, result: str):
    items = _load()
    for t in items:
        if t["id"] == tid:
            t["last_run"] = time.time()
            t["last_result"] = result[:500]
            t["next_run"] = next_run(t["schedule"], time.time() + 1) if t["schedule"]["type"] != "once" else None
            if t["schedule"]["type"] == "once":
                t["enabled"] = False
    _save(items)


class Scheduler:
    def __init__(self, agent, broadcast, notify_tg=None, run_command=None):
        self.agent, self.broadcast, self.notify_tg, self.run_command = agent, broadcast, notify_tg, run_command
        self.running: set[str] = set()

    async def loop(self):
        while True:
            await asyncio.sleep(20)
            now = time.time()
            for t in _load():
                if t.get("enabled") and t.get("next_run") and t["next_run"] <= now and t["id"] not in self.running:
                    asyncio.create_task(self.run(t))

    async def run(self, t: dict) -> str:
        self.running.add(t["id"])
        try:
            await self.broadcast({"type": "activity", "source": "task", "note": f"задача «{t['name']}»…"})
            if t["kind"] == "reminder":
                result = t["prompt"] or t["name"]
            elif t["kind"] == "command" and self.run_command:
                result = "\n".join(await self.run_command(t["command"]))
            else:
                answer = []

                async def send(ev):
                    if ev.get("type") == "token":
                        answer.append(ev["text"])
                async with self.agent.lock:
                    await self.agent.handle(t["prompt"], f"task-{t['id']}", send, None, perm="auto")
                result = "".join(answer).strip() or "(пустой ответ)"
            _mark(t["id"], result)
            from .tools.system import toast
            toast(f"Renard · {t['name']}", result[:200])
            await self.broadcast({"type": "task", "id": t["id"], "name": t["name"], "kind": t["kind"], "text": result})
            if t.get("telegram") and self.notify_tg:
                await self.notify_tg(f"⏰ {t['name']}\n{result}")
            if t.get("speak"):
                from . import voice
                from .wake import play_wav
                wav = await asyncio.to_thread(voice.tts.synth, result)
                if wav:
                    await asyncio.to_thread(play_wav, wav)
            return result
        except Exception as e:
            _mark(t["id"], f"ошибка: {e}")
            return f"ошибка: {e}"
        finally:
            self.running.discard(t["id"])
            await self.broadcast({"type": "activity", "source": "task", "note": ""})
