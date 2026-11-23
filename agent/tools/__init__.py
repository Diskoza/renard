"""Tool registry. Every tool = python function + JSON schema. Only registered tools can be called."""
import asyncio
import inspect
import json
import re
from typing import Callable

REGISTRY: dict[str, dict] = {}
MAIN_THREAD: set[str] = {"use_skill", "skills_list", "remember", "memory_read", "search_history", "project_remember",
                         "project_search", "list_tasks", "cancel_task"}


def _in_thread(fn, kwargs):
    """Worker thread for a blocking tool; COM (UI Automation, audio, shell) needs initialising in every thread."""
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pythoncom = None
    return fn(**kwargs)


def tool(name: str, description: str, params: dict | None = None, required: list | None = None,
         modes: tuple = ("low", "medium", "high"), confirm: bool = False):
    def deco(fn: Callable):
        REGISTRY[name] = {
            "fn": fn,
            "modes": modes,
            "confirm": confirm,
            "schema": {"type": "function", "function": {
                "name": name, "description": description,
                "parameters": {"type": "object", "properties": params or {}, "required": required or []}}},
        }
        return fn
    return deco


def schemas(mode: str) -> list[dict]:
    return [t["schema"] for t in REGISTRY.values() if mode in t["modes"]]


def resolve_skill_alias(name: str) -> str | None:
    """Small models often call a skill as if it were a tool ('pc-cleanup-advisor(...)'). Map it to use_skill."""
    from ..skills import installed
    key = name.lower().replace("_", "-")
    for s in installed():
        if key in (s["name"].lower().replace("_", "-"), s["dir"].name.lower().replace("_", "-")):
            return s["name"]
    return None


def repair_args(sig, args: dict) -> dict:
    """Small models sometimes pack several arguments into one string ({"app": "X goal=Y"}) or name a parameter
    slightly differently. Unpack `key=value` / `key: value` tails that name a real parameter, so the call works
    instead of failing with 'missing argument'."""
    params = [p for p in sig.parameters if p != "ctx"]
    for k, v in list(args.items()):
        if not isinstance(v, str):
            continue
        for p in params:
            if p == k or p in args and args[p] not in ("", None):
                continue
            m = re.search(rf"(?:^|[\s,;]){re.escape(p)}\s*[=:]\s*", v)
            if m:
                args[p] = v[m.end():].strip().strip('"\'')
                v = v[:m.start()].strip().rstrip(",;")
                args[k] = v
    missing = [p for p, s in sig.parameters.items() if p != "ctx" and s.default is inspect._empty and p not in args]
    unknown = [k for k in args if k not in sig.parameters]
    if len(missing) == 1 and len(unknown) == 1 and isinstance(args[unknown[0]], str):
        args[missing[0]] = args.pop(unknown[0])
    return args


async def call(name: str, args: dict, ctx: dict) -> str:
    t = REGISTRY.get(name)
    if not t and resolve_skill_alias(name):
        return REGISTRY["use_skill"]["fn"](resolve_skill_alias(name))
    if not t:
        return f"Ошибка: инструмента '{name}' нет. Доступны: {', '.join(REGISTRY)}"
    fn = t["fn"]
    sig = inspect.signature(fn)
    args = repair_args(sig, dict(args or {}))
    kwargs = {k: v for k, v in (args or {}).items() if k in sig.parameters}
    if "ctx" in sig.parameters:
        kwargs["ctx"] = ctx
    try:
        if inspect.iscoroutinefunction(fn) or name in MAIN_THREAD:
            res = fn(**kwargs)
        else:
            res = await asyncio.to_thread(_in_thread, fn, kwargs)
        if inspect.isawaitable(res):
            res = await res
    except TypeError as e:
        need = ", ".join(f"{p}" for p in sig.parameters if p != "ctx")
        return (f"Ошибка аргументов {name}: {e}. Это не отказ: вызови {name} ЕЩЁ РАЗ, каждый аргумент отдельным "
                f"полем ({need}). Пользователя об этом не спрашивай.")
    except Exception as e:
        return f"Ошибка {name}: {type(e).__name__}: {e}"
    if not isinstance(res, str):
        res = json.dumps(res, ensure_ascii=False, indent=1)
    rec = CALLS.get()
    if rec is not None:
        rec.append({"tool": name, "args": {k: v for k, v in args.items() if k != "ctx"}, "result": res})
    return res


import contextvars
CALLS: contextvars.ContextVar = contextvars.ContextVar("renard_tool_calls", default=None)


S = {"type": "string"}
I = {"type": "integer"}

from . import pc, files, media, web, mem, system, code, skills_tools, tg_tools, extra, automation, music, avatar, apps, activity_tools, power, sound, news, media_analyze, docs, project_tools, meta, browser_tabs, school, app_tools, messengers, steam, images, longwork, installer, drivers, office, mail, browser_ctl, camera, planner_tools, command_tools, code_agents, node_tools, cloud_tools, photo
from .. import study
