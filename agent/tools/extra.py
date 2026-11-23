"""Tools added after real use (25.10): folder access, weather, windows, vision (screen / image), image editing."""
import base64
import io
import re
import time
from pathlib import Path

import httpx

from ..config import SETTINGS
from . import I, S, tool
from .files import add_root, safe


@tool("allow_folder", "Разрешить агенту работать с папкой (если инструмент ответил, что папка не разрешена). "
                      "Система спросит подтверждение у пользователя", {"path": S}, ["path"], confirm=True)
def allow_folder(path: str) -> str:
    p = add_root(path)
    return f"Готово: папка {p} теперь доступна (чтение, запись, удаление в корзину). Повтори действие."


WMO = {0: "ясно", 1: "в основном ясно", 2: "переменная облачность", 3: "пасмурно", 45: "туман", 48: "изморозь",
       51: "морось", 53: "морось", 55: "сильная морось", 61: "небольшой дождь", 63: "дождь", 65: "сильный дождь",
       66: "ледяной дождь", 67: "ледяной дождь", 71: "небольшой снег", 73: "снег", 75: "сильный снег", 77: "снежная крупа",
       80: "ливни", 81: "ливни", 82: "сильные ливни", 85: "снегопад", 86: "сильный снегопад", 95: "гроза",
       96: "гроза с градом", 99: "гроза с градом"}
DAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _case_forms(place: str) -> list[str]:
    """«в Бельгии» -> Бельгия, «в Варшаве» -> Варшава, «в Токио» -> Токио: nominative candidates of a Russian place name."""
    p = re.sub(r"^(в|во|на|w|we|in)\s+", "", place.strip(), flags=re.I)
    out = [p]
    low = p.lower()
    for end, reps in (("ии", ["ия"]), ("ье", ["ья"]), ("е", ["", "а", "ь", "я"]), ("и", ["ь", "а", "я", "ы"]),
                      ("у", ["", "а"]), ("ю", ["я", "ь"]), ("ой", ["ая", "ое"]), ("ом", [""])):
        if low.endswith(end) and len(p) > len(end) + 2:
            out += [p[:-len(end)] + r for r in reps]
    return list(dict.fromkeys(x for x in out if x))


async def geocode(place: str) -> dict:
    """Best match for a city OR a country, any of ru / pl / en spelling; prefers countries, capitals, big cities."""
    best, best_score = None, -1.0
    async with httpx.AsyncClient(timeout=12) as c:
        for name in _case_forms(place)[:6]:
            for lang in ("ru", "pl", "en"):
                try:
                    res = (await c.get("https://geocoding-api.open-meteo.com/v1/search",
                                       params={"name": name, "count": 5, "language": lang})).json().get("results") or []
                except Exception:
                    continue
                for g in res:
                    exact = g.get("name", "").lower() == name.lower()
                    fc = g.get("feature_code", "")
                    score = (3 if exact else 0) + (2 if fc in ("PCLI", "PPLC") else 1 if fc.startswith("PPLA") else 0) \
                        + min((g.get("population") or 0) / 2e6, 2)
                    if score > best_score:
                        best, best_score = g, score
            if best_score >= 4:
                break
    if not best:
        raise ValueError(f"Не нашёл место «{place}». Напиши его по-другому (например, латиницей).")
    return best


async def weather_data(city: str, days: int = 3) -> dict:
    """Structured weather (also used by the home-screen widget)."""
    days = max(1, min(int(days or 3), 7))
    g = await geocode(city)
    async with httpx.AsyncClient(timeout=15) as c:
        f = (await c.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": g["latitude"], "longitude": g["longitude"], "timezone": "auto", "forecast_days": days,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
            "wind_speed_unit": "ms"})).json()
    cur, d = f["current"], f["daily"]
    out = {"city": g["name"], "country": g.get("country", ""), "temp": cur["temperature_2m"],
           "feels": cur["apparent_temperature"], "code": cur["weather_code"], "text": WMO.get(cur["weather_code"], "?"),
           "wind": cur["wind_speed_10m"], "humidity": cur["relative_humidity_2m"], "days": []}
    for i, day in enumerate(d["time"]):
        wd = DAYS[time.strptime(day, "%Y-%m-%d").tm_wday]
        out["days"].append({"date": day, "label": "сегодня" if i == 0 else "завтра" if i == 1 else f"{wd} {day[8:]}.{day[5:7]}",
                            "min": d["temperature_2m_min"][i], "max": d["temperature_2m_max"][i],
                            "code": d["weather_code"][i], "text": WMO.get(d["weather_code"][i], "?"),
                            "rain_mm": d["precipitation_sum"][i], "rain_pct": d["precipitation_probability_max"][i],
                            "wind": d["wind_speed_10m_max"][i]})
    return out


@tool("world_time", "Который час сейчас в другом городе или стране (часовой пояс, разница с моим временем). "
      "place — город или страна («Бельгия», «Tokio», «New York»)", {"place": S}, ["place"])
async def world_time(place: str) -> str:
    import datetime as dt
    try:
        g = await geocode(place)
    except ValueError as e:
        return str(e)
    async with httpx.AsyncClient(timeout=12) as c:
        f = (await c.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": g["latitude"], "longitude": g["longitude"], "timezone": "auto", "current": "temperature_2m"})).json()
    off = f.get("utc_offset_seconds", 0)
    there = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=off)
    diff = (off - dt.datetime.now().astimezone().utcoffset().total_seconds()) / 3600
    where = g["name"] + (f", {g['country']}" if g.get("country") and g.get("country") != g["name"] else "")
    return (f"{where}: сейчас {there:%H:%M}, {there:%d.%m.%Y} (часовой пояс {f.get('timezone', g.get('timezone', '?'))}, "
            f"{'+' if diff >= 0 else ''}{diff:g} ч к времени пользователя)")


@tool("weather", "Погода сейчас и прогноз. city — город ИЛИ страна, о которой спросили («Бельгия», «Варшава»); "
                 "пусто = домашний город пользователя. days: 1-7",
      {"city": S, "days": I}, [])
async def weather(city: str = "", days: int = 3) -> str:
    from ..prefs import get as pget
    city = (city or pget("home_city") or (SETTINGS.get("home_city") or "London")).strip()
    try:
        w = await weather_data(city, days)
    except ValueError as e:
        return str(e)
    out = [f"{w['city']} ({w['country']}). Сейчас {w['temp']:+.0f}°C, ощущается {w['feels']:+.0f}°C, {w['text']}, "
           f"ветер {w['wind']:.0f} м/с, влажность {w['humidity']}%."]
    for x in w["days"]:
        out.append(f"- {x['label']}: {x['min']:+.0f}…{x['max']:+.0f}°C, {x['text']}, осадки {x['rain_mm']:.1f} мм "
                   f"({x['rain_pct']}%), ветер до {x['wind']:.0f} м/с")
    return "\n".join(out)


def minimize_all(restore: bool = False) -> str:
    """Show the desktop / bring the windows back (used by tools/apps.py «windows»)."""
    import pythoncom
    from win32com.client import Dispatch
    pythoncom.CoInitialize()
    sh = Dispatch("Shell.Application")
    if restore:
        sh.UndoMinimizeALL()
        return "Вернул окна."
    sh.MinimizeAll()
    return "Свернул все окна."


def _img_b64(img, max_side: int = 1600) -> str:
    from PIL import Image
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


async def _ask_vision(ctx: dict, b64: str, question: str) -> str:
    agent = ctx.get("agent")
    if agent is None:
        return "Ошибка: зрение доступно только через агента."
    mode = "low"
    caps = await agent.llm.capabilities(agent.llm.mode_cfg(mode)["model"])
    if "vision" not in caps:
        return "Текущая модель не умеет смотреть на картинки (нет vision)."
    msg = [{"role": "system", "content": "Ты смотришь на изображение. Отвечай на языке вопроса (обычно русский), "
                                         "конкретно: что видно, тексты (дословно, на языке оригинала), ошибки, элементы "
                                         "интерфейса. Не выдумывай того, чего не видно."},
           {"role": "user", "content": question or "Опиши, что на изображении.", "images": [b64]}]
    r = await agent.llm.chat(mode, msg)
    return (r.get("message") or {}).get("content", "").strip() or "(модель ничего не ответила)"


@tool("look_at_screen", "Сделать скриншот экрана и посмотреть на него (что открыто, ошибка на экране, интерфейс программы). "
                        "question — что именно найти/понять", {"question": S}, [])
async def look_at_screen(question: str = "", ctx: dict | None = None) -> str:
    from PIL import ImageGrab
    shot = ImageGrab.grab(all_screens=True)
    out = Path(SETTINGS.get("workspace", "workspace")) / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    f = out / time.strftime("screen_%Y%m%d_%H%M%S.png")
    shot.save(f)
    ans = await _ask_vision(ctx or {}, _img_b64(shot), question)
    return f"{ans}\n(скриншот: {f})"


@tool("look_at_image", "Посмотреть на картинку/фото/скриншот из файла и ответить на вопрос о ней",
      {"path": S, "question": S}, ["path"])
async def look_at_image(path: str, question: str = "", ctx: dict | None = None) -> str:
    from PIL import Image
    p = safe(path)
    if not p.is_file():
        return (f"Файла {p} нет на диске. Если описание этой картинки уже есть в сообщении пользователя (результат "
                f"зрения) — отвечай по нему и не проси прислать её снова.")
    return await _ask_vision(ctx or {}, _img_b64(Image.open(p)), question)


