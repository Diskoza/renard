"""How to use the user's programs: a manual per app, so the model knows WHAT an app is for and HOW to drive it.

Three layers, merged by app_guide(app):
  1. CATALOG — hand-written manuals for the apps on his PC (purpose, hotkeys, common tasks as Renard tool steps);
     every other installed app gets a category manual (game, IDE, terminal, office, launcher, system tool…).
  2. UI map — learned automatically: every app_ui read stores the app's buttons / menus / tabs / fields
     (data/app_manuals/<app>.json), so next time the model knows the names to click without exploring again.
  3. Recipes — a task that worked in that app (the user's words + the app_ui / windows steps) is stored and shown
     next time («как в прошлый раз»).
Nothing here opens or closes apps by itself except app_learn, which the user asks for.
"""
import json
import re
import time
from pathlib import Path

from .config import DATA_DIR
from .logs import quiet

DIR = DATA_DIR / "app_manuals"

GENERIC_UI = ("Внутри окна: app_ui read (какие кнопки/поля есть) → app_ui click name=… / type name=… text=… / keys text=…; "
              "если read пустой (игры, Electron без доступности) — look_at_window и горячие клавиши.")
C = {
    r"chrome|хром|google chrome": ("браузер", "интернет, YouTube, сайты, вкладки",
        "Ctrl+T новая вкладка, Ctrl+W закрыть, Ctrl+Shift+T вернуть закрытую, Ctrl+L адресная строка, Ctrl+Tab следующая, "
        "Ctrl+1..9 вкладка по номеру, Ctrl+F поиск на странице, Ctrl+H история, Ctrl+J загрузки, F5 обновить, Alt+←/→ назад/вперёд",
        ["открыть сайт: open_file path=<url> (или app_ui keys ctrl+l, type url, enter)",
         "вернуть закрытую вкладку: reopen_tab (site — если нужен конкретный сайт)",
         "YouTube: music (play/next/pause), что на экране — look_at_window chrome",
         "прочитать страницу — fetch_page url (не листать глазами)"]),
    r"explorer|проводник|file explorer": ("файлы", "папки и файлы Windows",
        "Win+E открыть, Ctrl+L путь, Ctrl+N новое окно, Ctrl+Shift+N новая папка, F2 переименовать, Alt+↑ вверх, Ctrl+F поиск",
        ["открыть папку: open_folder (загрузки, документы…) или open_file path=<папка>",
         "найти файл: search_files; показать файл в проводнике: show_in_explorer",
         "удалить: только delete_to_recycle_bin (в корзину) после «да»"]),
    r"telegram|телеграм": ("мессенджер", "переписка Telegram (его бот Renard — @dz_renardbot)",
        "Ctrl+K поиск чата, Ctrl+↑/↓ прошлый/следующий чат, Esc закрыть чат, Ctrl+F поиск в чате, Ctrl+Shift+M без звука",
        ["прислать ему файл — send_file (через бота)",
         "написать кому-то: windows focus telegram → app_ui keys ctrl+k → type имя → enter → type текст; "
         "ОТПРАВКУ (enter) — только после «да» (app_ui_confirm)"]),
    r"discord|дискорд": ("мессенджер/голос", "голосовые каналы и чаты Discord",
        "Ctrl+K быстрый переход к серверу/каналу, Ctrl+Shift+M микрофон вкл/выкл, Ctrl+Shift+D звук вкл/выкл, "
        "Alt+↑/↓ канал, Ctrl+/ все горячие клавиши",
        ["громкость Discord: app_volume app=discord", "выключить микрофон: app_ui keys ctrl+shift+m",
         "сообщения — только после «да» пользователя"]),
    r"whatsapp": ("мессенджер", "WhatsApp Desktop", "Ctrl+F поиск чата, Ctrl+N новый чат, Ctrl+Shift+M без звука, Esc закрыть",
        ["отправка сообщений — только после «да»"]),
    r"steam|стим": ("игровой лаунчер", "игры Steam, библиотека, друзья",
        "Shift+Tab оверлей в игре, F12 скриншот в игре",
        ["запустить игру: open_app <название игры> (ярлыки игр есть в Пуске)",
         "библиотека: open_file path=steam://open/games; загрузки: steam://open/downloads; друзья: steam://open/friends"]),
    r"visual studio code|vscode|code\b|cursor|antigravity|kiro|devin": ("редактор кода", "код, проекты (VS Code и его клоны)",
        "Ctrl+P открыть файл, Ctrl+Shift+P палитра команд, Ctrl+` терминал, Ctrl+S сохранить, Ctrl+Shift+F поиск по проекту, "
        "F5 запуск/отладка, Ctrl+/ комментарий, Alt+Shift+F форматировать, Ctrl+B боковая панель",
        ["открыть папку проекта: run_command `code <папка>` (cursor/antigravity — так же своей командой) или open_app",
         "править файлы лучше самому через write_file/edit_file — надёжнее, чем печатать в редактор"]),
    r"pycharm|android studio|intellij": ("IDE JetBrains", "Python / Android проекты",
        "Shift Shift поиск везде, Ctrl+Shift+F10 запуск файла, Shift+F10 запуск, Ctrl+Alt+L формат, Alt+Enter исправление, "
        "Alt+F12 терминал, Ctrl+S сохранить", ["код править через write_file/edit_file, запуск — run_python / run_command"]),
    r"visual studio 2022|devenv": ("IDE", "C#/C++ проекты", "F5 запуск, Ctrl+Shift+B сборка, Ctrl+, поиск, Ctrl+K Ctrl+D формат", []),
    r"github desktop": ("git", "коммиты и push через окно", "Ctrl+Enter коммит, Ctrl+P push, Ctrl+Shift+P pull",
        ["git удобнее командой: run_command git status / git log (в папке проекта)"]),
    r"terminal|терминал|powershell|command prompt|cmd|git bash|wsl": ("терминал", "командная строка",
        "Ctrl+Shift+T новая вкладка (Терминал), Ctrl+C прервать, Ctrl+Shift+V вставить",
        ["команды выполняй сам через run_command (без окна) — так видно результат"]),
    r"блокнот|notepad": ("текст", "простые заметки", "Ctrl+N новый, Ctrl+S сохранить, Ctrl+F поиск, Ctrl+H замена",
        ["создать текстовый файл лучше write_file (сразу в нужную папку), потом open_file"]),
    r"калькулятор|^calculator$|^calc$|calculatorapp": ("утилита", "калькулятор", "Alt+1 обычный, Alt+2 инженерный, Alt+3 графики, Alt+4 программист",
        ["посчитать — calc (точно, без окна); окно — только если просят открыть"]),
    r"paint\b|mspaint": ("графика", "простое рисование", "Ctrl+N новый, Ctrl+V вставить, Ctrl+W размер, Ctrl+S сохранить",
        ["картинку изменить (размер, обрезка, ч/б, текст) — image_edit, без окна"]),
    r"gimp": ("графика", "редактор изображений", "Ctrl+O открыть, Ctrl+Shift+E экспорт, T текст, Shift+T масштаб, Ctrl+Z отмена",
        ["простые правки — image_edit; GIMP — для сложных, по шагам app_ui/keys"]),
    r"libreoffice writer|swriter|word": ("офис", "документы (.docx/.odt)", "Ctrl+S сохранить, Ctrl+Shift+S сохранить как, Ctrl+P печать, Ctrl+B/I/U",
        ["прочитать — read_file; заменить слово — doc_replace; новый документ проще создать файлом"]),
    r"libreoffice calc|scalc|excel": ("офис", "таблицы", "Ctrl+S сохранить, F2 правка ячейки, Ctrl+Shift+L фильтр",
        ["прочитать таблицу — read_file; посчитать — run_python"]),
    r"libreoffice impress|simpress|powerpoint": ("офис", "презентации", "F5 показ с начала, Shift+F5 с текущего слайда, Esc выход",
        ["показ — presentation (start/next/prev/end); найти — recent_files"]),
    r"libreoffice$|soffice": ("офис", "LibreOffice (Writer, Calc, Impress)", "", ["см. Writer / Calc / Impress"]),
    r"sharex": ("скриншоты", "скриншоты, запись экрана, загрузка",
        "Print Screen весь экран, Ctrl+Print Screen область, Shift+Print Screen запись экрана (по умолчанию)",
        ["что на экране для себя — look_at_screen (ShareX не нужен)"]),
    r"ножницы|snipping": ("скриншоты", "скриншот области", "Win+Shift+S область, Win+Shift+R запись экрана", []),
    r"audacity": ("звук", "запись и монтаж звука", "R запись, Space старт/стоп, Ctrl+Shift+E экспорт", ["разобрать запись — analyze_media"]),
    r"qbittorrent": ("загрузки", "торренты", "Ctrl+O добавить файл, Ctrl+D ссылка", ["скачивание — только после «да»"]),
    r"winrar|archiwizator|7-zip": ("архивы", "архивы zip/rar", "", ["распаковать: run_command (tar -xf для zip) или окно WinRAR"]),
    r"deepl": ("перевод", "переводчик DeepL", "Ctrl+C C (дважды) — перевести выделенное", ["перевести текст можешь сам, без окна"]),
    r"chatgpt|claude|copilot": ("ИИ", "другие ИИ-ассистенты", "", ["это не ты; отвечай сам, их окно открывай только по просьбе"]),
    r"ollama": ("ИИ", "сервер локальных моделей — это твой «мозг»", "", ["не закрывай; модели — вкладка «ИИ» Renard"]),
    r"renard": ("Renard", "это ты сам", "", []),
    r"task manager|диспетчер задач|taskmgr": ("система", "процессы и нагрузка", "Ctrl+Shift+Esc открыть",
        ["что грузит ПК — top_processes / pc_stats / diagnose_pc (без окна); завершить — kill_process после «да»"]),
    r"^настройки$|^параметры$|^settings$|ms-settings|systemsettings": ("система", "Параметры Windows", "Win+I открыть",
        ["страницу открыть: open_file path=ms-settings:display (sound, bluetooth, network-wifi, apps-volume, windowsupdate, "
         "personalization-background, defaultapps). Менять системные настройки и безопасность — не сам: объясни шаги"]),
    r"control panel|панель управления": ("система", "старая панель управления", "", ["настройки безопасности не меняй сам — дай инструкцию"]),
    r"(cisco )?packet ?tracer|пакет ?трейсер": ("учёба (сети)", "симулятор сетей Cisco (INF.02)", "Ctrl+S сохранить, Ctrl+R режим реального времени",
        ["команды IOS объясняй текстом; в окно CLI можно печатать app_ui type"]),
    r"vmware": ("виртуалки", "виртуальные машины", "Ctrl+Alt выйти из машины, Ctrl+Alt+Enter полный экран", []),
    r"tailscale|radmin vpn|parsec|ultravnc|radmin viewer|remote desktop|mstsc": ("удалённый доступ", "VPN / удалённый рабочий стол", "",
        ["подключения/пароли не вводи сам"]),
    r"putty|tera ?term": ("терминал", "SSH / последовательный порт", "", ["пароли не вводи; ssh-команды объясняй"]),
    r"wallpaper engine": ("оформление", "живые обои", "", ["в играх можно поставить на паузу через его трей"]),
    r"nvidia app|nvidia control": ("видеокарта", "драйверы, запись, оверлей NVIDIA", "Alt+Z оверлей, Alt+F9 запись, Alt+F10 повтор", []),
    r"armoury crate|aura creator|razer|synapse|cortex": ("железо", "подсветка, вентиляторы, профили", "", []),
    r"powertoys": ("утилиты", "PowerToys", "Alt+Space PowerToys Run, Win+Shift+C пипетка, Win+Shift+T текст с экрана, Win+Ctrl+V вставка",
        ["окна раскладывай сам — windows left/right/split"]),
    r"minecraft|curseforge|x minecraft launcher|craftos": ("игра (Minecraft)", "Minecraft и моды",
        "F3 отладка, F2 скриншот, F11 полный экран, T чат, / команда", ["лаунчер: open_app; моды/сборки — CurseForge"]),
    r"ubisoft|epic|overwolf|thunderstore|xbox|roblox player|meta horizon": ("игровой лаунчер", "игры и моды", "", ["игру запускай open_app"]),
    r"unity|roblox studio|unity hub": ("разработка игр", "движок / редактор", "Ctrl+S сохранить, Ctrl+P Play", []),
    r"subiekt|rachmistrz|rewizor|gratyfikant|kasiarz|gestor|insert": ("бухгалтерия InsERT GT", "склад/продажи/учёт (работа)", "",
        ["ничего не проводи и не удаляй сам; читать окно — app_ui read"]),
    r"медиаплеер|media player|vlc": ("медиа", "видео и музыка", "Space пауза, Ctrl+→ вперёд, F11 полный экран", ["пауза/следующий — music"]),
    r"фотографии|photos": ("медиа", "просмотр фото", "←/→ листать, Ctrl+E изменить", ["что на фото — look_at_image"]),
    r"камера|camera": ("медиа", "веб-камера", "", []),
    r"часы|clock": ("утилита", "будильники, таймер", "", ["таймер/напоминание — schedule_task (без окна)"]),
    r"погода|weather": ("утилита", "погода", "", ["погода — weather (без окна)"]),
    r"onedrive": ("облако", "OneDrive", "", []),
    r"microsoft store": ("магазин", "приложения Microsoft", "", ["установка — только после «да»"]),
    r"связь с телефоном|phone link": ("телефон", "Связь с телефоном (его OnePlus)", "", []),
    r"bongo cat|yolomouse": ("развлечение", "мелкая утилита", "", []),
}
GAME_HINTS = re.compile(r"steamapps|\\games\\|epic games|ubisoft|riot|gog|\\the witcher|minecraft|roblox player|world of tanks|"
                        r"war thunder|xbox games|steam://rungameid|programs\\steam\\[^\\]+\.url$|\[gog\.com\]|epic games\\", re.I)
SYSTEM_HINTS = re.compile(r"\\windows\\system32|\.msc$|administrative tools|mmc\.exe", re.I)
CATEGORY_MANUAL = {
    "игра": ("Игра. Запуск — open_app <название>. Пока он играет, тяжёлые модели не грузи (игровой режим). "
             "Внутри игр UI Automation обычно пуст: только look_at_window и клавиши. Закрывать игру — только если он просит "
             "(windows close), никогда сам."),
    "система": "Системная утилита Windows. Смотреть можно (app_ui read), менять системные/защитные настройки — нет: объясни шаги.",
    "программа": GENERIC_UI,
}


def _key(name: str) -> str:
    return re.sub(r"[^\w]+", "_", (name or "").lower()).strip("_")[:60] or "app"


def catalog_entry(name: str) -> tuple[str, tuple] | None:
    low = (name or "").lower()
    for rx, entry in C.items():
        if re.search(rx, low):
            return rx, entry
    return None


def installed() -> list[dict]:
    try:
        from .tools.system import apps_index
        return apps_index()
    except Exception:
        return []


def category(app: dict | None, name: str) -> str:
    hit = catalog_entry(name)
    if hit:
        return hit[1][0]
    tgt = f"{(app or {}).get('target', '')} {(app or {}).get('link', '')}"
    if GAME_HINTS.search(tgt):
        return "игра"
    if SYSTEM_HINTS.search(tgt):
        return "система"
    return "программа"


def _load(name: str) -> dict:
    p = DIR / f"{_key(name)}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"app": name, "ui": {}, "recipes": []}


def _save(name: str, d: dict):
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{_key(name)}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def learn_ui(app: str, read_text: str):
    """Called after every app_ui read: keep the names of buttons / menus / tabs / fields of this app."""
    if not app or not read_text or read_text.startswith("Не "):
        return
    d = _load(app)
    for line in read_text.splitlines():
        m = re.match(r"\s*(Button|MenuItem|TabItem|Edit|ComboBox|Hyperlink|CheckBox|ListItem|SplitButton):\s*(.{2,60}?)(\s*=|$)", line)
        if not m:
            continue
        kind, label = m.group(1), m.group(2).strip()
        if re.fullmatch(r"[\d\s.,:%-]+", label):
            continue
        d["ui"].setdefault(kind, [])
        if label not in d["ui"][kind]:
            d["ui"][kind] = (d["ui"][kind] + [label])[-80:]
    d["seen"] = time.strftime("%Y-%m-%d")
    _save(app, d)


def add_recipe(app: str, phrase: str, steps: list[dict]):
    """A task that worked in this app: the user's words + the steps, shown next time."""
    if not app or not steps:
        return
    d = _load(app)
    short = [f"{s['tool']} " + ", ".join(f"{k}={v}" for k, v in s.get("args", {}).items() if v not in ("", None, False))
             for s in steps][:8]
    d["recipes"] = [r for r in d.get("recipes", []) if r.get("phrase") != phrase][-19:] + \
        [{"phrase": phrase[:160], "steps": short, "date": time.strftime("%Y-%m-%d")}]
    _save(app, d)


def add_recipe_lines(app: str, phrase: str, lines: list[str]):
    """A run of the operator (app_do) that worked: the goal + the steps by element names (not numbers)."""
    if not app or not lines:
        return
    d = _load(app)
    d["recipes"] = [r for r in d.get("recipes", []) if r.get("phrase") != phrase][-19:] + \
        [{"phrase": phrase[:160], "steps": [l[:90] for l in lines][:14], "date": time.strftime("%Y-%m-%d")}]
    _save(app, d)


def find(name: str) -> tuple[str, dict | None]:
    """«хром», «телеграме», «ведьмак» -> (display name, index entry)."""
    q = (name or "").strip()
    if not q:
        return "", None
    exact = next((a for a in installed() if a["name"].lower() == q.lower()), None)
    if exact:
        return exact["name"], exact
    try:
        from .tools.pc import find_app
        hit = find_app(q)
        if hit:
            key, app = hit
            idx = next((a for a in installed() if a["name"].lower() == str(key).lower()), None)
            return (idx or {}).get("name") or str(key), idx or app
    except Exception:
        quiet()
    low = q.lower()
    for a in installed():
        if low in a["name"].lower() or a["name"].lower() in low:
            return a["name"], a
    return q, None


def guide(name: str) -> str:
    disp, app = find(name)
    if not disp:
        return "Назови программу."
    hit = catalog_entry(disp) or catalog_entry(name)
    cat = category(app, disp)
    lines = [f"Программа: {disp}" + (" (установлена)" if app else " (в меню Пуск не нашёл — может, это окно или сайт)"),
             f"Тип: {cat}"]
    if hit:
        _, (cat_, purpose, keys, tasks) = hit
        lines.append(f"Для чего: {purpose}")
        if keys:
            lines.append(f"Горячие клавиши: {keys}")
        if tasks:
            lines.append("Как делать:\n" + "\n".join(f"- {t}" for t in tasks))
    lines.append(CATEGORY_MANUAL.get(cat, GENERIC_UI) if cat in CATEGORY_MANUAL else GENERIC_UI)
    d = _load(disp)
    stem = Path(str((app or {}).get("process") or (app or {}).get("target") or "")).stem.lower()
    for other in {stem, _key(name)} - {"", _key(disp)}:
        o = _load(other)
        for k, v in o.get("ui", {}).items():
            d.setdefault("ui", {}).setdefault(k, [])
            d["ui"][k] += [x for x in v if x not in d["ui"][k]]
        d["recipes"] = d.get("recipes", []) + o.get("recipes", [])
        d["seen"] = d.get("seen") or o.get("seen", "")
    if d.get("ui"):
        ui = "; ".join(f"{k}: {', '.join(v[:25])}" for k, v in d["ui"].items())
        lines.append(f"Что есть в её окне (запомнено {d.get('seen', '')}): {ui[:1500]}")
    if d.get("recipes"):
        lines.append("Что уже получалось:\n" + "\n".join(f"- «{r['phrase']}»: " + " → ".join(r["steps"]) for r in d["recipes"][-6:]))
    lines.append("Открыть: open_app; уже открыта ли — windows list; переключиться — windows focus. Опасные кнопки "
                 "(отправить, удалить, купить) — только после «да» (app_ui_confirm).")
    return "\n".join(lines)


def _game_sources() -> dict[str, list[str]]:
    """Where his games come from: Steam / Epic / Hydra launcher / a «Games» folder."""
    src: dict[str, list[str]] = {}
    for a in installed():
        via_hydra = (a.get("process") or "").lower() == "hydra" or "hydra" in (a.get("target") or "").lower()
        s = a.get("source") or ("hydra" if via_hydra and a["name"].lower() != "hydra" else "")
        if s:
            src.setdefault(s, [])
            if a["name"] not in src[s]:
                src[s].append(a["name"])
    try:
        from .tools.system import _hydra_games, game_name_of
        for exe in _hydra_games():
            n = game_name_of(exe)
            src.setdefault("hydra", [])
            if n not in src["hydra"]:
                src["hydra"].append(n)
    except Exception:
        quiet()
    return src


SRC_NAMES = {"steam": "Steam", "epic": "Epic Games", "hydra": "Hydra Launcher", "folder": "папка Games (без лаунчера)"}


def overview(cat: str = "") -> str:
    low = (cat or "").lower()
    want = next((k for k, rx in (("hydra", r"hydra|гидр"), ("steam", r"steam|стим"), ("epic", r"epic|эпик"),
                                 ("folder", r"папк|folder|games")) if re.search(rx, low)), "")
    if want or re.search(r"игр|game|gry", low):
        src = _game_sources()
        keys = [want] if want else list(SRC_NAMES)
        parts = [f"- {SRC_NAMES[k]} ({len(src.get(k, []))}): {', '.join(sorted(src.get(k, []))[:60]) or 'нет'}" for k in keys]
        if want:
            return "Игры по источнику:\n" + "\n".join(parts)
        tail = "\nИгры по источнику:\n" + "\n".join(parts)
    else:
        tail = ""
    if re.search(r"игр|game|gry", low):
        cat = "игр"
    return _overview(cat) + tail


def _overview(cat: str = "") -> str:
    groups: dict[str, list[str]] = {}
    for a in installed():
        n = a["name"]
        if re.search(r"uninstall|деинстал|manual|руководств|web site|faq|support|readme|документац|module docs|check for updates", n, re.I):
            continue
        c = category(a, n)
        if cat and cat.lower() not in c.lower():
            continue
        groups.setdefault(c, [])
        if n not in groups[c]:
            groups[c].append(n)
    if not groups:
        return "Не нашёл программ такого типа."
    order = sorted(groups, key=lambda c: (c == "программа", c))
    return f"Программ в меню Пуск: {sum(len(v) for v in groups.values())}\n" + "\n".join(
        f"- {c} ({len(v)}): {', '.join(sorted(v)[:40])}" for c, v in ((c, groups[c]) for c in order))


_NAMES: tuple[int, list[tuple[str, str]]] | None = None


def mentioned_app(text: str) -> str:
    """The installed app a request talks about («в телеграме», «в gimp»), '' if none — for picking the app tools."""
    global _NAMES
    t = (text or "").lower()
    for rx in C:
        m = re.search(rx, t)
        if m and len(m.group(0)) >= 3:
            return m.group(0)
    apps = installed()
    if _NAMES is None or _NAMES[0] != len(apps):
        _NAMES = (len(apps), [(a["name"].lower(), a["name"]) for a in apps if len(a["name"]) >= 4])
    for low, n in _NAMES[1]:
        if re.search(r"(?<!\w)" + re.escape(low) + r"(?!\w)", t):
            return n
    try:
        from .tools.apps import list_wins
        for w in list_wins():
            title = re.sub(r"\s+v?\d+(?:\.\d+)*\s*$", "", (w.get("title") or "").split(" - ")[-1].strip()).lower()
            if len(title) >= 4 and re.search(r"(?<!\w)" + re.escape(title) + r"(?!\w)", t):
                return w["title"]
    except Exception:
        quiet()
    return ""
