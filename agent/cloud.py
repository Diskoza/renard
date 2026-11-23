"""Cloud escalation: a hard task the local model cannot do well goes to a strong cloud model — only as he allows it.

Settings (prefs «cloud», tab ИИ → «Облачные модели»):
  provider    "anthropic" (Claude, official SDK) or any OpenAI-compatible cloud from providers.py (openai, gemini,
              deepseek, groq, openrouter …)
  model       e.g. claude-opus-5-5
  permission  "off"  — never; the tool says it is switched off
              "ask"  — the local model asks him first («спросить у Claude?»), then calls ask_cloud_confirm
              "auto" — goes straight away
Keys live only in data/accounts/<provider>.json {"API_KEY": "…"} (written from the settings field, never shown back).
What is sent: the task the local model wrote + his last words + a short excerpt of the dialogue. Nothing else
(no memory notes, no files) unless the task text itself contains it.
"""
import time
import uuid

from . import prefs, providers

ANTHROPIC_MODELS = [
    ("claude-opus-5-5", "Opus 5.5 — сильная, по умолчанию"),
    ("claude-sonnet-5-5", "Sonnet 5.5 — быстрее и дешевле"),
    ("claude-haiku-5-5", "Haiku 5.5 — самая дешёвая"),
    ("claude-fable-5-2", "Fable 5.2 — самая сильная, дорогая"),
]
NO_FALLBACK = ("claude-haiku",)
SYSTEM = ("Ты — сильная модель. Локальный голосовой ассистент Renard на ПК пользователя (маленькая модель) передал "
          "тебе задачу, с которой сам не справится. Сделай её полностью и сразу дай готовый результат: код целиком, "
          "план по шагам, разбор. Не задавай встречных вопросов — если чего-то не хватает, сделай разумное "
          "допущение и назови его одной строкой. Отвечай на языке пользователя (обычно русский). Без вступлений.")
PENDING: dict[str, dict] = {}


def settings() -> dict:
    c = prefs.get("cloud") or {}
    return {"provider": c.get("provider", ""), "model": c.get("model", ""),
            "permission": c.get("permission", "off"), "effort": c.get("effort", "high")}


def status() -> dict:
    s = settings()
    pid = s["provider"]
    return {**s, "has_key": bool(providers.key(pid)) if pid else False,
            "ready": bool(pid and s["model"] and providers.key(pid) and s["permission"] != "off")}


def prompt_line() -> str:
    """One line for the system prompt while the lever is on: when to hand a task over (and that «ask» needs his yes)."""
    try:
        st = status()
    except Exception:
        return ""
    if not st["ready"]:
        return ""
    how = "сразу" if st["permission"] == "auto" else "но сначала спроси его разрешения (инструмент подскажет как)"
    return (f"Облако: для по-настоящему трудной задачи (большой или сложный код, архитектура, длинный разбор, сложная "
            f"математика) вызови ask_cloud — её сделает сильная модель {st['model']}, {how}. Простое делай сам.")


def save_key(pid: str, value: str) -> None:
    """The key goes only to data/accounts/<pid>.json (that folder is never sent anywhere or shown in the UI)."""
    import json
    from .config import DATA_DIR
    pid = "".join(ch for ch in pid.lower() if ch.isalnum() or ch in "_-")[:30]
    d = DATA_DIR / "accounts"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{pid}.json"
    try:
        cur = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cur = {}
    if value:
        cur["API_KEY"] = value.strip()
    else:
        cur.pop("API_KEY", None)
    p.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")


async def models(pid: str) -> list[dict]:
    if pid == "anthropic":
        k = providers.key("anthropic")
        if k:
            try:
                import anthropic
                async with anthropic.AsyncAnthropic(api_key=k) as c:
                    page = await c.models.list()
                    live = [m.id async for m in page]
                if live:
                    known = dict(ANTHROPIC_MODELS)
                    return [{"id": m, "note": known.get(m, "")} for m in live]
            except Exception:
                pass
        return [{"id": m, "note": n} for m, n in ANTHROPIC_MODELS]
    try:
        return [{"id": m, "note": ""} for m in await providers.models(pid)]
    except Exception as e:
        return [{"id": "", "note": f"не получил список: {type(e).__name__}: {str(e)[:150]}"}]


async def _anthropic(model: str, prompt: str, effort: str) -> tuple[str, str]:
    import anthropic
    k = providers.key("anthropic")
    if not k:
        raise RuntimeError("нет ключа Claude: вставь его во вкладке ИИ → Облачные модели")
    kw = {}
    if not model.startswith(NO_FALLBACK):
        kw = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    async with anthropic.AsyncAnthropic(api_key=k, timeout=600) as c:
        try:
            r = await c.beta.messages.create(model=model, max_tokens=16000, system=SYSTEM,
                                             output_config={"effort": effort},
                                             messages=[{"role": "user", "content": prompt}], **kw)
        except anthropic.AuthenticationError:
            raise RuntimeError("ключ Claude не подходит (проверь его во вкладке ИИ)") from None
        except anthropic.PermissionDeniedError as e:
            raise RuntimeError(f"нет доступа к модели {model}: {e.message[:200]}") from None
        except anthropic.NotFoundError:
            raise RuntimeError(f"модели {model} нет — выбери другую во вкладке ИИ") from None
        except anthropic.RateLimitError:
            raise RuntimeError("лимит запросов Claude — попробуй через минуту") from None
        except anthropic.APIStatusError as e:
            raise RuntimeError(f"Claude ответил ошибкой {e.status_code}: {e.message[:200]}") from None
        except anthropic.APIConnectionError:
            raise RuntimeError("нет связи с Claude (интернет?)") from None
    if r.stop_reason == "refusal":
        cat = getattr(r.stop_details, "category", None) if r.stop_details else None
        return "", f"Claude отказался выполнять это{f' ({cat})' if cat else ''}."
    text = "".join(b.text for b in r.content if b.type == "text").strip()
    note = " (ответ обрезан по длине)" if r.stop_reason == "max_tokens" else ""
    return text, f"{r.model}{note}"


async def _openai_compat(pid: str, model: str, prompt: str) -> tuple[str, str]:
    d = await providers.chat(pid, model, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                             None, {"temperature": 0.3, "num_predict": 8000})
    return (d["message"].get("content") or "").strip(), f"{pid}:{model}"


async def ask(task: str, context: str = "") -> str:
    s = settings()
    if not s["provider"] or not s["model"]:
        raise RuntimeError("облачная модель не выбрана (вкладка ИИ → Облачные модели)")
    prompt = task.strip() + (f"\n\nКонтекст из разговора:\n{context.strip()[:6000]}" if context.strip() else "")
    t = time.time()
    if s["provider"] == "anthropic":
        text, who = await _anthropic(s["model"], prompt, s["effort"])
    else:
        text, who = await _openai_compat(s["provider"], s["model"], prompt)
    if not text:
        return who or "Облачная модель ничего не ответила."
    return f"[{who}, {time.time() - t:.0f} с]\n{text}"


def new_pending(task: str, context: str) -> str:
    for k in [k for k, v in PENDING.items() if time.time() - v["t"] > 1800]:
        PENDING.pop(k, None)
    tok = uuid.uuid4().hex[:8]
    PENDING[tok] = {"task": task, "context": context, "t": time.time()}
    return tok
