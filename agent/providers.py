"""Other model servers besides Ollama (Astra: «любая модель»): LM Studio, Jan, llama.cpp server, vLLM, any
OpenAI-compatible endpoint, and optionally OpenRouter (cloud). Ollama stays the main one.

A mode uses a provider when its model is written «@<provider>:<model>», e.g. «@lmstudio:qwen2.5-7b-instruct».
Settings: data/providers.json (name, address); keys ONLY in data/accounts/<provider>.json {"API_KEY": "…"}.
Answers are converted to Ollama's shape, so the agent loop does not know the difference."""
import json
import time
import uuid
from typing import AsyncIterator

import httpx

from .config import DATA_DIR

PATH = DATA_DIR / "providers.json"
PRESETS = {
    "lmstudio": {"name": "LM Studio", "base_url": "http://127.0.0.1:1234/v1", "cloud": False,
                 "help": "LM Studio → Developer → Start Server (порт 1234). Загрузи модель в LM Studio — она появится тут."},
    "jan": {"name": "Jan", "base_url": "http://127.0.0.1:1337/v1", "cloud": False,
            "help": "Jan → Settings → Local API Server → Start."},
    "llamacpp": {"name": "llama.cpp server", "base_url": "http://127.0.0.1:8080/v1", "cloud": False,
                 "help": "llama-server -m model.gguf --port 8080"},
    "openai": {"name": "OpenAI", "base_url": "https://api.openai.com/v1", "cloud": True,
               "help": "Ключ: platform.openai.com/api-keys. Запросы уходят в интернет."},
    "gemini": {"name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "cloud": True,
               "help": "Ключ: aistudio.google.com/apikey. Запросы уходят в интернет."},
    "deepseek": {"name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "cloud": True,
                 "help": "Ключ: platform.deepseek.com/api_keys. Запросы уходят в интернет."},
    "groq": {"name": "Groq", "base_url": "https://api.groq.com/openai/v1", "cloud": True,
             "help": "Ключ: console.groq.com/keys. Очень быстрые открытые модели. Запросы уходят в интернет."},
    "openrouter": {"name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "cloud": True,
                   "help": "Ключ: openrouter.ai/keys → положи в data\\accounts\\openrouter.json как {\"API_KEY\": \"…\"} "
                           "(или: python -m agent.accounts_cli token openrouter). Запросы уходят в интернет."},
}


def _cfg() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d: dict):
    PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def key(pid: str) -> str:
    try:
        d = json.loads((DATA_DIR / "accounts" / f"{pid}.json").read_text(encoding="utf-8"))
        return str(d.get("API_KEY") or d.get("api_key") or d.get("KEY") or "")
    except Exception:
        return ""


def all_providers() -> list[dict]:
    cfg = _cfg()
    out = []
    for pid, p in {**PRESETS, **{k: v for k, v in cfg.items() if k not in PRESETS}}.items():
        c = {**p, **cfg.get(pid, {})}
        out.append({"id": pid, "name": c.get("name", pid), "base_url": c.get("base_url", ""), "cloud": bool(c.get("cloud")),
                    "enabled": bool(c.get("enabled", False)), "help": c.get("help", ""), "has_key": bool(key(pid)),
                    "builtin": pid in PRESETS})
    return out


def get(pid: str) -> dict | None:
    return next((p for p in all_providers() if p["id"] == pid), None)


def upsert(pid: str, d: dict) -> dict:
    cfg = _cfg()
    pid = "".join(ch for ch in (pid or d.get("name") or "custom").lower() if ch.isalnum() or ch in "_-")[:30] or "custom"
    cur = cfg.setdefault(pid, {})
    for k in ("name", "base_url", "enabled", "cloud"):
        if k in d:
            cur[k] = d[k]
    if "base_url" in cur:
        cur["base_url"] = str(cur["base_url"]).rstrip("/")
    _save(cfg)
    return get(pid)


def remove(pid: str) -> bool:
    cfg = _cfg()
    ok = cfg.pop(pid, None) is not None
    _save(cfg)
    return ok


def parse(model: str) -> tuple[str, str] | None:
    """«@lmstudio:qwen2.5-7b» → ("lmstudio", "qwen2.5-7b")."""
    if isinstance(model, str) and model.startswith("@") and ":" in model:
        pid, name = model[1:].split(":", 1)
        return pid, name
    return None


def _client(pid: str, timeout: float = 600) -> httpx.AsyncClient:
    p = get(pid)
    if not p or not p["base_url"]:
        raise RuntimeError(f"провайдер «{pid}» не настроен (вкладка ИИ → Другие серверы моделей)")
    h = {"Content-Type": "application/json"}
    k = key(pid)
    if k:
        h["Authorization"] = f"Bearer {k}"
    elif p["cloud"]:
        raise RuntimeError(f"нет ключа {pid}: положи его в data\\accounts\\{pid}.json как {{\"API_KEY\": \"…\"}}")
    if pid == "openrouter":
        h["HTTP-Referer"], h["X-Title"] = "http://127.0.0.1:8790", "Renard"
    return httpx.AsyncClient(base_url=p["base_url"], headers=h, timeout=httpx.Timeout(timeout, connect=6))


async def models(pid: str) -> list[str]:
    async with _client(pid, 15) as c:
        r = await c.get("/models")
        r.raise_for_status()
        return sorted(m.get("id", "") for m in r.json().get("data", []) if m.get("id"))


async def check(pid: str) -> dict:
    t0 = time.time()
    try:
        ms = await models(pid)
        return {"ok": True, "models": ms, "ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300], "models": []}


def to_openai(messages: list) -> list:
    out, pending = [], []
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            calls = []
            for tc in m["tool_calls"]:
                f = tc.get("function", {})
                cid = tc.get("id") or "call_" + uuid.uuid4().hex[:12]
                args = f.get("arguments", {})
                calls.append({"id": cid, "type": "function",
                              "function": {"name": f.get("name", ""), "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)}})
                pending.append((f.get("name", ""), cid))
            out.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
        elif role == "tool":
            name = m.get("tool_name") or m.get("name") or ""
            idx = next((i for i, (n, _) in enumerate(pending) if n == name), 0 if pending else None)
            cid = pending.pop(idx)[1] if idx is not None else "call_" + uuid.uuid4().hex[:12]
            out.append({"role": "tool", "tool_call_id": cid, "content": m.get("content") or ""})
        elif m.get("images"):
            parts = [{"type": "text", "text": m.get("content") or ""}]
            parts += [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b}"}} for b in m["images"]]
            out.append({"role": role, "content": parts})
        else:
            out.append({"role": role, "content": m.get("content") or ""})
    return out


def _payload(name: str, messages: list, tools: list | None, cfg: dict, stream: bool) -> dict:
    p = {"model": name, "messages": to_openai(messages), "stream": stream,
         "temperature": cfg.get("temperature", 0.3), "max_tokens": cfg.get("num_predict", 1000)}
    if tools:
        p["tools"] = tools
    return p


def _calls(raw: list) -> list:
    out = []
    for tc in raw or []:
        f = tc.get("function", {})
        args = f.get("arguments") or "{}"
        try:
            args = json.loads(args) if isinstance(args, str) else args
        except json.JSONDecodeError:
            args = {}
        out.append({"id": tc.get("id"), "function": {"name": f.get("name", ""), "arguments": args}})
    return out


async def chat(pid: str, name: str, messages: list, tools: list | None, cfg: dict) -> dict:
    t0 = time.time()
    async with _client(pid) as c:
        r = await c.post("/chat/completions", json=_payload(name, messages, tools, cfg, False))
        if r.status_code != 200:
            raise RuntimeError(f"{pid} {r.status_code}: {r.text[:300]}")
        d = r.json()
    msg = (d.get("choices") or [{}])[0].get("message", {}) or {}
    return {"message": {"role": "assistant", "content": msg.get("content") or "", "tool_calls": _calls(msg.get("tool_calls"))},
            "model": f"@{pid}:{name}", "_wall": time.time() - t0, "done": True}


async def stream(pid: str, name: str, messages: list, tools: list | None, cfg: dict) -> AsyncIterator[tuple[str, object]]:
    content, parts, t0, n = [], {}, time.time(), 0
    async with _client(pid) as c:
        async with c.stream("POST", "/chat/completions", json=_payload(name, messages, tools, cfg, True)) as r:
            if r.status_code != 200:
                body = await r.aread()
                raise RuntimeError(f"{pid} {r.status_code}: {body[:300]!r}")
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    ch = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = ((ch.get("choices") or [{}])[0] or {}).get("delta", {}) or {}
                think = delta.get("reasoning") or delta.get("reasoning_content")
                if think:
                    yield "think", think
                if delta.get("content"):
                    content.append(delta["content"]); n += 1
                    yield "token", delta["content"]
                for tc in delta.get("tool_calls") or []:
                    slot = parts.setdefault(tc.get("index", 0), {"id": None, "function": {"name": "", "arguments": ""}})
                    slot["id"] = tc.get("id") or slot["id"]
                    f = tc.get("function") or {}
                    slot["function"]["name"] += f.get("name") or ""
                    slot["function"]["arguments"] += f.get("arguments") or ""
    wall = time.time() - t0
    yield "done", {"content": "".join(content), "tool_calls": _calls([parts[k] for k in sorted(parts)]),
                   "stats": {"model": f"@{pid}:{name}", "tokens": n, "tps": round(n / wall, 1) if wall else None,
                             "load_s": 0, "wall_s": round(wall, 2), "done_reason": "stop"}}
