"""Own plugins: plugins/<name>/plugin.json + tools.py (+ optional skills/<skill>/SKILL.md).

tools.py registers tools the same way as built-in ones:
    from agent.tools import tool, S
    @tool("hello", "Поздороваться", {"name": S}, ["name"])
    def hello(name: str) -> str: return f"Привет, {name}!"
Enabled plugins are imported at server start; their skills appear next to the built-in skills.
"""
import importlib.util
import json
import re
import sys

from .config import ROOT
from .logs import quiet

DIR = ROOT / "plugins"
DIR.mkdir(exist_ok=True)
LOADED: dict[str, str] = {}

TEMPLATE_TOOLS = '''"""Плагин {name}: свои инструменты для Renard. После правки — перезапусти сервер (Настройки → Перезапуск)."""
from agent.tools import S, tool


@tool("{slug}_hello", "Пример инструмента плагина {name}: поздороваться", {{"who": S}}, ["who"])
def hello(who: str) -> str:
    return f"Привет, {{who}}! Это плагин {name}."
'''


def all_plugins() -> list[dict]:
    out = []
    for d in sorted(p for p in DIR.iterdir() if p.is_dir()):
        meta = {"name": d.name, "description": "", "enabled": True}
        try:
            meta.update(json.loads((d / "plugin.json").read_text(encoding="utf-8")))
        except Exception:
            quiet()
        meta["dir"] = str(d)
        meta["status"] = LOADED.get(d.name, "не загружен")
        meta["skills"] = [s.name for s in (d / "skills").iterdir()] if (d / "skills").is_dir() else []
        out.append(meta)
    return out


def load_all():
    for p in all_plugins():
        if not p.get("enabled", True):
            continue
        f = DIR / p["name"] / "tools.py"
        if not f.exists():
            LOADED[p["name"]] = "ok (без инструментов)"
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"renard_plugin_{p['name']}", f)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            LOADED[p["name"]] = "ok"
        except Exception as e:
            LOADED[p["name"]] = f"ошибка: {type(e).__name__}: {e}"


def create(name: str, description: str = "") -> dict:
    slug = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_") or "plugin"
    d = DIR / slug
    d.mkdir(exist_ok=True)
    (d / "plugin.json").write_text(json.dumps({"name": slug, "title": name, "description": description, "enabled": True},
                                              ensure_ascii=False, indent=1), encoding="utf-8")
    if not (d / "tools.py").exists():
        (d / "tools.py").write_text(TEMPLATE_TOOLS.format(name=name, slug=slug), encoding="utf-8")
    (d / "skills").mkdir(exist_ok=True)
    return {"name": slug, "dir": str(d)}


def set_enabled(name: str, on: bool):
    f = DIR / name / "plugin.json"
    meta = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"name": name}
    meta["enabled"] = on
    f.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
