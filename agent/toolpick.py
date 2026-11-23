"""Tool Search: give the model only the tools this request needs (like Astra's «Tool Search»).

65 tool schemas are ~22k characters (~7k tokens) on every request: slow on a small model and confusing for it.
Each request gets: a small core set + tools whose trigger words occur in the request / the recent dialogue +
tools used in the last turns, capped at MAX. The model can ask for more with `tool_search(query)`, and the core
falls back to the full list when the model claims an action it has no tool for.
"""
import re

from . import tools
from .logs import quiet

MAX = 14
CORE = ["web_search", "remember", "look_at_screen", "open_app", "read_file", "tool_search"]

TRIGGERS: dict[str, str] = {
    "music": "музык песн трек ютуб youtube spotify спотиф включи плейлист видео послуша лофай lofi слуша клип некст следующ",
    "volume": "громк звук тише громче mute замьют делени",
    "app_volume": "громк звук тише громче микшер дискорд хром",
    "media_control": "пауз продолж трек следующ предыдущ стоп плеер",
    "open_app": "открой запусти запуск включи игр программ стим steam дискорд discord майн minecraft танк",
    "close_app": "закрой выключи заверши убери программ",
    "windows": "окн сверн разверн раздели экран монитор слева справа поверх переключ фокус",
    "app_ui": "кнопк нажми интерфейс меню вкладк поле пункт",
    "app_ui_confirm": "кнопк нажми удали отправ оплат",
    "look_at_screen": "экран вижу видишь посмотри глянь скрин что на экране ошибка",
    "look_at_window": "окн посмотри глянь хром вскод vscode",
    "look_at_image": "картинк фото изображен скрин png jpg",
    "analyze_media": "видео аудио голосов запис mp3 mp4 разбер расшифр",
    "read_file": "прочитай файл документ pdf docx txt открой файл что в файле",
    "write_file": "создай файл запиши файл сохрани в файл",
    "edit_file": "замени исправ код строк файл",
    "doc_replace": "замени слово презентац документ docx pptx xlsx",
    "search_files": "найди файл где лежит папк поиск",
    "recent_files": "недавн последн презентац документ таблиц фото видео делал",
    "list_dir": "папк содержим что лежит",
    "file_info": "размер файл когда изменен",
    "largest_files": "больш файл место занима лишн ненужн",
    "open_file": "открой файл папк документ",
    "school": "замен уроки урок школ план уроков расписание zastępstw zastepstw lekcj plan lekcji szkoł класс оценк средн "
              "справдз sprawdzian kartk контрольн домашк задали zadani ocen dziennik дневник пропуск frekwencj",
    "app_guide": "программ приложени как в горяч клавиш кнопк меню умеет научись пользоваться",
    "apps_overview": "какие программы приложения игры установлены есть у меня",
    "app_learn": "изучи изучить научись запомни кнопки",
    "app_do": "сделай нажми найди открой зайди программ приложени окно hydra гидр gimp paint blender inkscape обс obs",
    "telegram": "телеграм телеге тг telegram чат пишет написал переписк сообщени непрочитан",
    "telegram_send": "телеграм телеге тг telegram напиши отправь ответь скинь вышли фото фотку",
    "discord": "дискорд discord канал сервер",
    "discord_send": "дискорд discord напиши отправь скинь",
    "steam": "стим steam игр наиграл играл библиотек скидк цена стоит качается обновлен",
    "site_api": "ютуб youtube канал видео вакансi ваканс hh хабр habr github гитхаб реддит reddit википеди wikipedia imdb "
                "фильм сериал рейтинг рецепт авиабилет билет рейс перелет spotify pypi arxiv сайт сайта сайте",
    "site_learn": "научись выучи сайт сайта сайте",
    "inspect_program": "exe dll программ безопасн вирус подпис подписан проверь проверить троян шпион",
    "ask_cloud": "облак claude клод опус opus gpt чатгпт gemini джемин сильн умн сложн трудн спроси",
    "ask_cloud_confirm": "да давай спроси отправ облак",
    "connector_add": "коннектор connector mcp npx подключи подключить сервер",
    "image_edit": "фото фотк картинк изображен обрежь обрезать размер ярк контраст размой размыть замаж надпись текст рамк "
                  "повернуть поверни ч/б чб редактир улучши фильтр сепия водян круг",
    "image_make": "коллаж мем открытк картинк создай нарисуй",
    "photo_fix": "фото фотк снимк обработ улучши красив цветокор свет тен шум зерн тепл ярч затемн осветл ретуш "
                 "инстаграм instagram zdjęc",
    "photo_best": "лучш выбер отбер серии фото фотк снимк удачн смазан",
    "photo_crop": "обрежь обрез 4:5 9:16 сторис stories рилс reels инст instagram insta формат пропорц квадрат",
    "photo_info": "фото фотк смазан резк размыт пересвет темн",
    "photo_mask": "перерису рук пальц лишн человек предмет дорису кист маск",
    "photo_ai": "перерису рук пальц лишн человек предмет дорису нейросет маск инпейнт",
    "open_folder": "папк загрузк документы рабочий стол картинк pobrane folder katalog",
    "reopen_tab": "вкладк закрыл закрыт tab kart хром chrome браузер",
    "browser": "браузер вкладк обнов страниц перезагруз f5 ctrl ссылк назад вперёд пролист масштаб хром chrome firefox edge "
               "przegląd odśwież kart link",
    "show_renard": "renard ренар приложен окно чат экран покажи выведи",
    "tasks": "дела дело задач список туду todo сделать купить вычеркни отметь сделал срок",
    "notes": "заметк запиши записать сохрани идея код пароль список",
    "calendar": "календар встреч созвон событи день рождения запланир собрани урок",
    "currency": "курс валют доллар евро злот гривн фунт обменять перевести сколько стоит",
    "day_plan": "планы утро сводка сегодня завтра расписание день",
    "look_at_camera": "камер веб-камер в руке как выгляжу покажу фото сфоткай посмотри на меня",
    "show_in_explorer": "проводник покажи где",
    "delete_to_recycle_bin": "удали корзин",
    "presentation": "презентац слайд показ",
    "web_search": "найди интернет загугли гугл поищи узнай новост цен курс кто такой что такое",
    "fetch_page": "ссылк сайт страниц http www прочитай",
    "weather": "погод прогноз зонт дожд температур градус pogod wetter weather",
    "world_time": "времени врем час часов часовой пояс godzin czas uhrzeit zeit time",
    "calc": "посчитай вычисли сколько будет процент умнож подели корень",
    "wiki": "кто такой что такое когда был википеди факт дата",
    "news": "новост ютубер стрим твич подписк хайп заквиел видео вышло",
    "pc_stats": "загрузк нагрузк процессор видеокарт память озу vram диска дисков ssd hdd температур состояние пк",
    "diagnose_pc": "тормоз лага медлен грузит нагрузк диагност",
    "top_processes": "процесс грузит жрёт жрет",
    "load_history": "нагрузк истори час",
    "kill_process": "убей заверши процесс",
    "junk_report": "мусор место почисти лишн ненужн захламл",
    "clean_temp": "почисти временн temp мусор",
    "defender_scan": "вирус сканир защит defender",
    "defender_status": "вирус защит defender",
    "find_installed_apps": "установлен программ игр какие есть",
    "power": "выключи перезагру сон усни гибернац выйди",
    "power_cancel": "отмени выключен",
    "lock_pc": "заблокир блокир экран",
    "schedule_task": "напомни напоминан каждый ежеднев будильник через минут расписан запланир",
    "list_tasks": "задач напоминан расписан",
    "cancel_task": "отмени удали напоминан задач",
    "remember": "запомни помни правило запиши себе",
    "memory_read": "помнишь знаешь обо мне",
    "search_history": "обсуждали говорили раньше вчера истори чат чатгпт chatgpt gpt клод claude спрашивал советовал "
                      "советовали делали настраивал прошлый прошлом",
    "clipboard": "буфер скопир вставь",
    "notify": "уведомлен",
    "play_radio": "радио",
    "stop_radio": "радио выключи",
    "avatar": "аватар помаши танцуй станцуй прыгни сядь улыбн кивни потанцуй",
    "routine": "как обычно привычк",
    "activity_report": "сколько времени провёл провел активност играл сидел",
    "run_python": "посчитай вычисли python питон скрипт код",
    "run_command": "npm pip git python node запусти команд тест сборк",
    "run_user_command": "команд",
    "code_agent": "claude code клод кодекс codex aider айдер gemini агент-программист программист допиши рефакторинг "
                  "поручи напиши код проект",
    "code_agent_status": "клод кодекс aider айдер программист как там код прогресс останови",
    "make_command": "команд автоматизац горяч клавиш хоткей сочетан макрос каждый день каждое утро запомни как сохрани как",
    "project_map": "проект структур код разберись репозитор",
    "project_tree": "проект структур дерев папк",
    "project_search": "проект знани",
    "project_remember": "проект запомни",
    "send_file": "пришли отправь телеграм файл",
    "allow_folder": "разреши папк доступ",
    "skill_search": "навык скилл найди",
    "skill_install": "навык скилл установи",
    "skills_list": "навык скилл",
    "use_skill": "навык скилл",
    "mcp_tools": "коннектор сервис mcp",
    "mcp_call": "коннектор сервис mcp",
    "probe_app": "настрой настроить программ приложени где хранит настройк конфиг config не работает разберись почему",
    "pc_script": "скрипт конфиг config настройк файл реестр json ini прочитай посмотри проверь где лежит сколько места",
    "apply_sandbox": "примени песочниц изменени верни отмени правк",
    "save_skill": "запомни как научись сохрани способ в следующий раз",
    "run_skill": "навык скилл как в прошлый раз",
    "long_task": "разберись выясни почему сам долго поработай исследуй докопайся продолжи",
    "install_app": "установи поставь обнови обновить новая версия последняя версия переустанови install update "
                   "upgrade zainstaluj zaktualizuj winget java джава python питон",
    "drivers": "драйвер драйвера драйверы driver sterownik обнови железо видеокарт чипсет bios",
    "download_file": "скачай скачать загрузи загрузить download pobierz ściągnij установщик инсталлятор файл по ссылке",
    "task_notes": "выяснил журнал что пробовал продолжи",
    "convert_document": "pdf пдф docx ворд word odt конверт перевед сохрани формат excel xlsx pptx",
    "make_document": "документ pdf пдф docx ворд word карточк памятк плакат бланк оформ подкоррект подкорект подровн "
                     "выровн шрифт таблиц распечат лист справк заявлени резюме реферат dokument",
    "mail": "почт письм письмо mail email gmail inbox входящ poczt wiadomości e-mail ящик",
}
STOP = {"что", "как", "где", "когда", "есть", "какие", "лежит", "себе", "раньше", "файле"}
SHORT_OK = {"пк", "чб", "mp3", "mp4", "pdf", "txt", "png", "jpg", "git", "npm", "pip", "mcp"}
_STEMS = {k: [w for w in v.split() if (len(w) >= 3 or w in SHORT_OK) and w not in STOP] for k, v in TRIGGERS.items()}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zа-яёąćęłńóśźż0-9]+", (text or "").lower().replace("ё", "е"))


def score(name: str, words: list[str], joined: str) -> int:
    s = 0
    for st in _STEMS.get(name, []):
        if " " in st:
            s += 2 * (st in joined)
        else:
            s += any(w.startswith(st) for w in words)
    return s


def pick(mode: str, text: str, recent: str = "", used: list[str] | None = None, extra: list[str] | None = None) -> list[dict]:
    """Schemas for this request. text — the request; recent — the last messages (for «а теперь закрой его»)."""
    allowed = {s["function"]["name"]: s for s in tools.schemas(mode)}
    w_now, w_old = _words(text), _words(recent)
    j_now, j_old = " ".join(w_now), " ".join(w_old)
    ranked = sorted(((score(n, w_now, j_now) * 3 + score(n, w_old, j_old), n) for n in allowed), reverse=True)
    names = [n for n in CORE if n in allowed]
    try:
        from .corrections import suggest
        learned = suggest(text)
    except Exception:
        learned = []
    for n in (used or []) + (extra or []) + learned:
        if n in allowed and n not in names:
            names.append(n)
    try:
        from .app_manuals import mentioned_app
        if mentioned_app(text):
            for n in ("app_do", "app_guide", "open_app", "look_at_window", "probe_app"):
                if n in allowed and n not in names:
                    names.append(n)
    except Exception:
        quiet()
    for sc, n in ranked:
        if sc <= 0 or len(names) >= MAX:
            break
        if n not in names:
            names.append(n)
    if "app_do" in names:
        names = [n for n in names if n not in ("app_ui", "app_ui_confirm")]
    try:
        from . import cloud
        if cloud.status()["ready"]:
            names.append("ask_cloud")
            if cloud.PENDING:
                names.append("ask_cloud_confirm")
        else:
            names = [n for n in names if n not in ("ask_cloud", "ask_cloud_confirm")]
    except Exception:
        pass
    if "use_skill" in allowed and any(w in j_now for w in ("навык", "скилл", "skill")):
        names.append("use_skill")
    return [allowed[n] for n in dict.fromkeys(names) if n in allowed]


def search(query: str, mode: str = "low", k: int = 8) -> list[str]:
    """For the tool_search tool: names of the tools that fit the query (trigger words + description words)."""
    allowed = {s["function"]["name"]: s for s in tools.schemas(mode)}
    w = _words(query)
    j = " ".join(w)
    out = []
    for n, s in allowed.items():
        d = _words(s["function"]["description"])
        sc = score(n, w, j) * 2 + sum(1 for x in w if len(x) > 3 and any(y.startswith(x[:5]) for y in d))
        if sc > 0:
            out.append((sc, n))
    return [n for _, n in sorted(out, reverse=True)[:k]]
