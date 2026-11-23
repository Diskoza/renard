"""«Здоровье Renard»: is every part alive, what broke lately, where the time goes, how the last tests went.

check(S) -> {"items": [{"id", "name", "level": ok|warn|bad|off, "detail"}], "speed": …, "errors": […], "tests": …}
Run once ~40 s after start (one log line: what is not ok) and on demand: GET /api/health (the «Здоровье» page).
"""
import asyncio
import json
import re
import shutil
import time
from pathlib import Path

from .config import DATA_DIR, SETTINGS
from .logs import quiet

ROOT = Path(__file__).resolve().parent.parent
LOG = DATA_DIR / "logs" / "renard.log"
LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\s+\S+\s+(\w+)\s+(.*)$")


def _item(id_, name, level, detail=""):
    return {"id": id_, "name": name, "level": level, "detail": detail}


async def _ollama(agent) -> list[dict]:
    out = []
    llm = agent.llm
    if not await llm.alive():
        return [_item("ollama", "Ollama (локальные модели)", "bad", "не отвечает — ответы ИИ не работают")]
    try:
        r = await llm.client.get("/api/tags", timeout=5)
        have = {m["name"] for m in r.json().get("models", [])}
    except Exception as e:
        return [_item("ollama", "Ollama (локальные модели)", "warn", f"список моделей не получен: {type(e).__name__}")]
    loaded = [m.get("name") for m in await llm.loaded_models()]
    out.append(_item("ollama", "Ollama (локальные модели)", "ok",
                     f"в видеопамяти: {', '.join(loaded) or 'ничего (первый ответ будет дольше)'}"))
    missing = sorted({cfg.get("model", "") for name, cfg in llm.modes.items()
                      if not name.startswith("_") and cfg.get("model") and not cfg["model"].startswith("@")} - have
                     - {m.removesuffix(":latest") for m in have})
    from .llm import GAME_MODEL
    if GAME_MODEL not in have and f"{GAME_MODEL}:latest" not in have:
        missing.append(f"{GAME_MODEL} (игровой режим)")
    out.append(_item("models", "Модели режимов", "bad" if missing else "ok",
                     ("не скачаны: " + ", ".join(missing)) if missing else f"все на месте ({len(have)} в Ollama)"))
    return out


def _services(S) -> list[dict]:
    out = []
    tg = S.telegram.status() if getattr(S, "telegram", None) else {}
    if not tg.get("configured"):
        out.append(_item("telegram", "Telegram-бот", "off", "не настроен"))
    else:
        out.append(_item("telegram", "Telegram-бот", "ok" if tg.get("connected") else "bad",
                         f"@{tg.get('bot')}, связанных: {tg.get('paired')}" if tg.get("connected")
                         else f"не подключён {tg.get('error') or ''}".strip()))
    wake = getattr(S, "wake", None)
    if wake is not None:
        from .wake import wanted
        want = wanted()
        if wake.enabled:
            out.append(_item("wake", "Слово-пробуждение", "ok", f"слушает{(' (' + wake.device + ')') if wake.device else ''}"))
        else:
            out.append(_item("wake", "Слово-пробуждение", "warn" if want else "off", "включено в настройках, но не слушает"
                             if want else "выключено"))
    from .mcp_client import HUB
    srv = list(HUB.servers.values())
    if srv:
        bad = [f"{s.name} ({s.error[:80] or s.status})" for s in srv if s.status == "error"]
        ready = sum(s.status == "ready" for s in srv)
        out.append(_item("mcp", "Коннекторы (MCP)", "warn" if bad else "ok",
                         f"готово {ready} из {len(srv)}" + ("; ошибки: " + "; ".join(bad[:4]) if bad else "")))
    from . import corrections
    learned = corrections.load()
    if learned:
        out.append(_item("learned", "Выучено из поправок", "ok",
                         f"{len(learned)} связок «просьба → инструмент», последняя: «{learned[-1]['phrase'][:50]}» → "
                         f"{learned[-1]['tool']}"))
    from . import cloud
    st = cloud.status()
    out.append(_item("cloud", "Облачные модели", "ok" if st.get("ready") else "off",
                     f"{st.get('provider')}:{st.get('model')}, разрешение «{st.get('permission')}»" if st.get("ready")
                     else "не подключены (ИИ → Облачные модели)"))
    return out


def _system() -> list[dict]:
    out = []
    try:
        free = shutil.disk_usage(DATA_DIR).free / 1e9
        out.append(_item("disk", "Место для данных", "bad" if free < 2 else "warn" if free < 10 else "ok",
                         f"свободно {free:.0f} ГБ на диске с data/"))
    except Exception:
        quiet()
    try:
        from . import media_now
        busy = media_now._W.get("busy_since") or 0
        if busy and time.time() - busy > 30:
            out.append(_item("media", "Медиа Windows («Сейчас играет»)", "warn",
                             f"сеанс Windows не отвечает {time.time() - busy:.0f} с (перезапусков потока: {media_now._W.get('gen')})"))
        else:
            out.append(_item("media", "Медиа Windows («Сейчас играет»)", "ok", "отвечает"))
    except Exception:
        quiet()
    return out


def recent_errors(hours: float = 24, limit: int = 8) -> dict:
    """ERROR / WARNING lines of renard.log from the last hours, grouped (the same warning 200× is one row)."""
    if not LOG.exists():
        return {"errors": 0, "warnings": 0, "top": []}
    since = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - hours * 3600))
    groups: dict[str, dict] = {}
    n_err = n_warn = 0
    try:
        with LOG.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4_000_000))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return {"errors": 0, "warnings": 0, "top": []}
    for line in lines:
        m = LINE.match(line)
        if not m or m.group(1) < since or m.group(2) not in ("ERROR", "WARNING", "CRITICAL"):
            continue
        lvl, msg = m.group(2), m.group(3)
        if lvl == "WARNING":
            n_warn += 1
        else:
            n_err += 1
        sig = re.sub(r"\d+(\.\d+)?", "N", msg)[:90]
        g = groups.setdefault(sig, {"level": lvl, "text": msg[:240], "count": 0, "last": m.group(1)})
        g["count"] += 1
        g["last"], g["text"] = m.group(1), msg[:240]
    top = sorted(groups.values(), key=lambda g: (g["level"] == "WARNING", -g["count"]))[:limit]
    return {"errors": n_err, "warnings": n_warn, "top": top}


def stuck_report(path: Path | None = None, limit: int = 5) -> list[dict]:
    """Where the server's event loop got stuck (faulthandler dumps in loop_stuck.log, main.py): the first frame of OUR
    code in the loop thread's stack, grouped. [{"where", "count", "last", "longest"}]"""
    path = path or DATA_DIR / "logs" / "loop_stuck.log"
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[-1_500_000:]
    except OSError:
        return []
    groups: dict[str, dict] = {}
    parts =re.split(r"(?m)^\^\^\^ ", text)
    for i in range(len(parts) - 1):
        dump, tail = parts[i], parts[i + 1]
        m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}): event loop was stuck ([\d.]+)s", tail)
        if not m or "Timeout" not in dump:
            continue
        dump = dump[dump.rfind("Timeout"):]
        threads = re.split(r"(?m)^(?:Current thread|Thread) 0x", dump)
        loop = next((t for t in threads if "run_forever" in t), "")
        frames = re.findall(r'File "([^"]+)", line (\d+) in (\S+)', loop)
        ours = [f for f in frames if "pc-agent" in f[0] and ".venv" not in f[0]]
        lib = frames[0] if frames else ("?", "0", "?")
        f = ours[0] if ours else lib
        where = f"{Path(f[0]).name}:{f[1]} {f[2]}" + ("" if ours else " (библиотека)")
        g = groups.setdefault(where, {"where": where, "count": 0, "last": "", "longest": 0.0})
        g["count"] += 1
        g["last"] = m.group(1)
        g["longest"] = max(g["longest"], float(m.group(2)))
    return sorted(groups.values(), key=lambda g: -g["count"])[:limit]


def last_tests() -> dict:
    out = {}
    d = ROOT / "eval" / "results"
    res = sorted(p for p in d.glob("*.md") if re.fullmatch(r"\d{8}-\d{6}\.md", p.name)) if d.exists() else []
    if res:
        m = re.search(r"\*\*Итог: (\d+)/(\d+)\*\*", res[-1].read_text(encoding="utf-8", errors="replace"))
        if m:
            out["eval"] = {"ok": int(m.group(1)), "total": int(m.group(2)), "file": res[-1].name}
    rp = DATA_DIR / "replay" / "last.json"
    if rp.exists():
        try:
            out["replay"] = json.loads(rp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            quiet()
    return out


async def check(S) -> dict:
    items = []
    try:
        items += await asyncio.wait_for(_ollama(S.agent), 15)
    except Exception as e:
        items.append(_item("ollama", "Ollama (локальные модели)", "bad", f"проверка не прошла: {type(e).__name__}"))
    for part in (_services, lambda _S: _system()):
        try:
            items += part(S)
        except Exception as e:
            items.append(_item("check", "Проверка", "warn", f"{type(e).__name__}: {e}"[:200]))
    from . import timing
    errs = await asyncio.to_thread(recent_errors)
    if errs["errors"]:
        items.append(_item("log", "Ошибки за сутки", "warn", f"{errs['errors']} ошибок, {errs['warnings']} предупреждений"))
    stuck = await asyncio.to_thread(stuck_report)
    if stuck:
        top = stuck[0]
        items.append(_item("stuck", "Подвисания сервера", "warn",
                           f"чаще всего в {top['where']} ({top['count']}×, до {top['longest']:.0f} с, последнее {top['last'][5:16]})"))
    return {"ts": time.time(), "items": items, "speed": timing.report(timing.load(200)), "log": errs, "stuck": stuck,
            "tests": last_tests(), "keep_warm": SETTINGS.get("agent", {}).get("keep_warm", True)}


async def startup_check(S, delay: float = 40):
    """One line in renard.log after start: what is not ok (Ollama down, a model missing, the bot offline…)."""
    from .logs import log
    await asyncio.sleep(delay)
    try:
        r = await check(S)
        bad = [f"{i['name']}: {i['detail']}" for i in r["items"] if i["level"] in ("bad", "warn")]
        if bad:
            log.warning("health: " + " | ".join(bad))
        else:
            log.info(f"health: all {len(r['items'])} checks ok")
    except Exception:
        quiet()
