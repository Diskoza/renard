"""Gallery of ready automations («Галерея» in «Команды»): one click → a normal editable command.
Every template is a chain of the same blocks the editor has, so after adding it can be changed freely."""
import json

T = lambda tool, **a: ("renard_tool", {"tool": tool, "args": json.dumps(a, ensure_ascii=False)})

TEMPLATES = [
    {"id": "translate_sel", "icon": "🌍", "title": "Перевести выделенное",
     "desc": "Ctrl+Alt+T: выделенный текст переводится (RU↔EN) и заменяется переводом.",
     "chain": [("trigger_hotkey", {"combo": "ctrl+alt+t"}), ("selected_text", {}),
               ("ai_text", {"task": "Переведи: если текст на русском — на английский, иначе — на русский", "text": "{last}"}),
               ("paste_text", {"text": "{last}"})]},
    {"id": "fix_sel", "icon": "✍", "title": "Исправить выделенный текст",
     "desc": "Ctrl+Alt+R: ИИ исправляет ошибки в выделенном тексте и вставляет исправленный.",
     "chain": [("trigger_hotkey", {"combo": "ctrl+alt+r"}), ("selected_text", {}),
               ("ai_text", {"task": "Исправь орфографию, пунктуацию и стиль. Язык не меняй", "text": "{last}"}),
               ("paste_text", {"text": "{last}"})]},
    {"id": "explain_clip", "icon": "💡", "title": "Объяснить буфер",
     "desc": "Фраза «объясни буфер»: коротко объясняет скопированный текст или код и произносит.",
     "chain": [("trigger_phrase", {"phrases": "объясни буфер, что в буфере"}), ("clipboard_get", {}),
               ("ai_text", {"task": "Объясни простыми словами в 2–3 предложениях, на русском", "text": "{last}"}),
               ("notify", {"text": "{last}"}), ("say", {"text": "{last}"})]},
    {"id": "shutdown_timer", "icon": "⏻", "title": "Выключить ПК через час",
     "desc": "«Выключи комп через час» — таймер выключения; «отмени выключение» есть отдельной командой.",
     "chain": [("trigger_phrase", {"phrases": "выключи комп через час, выключи компьютер через час"}),
               ("power", {"action": "shutdown", "minutes": "60"}), ("say", {"text": "Хорошо, выключу компьютер через час"})]},
    {"id": "shutdown_cancel", "icon": "↩", "title": "Отменить выключение",
     "desc": "«Отмени выключение» — снимает таймер выключения или перезагрузки.",
     "chain": [("trigger_phrase", {"phrases": "отмени выключение, не выключай компьютер"}),
               ("power", {"action": "cancel", "minutes": "0"}), ("say", {"text": "Выключение отменено"})]},
    {"id": "meeting", "icon": "📅", "title": "Подключиться к встрече",
     "desc": "«Подключи к встрече»: открывает ссылку ближайшего события календаря (Meet, Zoom, Teams).",
     "chain": [("trigger_phrase", {"phrases": "подключи к встрече, открой встречу"}), ("next_meeting", {"minutes": "30"})]},
    {"id": "work_mode", "icon": "💼", "title": "Рабочий режим",
     "desc": "«Рабочий режим»: VS Code, почта, «не беспокоить» и план на сегодня вслух. Поменяй программы под себя.",
     "chain": [("trigger_phrase", {"phrases": "рабочий режим, начинаем работать"}), ("open_app", {"name": "code"}),
               ("open_url", {"url": "https://mail.google.com"}), ("focus", {"mode": "on"}),
               T("day_plan", day="сегодня"), ("say", {"text": "{last}"})]},
    {"id": "work_off", "icon": "🌙", "title": "Конец работы",
     "desc": "«Заканчиваем работу»: выключает «не беспокоить» и рассказывает план на завтра.",
     "chain": [("trigger_phrase", {"phrases": "заканчиваем работу, конец работы"}), ("focus", {"mode": "off"}),
               T("day_plan", day="завтра"), ("say", {"text": "{last}"})]},
    {"id": "hung", "icon": "🧊", "title": "Закрыть зависшие окна",
     "desc": "Ctrl+Alt+K: закрывает программы, окна которых не отвечают.",
     "chain": [("trigger_hotkey", {"combo": "ctrl+alt+k"}), ("close_hung", {}), ("notify", {"text": "Проверил зависшие окна"})]},
    {"id": "pomodoro", "icon": "🍅", "title": "Помодоро ×4",
     "desc": "«Помодоро»: 4 круга по 25 минут работы и 5 минут отдыха, на время работы — «не беспокоить».",
     "chain": [("trigger_phrase", {"phrases": "помодоро, запусти помодоро"}), ("focus", {"mode": "on"}),
               ("notify", {"text": "🍅 25 минут фокуса"}), ("wait", {"seconds": "1500"}), ("focus", {"mode": "off"}),
               ("say", {"text": "Перерыв пять минут"}), ("wait", {"seconds": "300"}), ("repeat", {"times": "4"}),
               ("say", {"text": "Четыре помидора готово, отличная работа!"})]},
    {"id": "water", "icon": "💧", "title": "Напоминание пить воду",
     "desc": "Каждый час с 9 до 22: уведомление выпить воды.",
     "chain": [("trigger_schedule", {"when": "every 60m"}), ("if_time", {"from": "09:00", "to": "22:00"}),
               ("notify", {"text": "💧 Выпей воды"})]},
    {"id": "morning", "icon": "☀", "title": "Утренний план",
     "desc": "По будням в 8:00: погода, дела и встречи на сегодня — вслух.",
     "chain": [("trigger_schedule", {"when": "weekdays 08:00"}), T("day_plan", day="сегодня"), ("say", {"text": "{last}"})]},
    {"id": "evening", "icon": "🌆", "title": "Вечерний итог",
     "desc": "Каждый день в 21:30: что сделано за день и что на завтра — в уведомление и Telegram.",
     "chain": [("trigger_schedule", {"when": "daily 21:30"}),
               ("ask_ai", {"prompt": "Коротко подведи итог моего дня (activity_report) и скажи, что у меня на завтра (day_plan завтра)."}),
               ("notify", {"text": "{last}"}), ("telegram", {"text": "{last}"})]},
    {"id": "lofi", "icon": "🎧", "title": "Включи лофи",
     "desc": "«Включи лофи» — lofi hip hop на YouTube. Поменяй запрос на свою музыку.",
     "chain": [("trigger_phrase", {"phrases": "включи лофи, музыка для работы"}), T("music", action="play", query="lofi hip hop radio")]},
    {"id": "dnd_key", "icon": "🔕", "title": "Не беспокоить по клавише",
     "desc": "Ctrl+Alt+D — включить «не беспокоить» (уведомления Windows и замечания Renard).",
     "chain": [("trigger_hotkey", {"combo": "ctrl+alt+d"}), ("focus", {"mode": "on"}), ("notify", {"text": "🔕 Не беспокоить"})]},
    {"id": "screens", "icon": "📸", "title": "Скриншот в папку",
     "desc": "Ctrl+Alt+S: снимок всех экранов в Изображения\\Renard и открыть папку.",
     "chain": [("trigger_hotkey", {"combo": "ctrl+alt+s"}), ("screenshot", {}),
               ("open_path", {"path": "%USERPROFILE%\\Pictures\\Renard"})]},
    {"id": "form", "icon": "🧾", "title": "Заполнить форму",
     "desc": "Ctrl+Alt+F: вводит поля по очереди через Tab. Впиши свои данные в блок «Ввести текст».",
     "enabled": False,
     "chain": [("trigger_hotkey", {"combo": "ctrl+alt+f"}), ("type_text", {"text": "Имя{tab}Фамилия{tab}почта@example.com"})]},
    {"id": "webhook", "icon": "🔗", "title": "Выделенное → вебхук (n8n, Make, Zapier)",
     "desc": "Ctrl+Alt+W: отправляет выделенный текст POST-запросом. Впиши адрес своего вебхука.",
     "enabled": False,
     "chain": [("trigger_hotkey", {"combo": "ctrl+alt+w"}), ("selected_text", {}),
               ("http", {"method": "POST", "url": "https://", "body": '{"text": "{last}"}'}), ("notify", {"text": "Отправлено"})]},
]


def gallery() -> list[dict]:
    from .commands import NODES, all_commands
    have = {c.get("template") for c in all_commands()}
    return [{"id": t["id"], "icon": t["icon"], "title": t["title"], "desc": t["desc"], "added": t["id"] in have,
             "blocks": [NODES[n]["title"] for n, _ in t["chain"]]} for t in TEMPLATES]


def install(tid: str) -> dict:
    from .commands import _chain, upsert
    t = next((x for x in TEMPLATES if x["id"] == tid), None)
    if not t:
        raise ValueError("нет такого шаблона")
    return upsert({"name": t["title"], "group": "Из галереи", "enabled": t.get("enabled", True), "template": tid,
                   "graph": _chain(*t["chain"])})
