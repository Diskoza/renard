"""Steam: his library from the local Steam files (no key needed) + the public Store API.

Local: libraryfolders.vdf -> all libraries; appmanifest_*.acf -> installed games, size, update / download state;
userdata/<id>/config/localconfig.vdf -> playtime and last played per game.
Store: search, details, price and discount in his account's region (UA → hryvnia; prefs steam.cc overrides).
Wishlist («желаемое»): IWishlistService/GetWishlist for the steamid logged in on this PC + IStoreBrowseService prices.
Watchlist (prefs steam.watch): «следи за скидкой на X» -> «что со скидками» shows the current price / discount.
Opening pages goes through steam:// links (the Steam window does it).
"""
import datetime as dt
import json
import os
import re
import time
from pathlib import Path

import httpx

from . import I, S, tool

UA = {"User-Agent": "Renard-local-assistant/1.0 (personal desktop assistant)"}
_cache: dict[str, tuple[float, object]] = {}


def parse_vdf(text: str) -> dict:
    """Valve KeyValues text -> nested dicts."""
    toks = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    stack, cur, key = [], {}, None
    root = cur
    for s, br in toks:
        if br == "{":
            new = {}
            cur[key] = new
            stack.append(cur)
            cur, key = new, None
        elif br == "}":
            cur = stack.pop() if stack else cur
            key = None
        elif key is None:
            key = s
        else:
            cur[key] = s.replace("\\\\", "\\")
            key = None
    return root


def steam_dir() -> Path | None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            p = Path(winreg.QueryValueEx(k, "SteamPath")[0])
            if p.exists():
                return p
    except OSError:
        pass
    for p in (Path(r"C:\Program Files (x86)\Steam"), Path(r"D:\Steam")):
        if p.exists():
            return p
    return None


def libraries() -> list[Path]:
    sd = steam_dir()
    if not sd:
        return []
    out = [sd / "steamapps"]
    f = sd / "steamapps" / "libraryfolders.vdf"
    if f.exists():
        data = parse_vdf(f.read_text(encoding="utf-8", errors="replace")).get("libraryfolders", {})
        for v in data.values():
            if isinstance(v, dict) and v.get("path"):
                p = Path(v["path"]) / "steamapps"
                if p.exists() and p not in out:
                    out.append(p)
    return out


def installed() -> list[dict]:
    games = []
    for lib in libraries():
        for f in lib.glob("appmanifest_*.acf"):
            try:
                st = parse_vdf(f.read_text(encoding="utf-8", errors="replace")).get("AppState", {})
            except Exception:
                continue
            name = st.get("name", "")
            if not name or re.search(r"redistributable|steamworks common|proton|steam linux runtime", name, re.I):
                continue
            flags = int(st.get("StateFlags", "4") or 4)
            todo = int(st.get("BytesToDownload", "0") or 0)
            done = int(st.get("BytesDownloaded", "0") or 0)
            state = "установлена" if flags == 4 else "нужно обновление" if flags & 2 else \
                "качается" if flags & 1024 or todo else "в очереди" if flags & 512 else f"состояние {flags}"
            games.append({"appid": st.get("appid"), "name": name, "size_gb": int(st.get("SizeOnDisk", "0") or 0) / 1e9,
                          "state": state, "progress": f"{100 * done / todo:.0f}%" if todo and done else "",
                          "updated": int(st.get("LastUpdated", "0") or 0), "lib": str(lib.parent)})
    return games


def playtime() -> dict[str, dict]:
    """appid -> {minutes, last}: from the most recently used Steam account's localconfig.vdf."""
    sd = steam_dir()
    if not sd:
        return {}
    cfgs = sorted((sd / "userdata").glob("*/config/localconfig.vdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not cfgs:
        return {}
    key = f"pt:{cfgs[0]}:{cfgs[0].stat().st_mtime}"
    if key in _cache:
        return _cache[key][1]
    data = parse_vdf(cfgs[0].read_text(encoding="utf-8", errors="replace"))
    apps = {}
    node = data.get("UserLocalConfigStore", {}).get("Software", {}).get("Valve", {}).get("Steam", {})
    node = node.get("apps") or node.get("Apps") or {}
    for appid, v in node.items():
        if isinstance(v, dict):
            apps[appid] = {"minutes": int(v.get("Playtime", "0") or 0), "last": int(v.get("LastPlayed", "0") or 0)}
    _cache[key] = (time.time(), apps)
    return apps


def _ago(ts: int) -> str:
    if not ts:
        return "не запускал"
    d = (dt.date.today() - dt.date.fromtimestamp(ts)).days
    return "сегодня" if d == 0 else "вчера" if d == 1 else f"{d} дн. назад" if d < 60 else dt.date.fromtimestamp(ts).strftime("%d.%m.%Y")


def _hours(m: int) -> str:
    return f"{m / 60:.1f} ч" if m >= 60 else f"{m} мин"


async def _get(url: str, params: dict, ttl: int = 1800):
    key = url + repr(sorted(params.items()))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    async with httpx.AsyncClient(headers=UA, timeout=15) as c:
        r = await c.get(url, params=params)
    r.raise_for_status()
    data = r.json()
    _cache[key] = (time.time(), data)
    return data


def _cc() -> str:
    """Store region = the currency his account pays in (UA → hryvnia). prefs steam.cc overrides."""
    try:
        from ..prefs import get
        return (get("steam.cc", "") or "UA").upper()
    except Exception:
        return "UA"


def my_steamid() -> str:
    """steamid64 of the account logged in on this PC (loginusers.vdf, MostRecent first)."""
    root = steam_dir()
    f = root / "config" / "loginusers.vdf" if root else None
    if not f or not f.exists():
        return ""
    users = (parse_vdf(f.read_text("utf-8", "ignore")).get("users") or {})
    best = ""
    for sid, u in users.items():
        if not best or str((u or {}).get("MostRecent", (u or {}).get("mostrecent", "0"))) == "1":
            best = sid
    return best


async def store_search(q: str, n: int = 6) -> list[dict]:
    d = await _get("https://store.steampowered.com/api/storesearch/", {"term": q, "l": "russian", "cc": _cc()})
    return (d or {}).get("items", [])[:n]


async def details(appid: str) -> dict:
    d = await _get("https://store.steampowered.com/api/appdetails", {"appids": appid, "cc": _cc().lower(), "l": "russian"})
    return ((d or {}).get(str(appid)) or {}).get("data") or {}


async def items(appids: list) -> list[dict]:
    """name + current price/discount for many apps at once (IStoreBrowseService, the store's own API)."""
    out = []
    for i in range(0, len(appids), 50):
        chunk = appids[i:i + 50]
        req = {"ids": [{"appid": int(a)} for a in chunk], "context": {"language": "russian", "country_code": _cc()},
               "data_request": {"include_basic_info": False}}
        d = await _get("https://api.steampowered.com/IStoreBrowseService/GetItems/v1/", {"input_json": json.dumps(req)}, ttl=900)
        for it in ((d or {}).get("response") or {}).get("store_items", []):
            bp = it.get("best_purchase_option") or {}
            out.append({"appid": str(it.get("appid") or it.get("id")), "name": it.get("name") or "?",
                        "price": bp.get("formatted_final_price") or ("бесплатно" if it.get("is_free") else "нет в продаже"),
                        "was": bp.get("formatted_original_price", ""), "discount": int(bp.get("discount_pct") or 0),
                        "cents": int(bp.get("final_price_in_cents") or 0)})
    return out


async def wishlist() -> list[dict]:
    """His Steam wishlist («желаемое») with prices in his region; raises if the profile hides it."""
    sid = my_steamid()
    if not sid:
        raise RuntimeError("не нашёл аккаунт Steam на этом ПК")
    d = await _get("https://api.steampowered.com/IWishlistService/GetWishlist/v1/", {"steamid": sid}, ttl=900)
    ids = [str(x["appid"]) for x in ((d or {}).get("response") or {}).get("items", [])]
    if not ids:
        raise RuntimeError("Steam не отдал список желаемого (пустой или скрыт в настройках приватности профиля)")
    return await items(ids)


def _price(p: dict | None) -> str:
    if not p:
        return "бесплатно или цены нет"
    s = p.get("final_formatted") or f"{p.get('final', 0) / 100:.2f} {p.get('currency', '')}"
    if p.get("discount_percent"):
        s += f" (скидка {p['discount_percent']}%, было {p.get('initial_formatted') or p.get('initial', 0) / 100})"
    return s


async def _resolve(game: str) -> tuple[str, str]:
    """name -> (appid, name): the installed game first, else the store's first hit."""
    g = (game or "").strip()
    if g.isdigit():
        return g, g
    low = g.lower()
    for x in installed():
        if low in x["name"].lower():
            return x["appid"], x["name"]
    hits = await store_search(g, 1)
    return (str(hits[0]["id"]), hits[0]["name"]) if hits else ("", "")


@tool("steam",
      "Steam пользователя. action: library (установленные игры, размер, время в игре, когда запускал), recent (во что "
      "играл недавно), downloads (что качается / ждёт обновления), search (поиск в магазине, query), info (об игре: цена, "
      "скидка, жанры, описание; game), open (открыть в Steam: game — страница игры в магазине / library / downloads / "
      "friends; launch — запустить игру), watch (следить за ценой игры game), wishlist (его список желаемого Steam с "
      "ценами), deals (какие игры из ЖЕЛАЕМОГО и списка слежения сейчас со скидкой). «желаемое», «игры которые я хочу», "
      "«скидки на мои игры» = deals, НЕ search. Цены в его валюте (гривны).",
      {"action": S, "query": S, "game": S, "n": I}, ["action"])
async def steam(action: str = "library", query: str = "", game: str = "", n: int = 15) -> str:
    a = (action or "library").lower()
    game = game or query
    if a in ("library", "games", "installed", "recent"):
        games, pt = installed(), playtime()
        if not games:
            return "Не нашёл библиотек Steam на этом ПК."
        for g in games:
            p = pt.get(str(g["appid"]), {})
            g["minutes"], g["last"] = p.get("minutes", 0), p.get("last", 0)
        if a == "recent":
            games = [g for g in games if g["last"]]
            games.sort(key=lambda g: g["last"], reverse=True)
        else:
            games.sort(key=lambda g: g["minutes"], reverse=True)
        total = sum(g["size_gb"] for g in installed())
        rows = [f"- {g['name']}: {_hours(g['minutes'])} в игре, запускал {_ago(g['last'])}, {g['size_gb']:.1f} ГБ"
                + (f" — {g['state']}" if g["state"] != "установлена" else "") for g in games[:max(1, n)]]
        head = "Недавно играл:" if a == "recent" else f"Установлено игр Steam: {len(installed())} ({total:.0f} ГБ), по времени в игре:"
        return head + "\n" + "\n".join(rows)
    if a in ("downloads", "updates", "загрузки"):
        busy = [g for g in installed() if g["state"] != "установлена"]
        return ("Steam сейчас:\n" + "\n".join(f"- {g['name']}: {g['state']} {g['progress']}" for g in busy)) if busy \
            else "Все игры Steam установлены и обновлены, ничего не качается."
    if a in ("search", "find", "поиск"):
        if not game:
            return "Что искать в магазине Steam? (query)"
        hits = await store_search(game, max(3, min(n, 10)))
        if not hits:
            return f"В магазине Steam ничего не нашлось по «{game}»."
        have = {str(g["appid"]) for g in installed()}
        return f"Steam, поиск «{game}»:\n" + "\n".join(
            f"- {h['name']} (id {h['id']}): {_price(h.get('price')) if h.get('price') else 'бесплатно/нет цены'}"
            + (" — уже установлена" if str(h['id']) in have else "") for h in hits)
    if a in ("info", "price", "details"):
        appid, name = await _resolve(game)
        if not appid:
            return f"Не нашёл «{game}» в Steam."
        d = await details(appid)
        if not d:
            return f"Steam не отдал данные об игре {name} (id {appid})."
        pt = playtime().get(str(appid), {})
        genres = ", ".join(x.get("description", "") for x in d.get("genres", [])[:4])
        desc = re.sub(r"<[^>]+>", "", d.get("short_description", ""))[:300]
        return (f"{d.get('name')} (id {appid})\nЦена: {_price(d.get('price_overview')) if not d.get('is_free') else 'бесплатная'}\n"
                f"Жанры: {genres}\nВыход: {(d.get('release_date') or {}).get('date', '?')}\n"
                + (f"Твоё время: {_hours(pt.get('minutes', 0))}, запускал {_ago(pt.get('last', 0))}\n" if pt else "")
                + f"{desc}\nhttps://store.steampowered.com/app/{appid}/")
    if a in ("open", "launch", "run", "play"):
        target = (game or "").lower()
        if a == "open" and target in ("library", "библиотека", "downloads", "загрузки", "friends", "друзья", "store", "магазин", ""):
            url = {"library": "steam://open/games", "библиотека": "steam://open/games", "downloads": "steam://open/downloads",
                   "загрузки": "steam://open/downloads", "friends": "steam://open/friends", "друзья": "steam://open/friends",
                   "store": "steam://store", "магазин": "steam://store", "": "steam://open/main"}[target]
            os.startfile(url)
            return f"Открыл Steam: {target or 'главная'}."
        appid, name = await _resolve(game)
        if not appid:
            return f"Не нашёл «{game}» в Steam."
        if a == "open":
            os.startfile(f"steam://store/{appid}")
            return f"Открыл страницу {name} в Steam."
        if not any(str(g["appid"]) == appid for g in installed()):
            return f"{name} не установлена — могу открыть её страницу (open)."
        os.startfile(f"steam://rungameid/{appid}")
        return f"Запускаю {name} через Steam."
    if a in ("watch", "track", "follow"):
        appid, name = await _resolve(game)
        if not appid:
            return f"Не нашёл «{game}» в Steam."
        from ..prefs import get, update
        w = get("steam.watch", {}) or {}
        d = await details(appid)
        w[appid] = {"name": name, "since": time.strftime("%Y-%m-%d"), "price": _price(d.get("price_overview"))}
        update({"steam": {"watch": w}})
        return f"Слежу за {name}. Сейчас: {w[appid]['price']}. Спроси «что со скидками в стиме» — покажу."
    if a in ("wishlist", "wish", "желаемое", "deals", "скидки", "sale", "sales"):
        try:
            wl = await wishlist()
        except Exception as e:
            wl, err = [], str(e)
        else:
            err = ""
        from ..prefs import get
        w = get("steam.watch", {}) or {}
        extra = [x for x in (await items(list(w))) if x["appid"] not in {y["appid"] for y in wl}] if w else []
        allg = wl + extra
        if not allg:
            return f"Не получил список желаемого: {err}." if err else "Список желаемого пуст."
        sale = sorted([x for x in allg if x["discount"]], key=lambda x: (-x["discount"], x["cents"]))
        line = lambda x: f"- {x['name']}: {x['price']}" + (f" (−{x['discount']}%, было {x['was']})" if x["discount"] else "")
        head = f"Желаемое в Steam: {len(wl)} игр, цены в {'гривнах' if _cc() == 'UA' else _cc()}."
        if a.startswith(("wish", "жел")) and not sale:
            return head + " Скидок сейчас нет.\n" + "\n".join(line(x) for x in sorted(allg, key=lambda x: x["cents"])[:max(n, 15)])
        if not sale:
            return head + " Сейчас ни на одну из них нет скидки."
        return (head + f" Со скидкой сейчас {len(sale)}:\n" + "\n".join(line(x) for x in sale[:max(n, 15)])
                + (f"\n…и ещё {len(sale) - max(n, 15)}." if len(sale) > max(n, 15) else ""))
    return f"Не знаю действие «{action}». Есть: library, recent, downloads, search, info, open, launch, watch, wishlist, deals."
