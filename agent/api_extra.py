"""HTTP API for the new UI: prefs, projects, chats, scheduled tasks, node commands, skills, connectors, plugins,
AI models, voice, widgets, avatars."""
import asyncio
import json
import re
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import commands, plugins, prefs, projects, scheduler, skills
from .config import DATA_DIR, ROOT, SETTINGS
from .mcp_client import HUB, PRESETS, load_cfg, runtimes, save_cfg
from .logs import quiet

AVATARS = DATA_DIR / "avatars"


def chat_title(first: str | None) -> str:
    """First user message -> a readable title: no [файл: …] markers or attached context, a file name instead."""
    t = (first or "").split("\n\n[Пользователь прислал")[0]
    files = re.findall(r"\[(?:файл|папка): ([^\]]+)\]", t)
    t = re.sub(r"\[(?:файл|папка): [^\]]+\]\s*", "", t).strip()
    t = re.sub(r"\s+", " ", t)
    if not t and files:
        t = "📎 " + ", ".join(Path(f).name for f in files)
    elif files:
        t = "📎 " + t
    return (t or "(без текста)")[:80]
AVATARS.mkdir(exist_ok=True)


def build(S) -> APIRouter:
    """S: namespace with agent, broadcast, telegram, wake, sched, runner."""
    r = APIRouter(prefix="/api")
    for part in (_prefs, _avatar_body, _archive, _projects, _chats, _scheduled_tasks, _node_commands, _wake_on_lan, _skills, _connectors, _plugins, _ai_models, _built_in_plugins, _other_model_servers, _cloud_escalation, _personas, _widgets, _own_pixel_characters, _avatars, _server):
        part(r, S)
    from .api_photo import routes as _photo_routes
    _photo_routes(r)
    return r


def _prefs(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    @r.get("/prefs")
    def get_prefs():
        return prefs.load()

    @r.post("/prefs")
    async def set_prefs(request: Request):
        new = prefs.update(await request.json())
        await S.broadcast({"type": "prefs"})
        return new


def _avatar_body(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    @r.post("/avatar")
    async def avatar_act(request: Request):
        from .tools.avatar import avatar
        d = await request.json()
        return {"text": await avatar(d.get("action", ""), d.get("emotion", ""), d.get("say", ""),
                                     d.get("activity", ""), d.get("place", ""), d.get("style", ""),
                                     d.get("wear", ""), d.get("take_off", ""), d.get("weather", ""), d.get("anim", ""),
                                     d.get("face", ""), d.get("red"))}

    @r.post("/debug/event")
    async def debug_event(request: Request):
        if request.client and request.client.host not in ("127.0.0.1", "::1", "localhost"):
            return {"ok": False}
        d = await request.json()
        if d.get("type") not in ("beat", "activity", "avatar"):
            return {"ok": False, "why": "type"}
        await S.broadcast(d)
        return {"ok": True}


def _archive(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    @r.get("/archive")
    async def archive_info():
        from . import archive
        st = await asyncio.to_thread(archive.stats)
        st["found"] = await asyncio.to_thread(archive.find_exports)
        return st

    @r.post("/archive/import")
    async def archive_import(request: Request):
        from . import archive
        d = await request.json()
        p = Path(d.get("path") or "")
        if not p.is_file() or p.suffix.lower() != ".zip":
            return JSONResponse({"error": "нужен .zip экспорта ChatGPT или Claude"}, status_code=400)
        try:
            res = await asyncio.to_thread(archive.import_export, p)
        except (ValueError, OSError) as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": f"не смог прочитать архив: {type(e).__name__}"}, status_code=400)
        return res

    @r.post("/archive/forget")
    async def archive_forget(request: Request):
        from . import archive
        d = await request.json()
        n = await asyncio.to_thread(archive.forget, d.get("source", ""), d.get("account", ""))
        return {"deleted": n}

    @r.get("/archive/search")
    async def archive_search(q: str, limit: int = 5):
        from . import archive
        return {"hits": await asyncio.to_thread(archive.search, q, min(limit, 20))}


def _projects(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    @r.get("/projects")
    def list_projects():
        sess = prefs.get("session_projects", {}) or {}
        out = []
        for p in projects.all_projects():
            out.append({**p, "chats": sum(1 for v in sess.values() if v == p["id"])})
        return {"projects": out}

    @r.post("/projects")
    async def save_project(request: Request):
        return projects.upsert(await request.json())

    @r.delete("/projects/{pid}")
    def del_project(pid: str):
        return {"ok": projects.delete(pid)}

    @r.get("/projects/{pid}")
    def project_detail(pid: str):
        p = projects.get(pid)
        if not p:
            return JSONResponse({"error": "нет проекта"}, 404)
        idx = projects._index(pid)
        return {**p, "knowledge": projects.knowledge(pid), "memory": projects.memory(pid),
                "index": {"chunks": len(idx), "files": len({c["file"] for c in idx}),
                          "chars": sum(len(c["text"]) for c in idx)}}

    @r.post("/projects/{pid}/files")
    async def project_add_file(pid: str, request: Request, name: str = "file"):
        if not projects.get(pid):
            return JSONResponse({"error": "нет проекта"}, 404)
        return await asyncio.to_thread(projects.add_file, pid, name, await request.body())

    @r.delete("/projects/{pid}/files/{name}")
    def project_del_file(pid: str, name: str):
        return {"ok": projects.remove_file(pid, name)}

    @r.post("/projects/{pid}/reindex")
    async def project_reindex(pid: str):
        return await asyncio.to_thread(projects.reindex, pid)

    @r.post("/projects/{pid}/memory")
    async def project_memory_save(pid: str, request: Request):
        d = await request.json()
        (projects.pdir(pid) / "memory.md").write_text(d.get("memory", ""), encoding="utf-8")
        return {"ok": True}


def _chats(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    agent = S.agent
    @r.get("/chats")
    def chats(q: str = "", project: str = ""):
        db = agent.memory.db
        rows = db.execute(
            "SELECT session, MAX(ts), COUNT(*), "
            "(SELECT content FROM messages m2 WHERE m2.session=m.session AND m2.role='user' ORDER BY id LIMIT 1) "
            "FROM messages m WHERE role IN ('user','assistant') GROUP BY session ORDER BY MAX(ts) DESC LIMIT 300").fetchall()
        p = prefs.load()
        titles, pins, sp = p.get("session_titles", {}), set(p.get("pinned_sessions", [])), p.get("session_projects", {})
        hits = None
        if q.strip():
            hits = {s for (s,) in db.execute("SELECT DISTINCT session FROM messages WHERE content LIKE ?", (f"%{q}%",))}
        out = []
        for sid, t1, n, first in rows:
            if hits is not None and sid not in hits:
                continue
            if sid.startswith(("eval-", "test-", "sim-")):
                continue
            if project and sp.get(sid) != project:
                continue
            src = ("telegram" if sid.startswith("tg-") else "voice" if sid == "wake" else
                   "task" if sid.startswith("task-") else "command" if sid == "commands" else "window")
            out.append({"id": sid, "title": titles.get(sid) or chat_title(first), "n": n, "src": src,
                        "ts": t1, "when": time.strftime("%d.%m %H:%M", time.localtime(t1)), "pinned": sid in pins,
                        "project": sp.get(sid, "")})
        return {"chats": out}

    @r.get("/chats/{sid}")
    def chat(sid: str):
        rows = agent.memory.db.execute(
            "SELECT ts, role, content, mode FROM (SELECT * FROM messages WHERE session=? AND role IN ('user','assistant') "
            "ORDER BY id DESC LIMIT 300) ORDER BY id", (sid,)).fetchall()
        return {"id": sid, "project": (prefs.get("session_projects", {}) or {}).get(sid, ""),
                "title": (prefs.get("session_titles", {}) or {}).get(sid, ""),
                "messages": [{"time": time.strftime("%d.%m %H:%M", time.localtime(t)), "role": ro, "content": c,
                              "mode": m} for t, ro, c, m in rows]}

    @r.post("/chats/{sid}")
    async def chat_meta(sid: str, request: Request):
        d = await request.json()
        p = prefs.load()
        patch = {}
        if "title" in d:
            patch["session_titles"] = {**p["session_titles"], sid: d["title"]}
        if "pinned" in d:
            pins = [x for x in p["pinned_sessions"] if x != sid] + ([sid] if d["pinned"] else [])
            patch["pinned_sessions"] = pins
        if "project" in d:
            patch["session_projects"] = {**p["session_projects"], sid: d["project"]}
        prefs.update(patch)
        return {"ok": True}

    @r.get("/chats/{sid}/memory")
    def chat_memory(sid: str):
        """What Renard remembered from this chat — shown in the delete dialog («забыть и это»)."""
        return {"items": agent.memory.learned_from(sid)}

    @r.post("/chats/{sid}/forget")
    async def chat_forget(sid: str, request: Request):
        """Forget only the lines the user ticked in the delete dialog (they must be among what came from this chat)."""
        want = {(i.get("note"), i.get("line")) for i in (await request.json()).get("items", []) if isinstance(i, dict)}
        items = [i for i in agent.memory.learned_from(sid) if (i["note"], i["line"]) in want]
        return {"ok": True, "forgotten": agent.memory.forget_lines(items)}

    @r.delete("/chats/{sid}")
    def chat_delete(sid: str, forget: int = 0):
        db = agent.memory.db
        forgotten = agent.memory.forget_lines(agent.memory.learned_from(sid)) if forget else 0
        try:
            db.execute("DELETE FROM mem_sources WHERE session=?", (sid,))
        except Exception:
            quiet()
        ids = [i for (i,) in db.execute("SELECT id FROM messages WHERE session=?", (sid,))]
        db.execute("DELETE FROM messages WHERE session=?", (sid,))
        for i in ids:
            try:
                db.execute("INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', ?, '')", (i,))
            except Exception:
                quiet()
        db.commit()
        if sid in getattr(agent, "last_study", {}):
            agent.last_study.pop(sid, None)
        return {"ok": True, "deleted": len(ids), "forgotten": forgotten}


def _scheduled_tasks(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    @r.get("/tasks")
    def tasks():
        return {"tasks": scheduler.all_tasks()}

    @r.post("/tasks")
    async def save_task(request: Request):
        try:
            return scheduler.upsert(await request.json())
        except ValueError as e:
            return JSONResponse({"error": str(e)}, 400)

    @r.delete("/tasks/{tid}")
    def del_task(tid: str):
        return {"ok": scheduler.delete(tid)}

    @r.post("/tasks/{tid}/run")
    async def run_task(tid: str):
        t = next((x for x in scheduler.all_tasks() if x["id"] == tid), None)
        if not t:
            return JSONResponse({"error": "нет задачи"}, 404)
        return {"result": await S.sched.run(t)}


def _node_commands(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    @r.get("/commands")
    def cmds():
        return {"commands": commands.all_commands(), "nodes": commands.NODES}

    @r.post("/commands")
    async def save_cmd(request: Request):
        c = commands.upsert(await request.json())
        await S.broadcast({"type": "commands_changed"})
        return c


def _wake_on_lan(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    _wol_cache = {"t": 0.0, "info": None}

    @r.get("/wol")
    async def wol_info(fresh: int = 0):
        """Up to ~15 s (adapter, router, public IP checks) and it rarely changes: one minute cache, dropped on any
        WOL setting change below (and «?fresh=1»)."""
        if not fresh and _wol_cache["info"] is not None and time.time() - _wol_cache["t"] < 60:
            return _wol_cache["info"]
        from . import wol
        info = await asyncio.to_thread(wol.readiness)
        s = wol.settings()
        info["has_token"] = bool(s.get("token"))
        info["package"] = str(wol.OUT / "renard_waker.zip") if (wol.OUT / "renard_waker.zip").exists() else ""
        info["internet"] = await asyncio.to_thread(wol.internet_info, info)
        _wol_cache.update(t=time.time(), info=info)
        return info

    @r.post("/wol/internet")
    async def wol_internet(request: Request):
        """DDNS name (optional) and the forwarded port of the internet mode."""
        _wol_cache["info"] = None
        from . import wol
        d = await request.json()
        host = (d.get("host") or "").strip()
        if host and not re.fullmatch(r"[A-Za-z0-9.-]{3,253}", host):
            return JSONResponse({"error": "адрес: имя вроде myhome.duckdns.org или IP"}, status_code=400)
        port = str(d.get("port") or "").strip()
        if port and not (port.isdigit() and 1 <= int(port) <= 65535):
            return JSONResponse({"error": "порт — число от 1 до 65535"}, status_code=400)
        wol.save_settings(wan_host=host, **({"wan_port": int(port)} if port else {}))
        return {"ok": True}

    @r.post("/wol/listen")
    async def wol_listen_start(request: Request):
        _wol_cache["info"] = None
        from . import wol
        d = await request.json() if (await request.body()) else {}
        return await asyncio.to_thread(wol.start_listen, int(d.get("seconds") or 180))

    @r.get("/wol/listen")
    async def wol_listen_status():
        from . import wol
        return wol.listen_status()

    @r.post("/wol/button")
    async def wol_button(request: Request):
        """The phone button package (no bot, internet mode)."""
        _wol_cache["info"] = None
        from . import wol
        d = await request.json() if (await request.body()) else {}
        z = await asyncio.to_thread(wol.build_phone_package)
        sent = ""
        if d.get("send"):
            from .telegram_bot import BRIDGE
            sent = await BRIDGE.send_file(str(z), "Кнопка «Включить ПК» для телефона: README.txt внутри "
                                                   "(или просто приложение Wake On Lan с этими же данными)") \
                if BRIDGE else "Telegram не подключён"
        return {"ok": True, "path": str(z), "sent": sent}

    @r.post("/wol/package")
    async def wol_package(request: Request):
        _wol_cache["info"] = None
        from . import wol
        d = await request.json()
        try:
            z = await asyncio.to_thread(wol.build_package, (d.get("token") or "").strip())
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        sent = ""
        if d.get("send"):
            from .telegram_bot import BRIDGE
            sent = await BRIDGE.send_file(str(z), "Будильник Renard: распакуй на телефоне (Termux) или Raspberry Pi и "
                                                   "запусти python renard_waker.py — инструкция в README.txt") \
                if BRIDGE else "Telegram не подключён"
        return {"ok": True, "path": str(z), "sent": sent}

    @r.post("/commands/learn")
    async def learn_cmd(request: Request):
        """«Сохранить как команду» card: name + trigger phrases + the steps the AI just ran."""
        d = await request.json()
        phrases = ", ".join(p.strip().lower() for p in re.split(r"[,\n]", d.get("phrases", "")) if p.strip())
        if not phrases:
            return JSONResponse({"error": "нужна хотя бы одна фраза"}, status_code=400)
        try:
            c = commands.from_steps(d.get("name") or phrases.split(",")[0], phrases, d.get("steps") or [], d.get("say", ""))
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        await S.broadcast({"type": "commands_changed"})
        return c

    @r.get("/commands/gallery")
    def cmd_gallery():
        from . import command_templates
        return {"templates": command_templates.gallery()}

    @r.post("/commands/gallery/{tid}")
    async def cmd_gallery_add(tid: str):
        from . import command_templates
        try:
            c = command_templates.install(tid)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        await S.broadcast({"type": "commands_changed"})
        return c

    @r.delete("/commands/{cid}")
    async def del_cmd(cid: str):
        ok = commands.delete(cid)
        await S.broadcast({"type": "commands_changed"})
        return {"ok": ok}

    @r.post("/commands/{cid}/run")
    async def run_cmd(cid: str, node: str = ""):
        return {"log": await S.runner.run(cid, node or None)}

    @r.get("/commands_hotkeys")
    def cmd_hotkeys():
        return {"hotkeys": commands.hotkeys()}


def _skills(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    @r.get("/skills")
    def skills_list():
        return {"skills": [{"name": s["name"], "description": s["description"], "source": s["source"],
                            "enabled": s["enabled"], "dir": str(s["dir"])} for s in skills.installed(True)]}

    @r.get("/skills/{name}")
    def skill_get(name: str):
        for s in skills.installed(True):
            if s["name"] == name:
                return {"name": s["name"], "description": s["description"], "body": s["body"], "source": s["source"],
                        "dir": str(s["dir"])}
        return JSONResponse({"error": "нет навыка"}, 404)

    @r.post("/skills")
    async def skill_save(request: Request):
        d = await request.json()
        if d.get("toggle") is not None:
            off = set(prefs.get("disabled_skills", []) or [])
            off.discard(d["name"]) if d["toggle"] else off.add(d["name"])
            prefs.update({"disabled_skills": sorted(off)})
            return {"ok": True}
        path = skills.save_skill(d["name"], d.get("description", ""), d.get("body", ""))
        return {"ok": True, "path": str(path)}

    @r.delete("/skills/{name}")
    def skill_del(name: str):
        return {"result": skills.remove(name)}

    @r.get("/skills_search")
    async def skill_search(q: str = "", source: str = "clawhub"):
        try:
            if source == "clawhub":
                res = await asyncio.to_thread(skills.clawhub_search, q, 25)
                return {"results": [{"id": x.get("slug") or x.get("name"), "title": x.get("displayName") or x.get("name"),
                                     "description": (x.get("summary") or x.get("description") or "")[:200]} for x in res]}
            res = await asyncio.to_thread(skills.search, q, "hermes", 30)
            return {"results": [{"id": f"hermes:{x}", "title": x, "description": ""} for x in res]}
        except Exception as e:
            return {"results": [], "error": str(e)}

    @r.post("/skills_install")
    async def skill_install(request: Request):
        spec = (await request.json())["id"]
        spec = spec if ":" in spec else f"clawhub:{spec}"
        return {"result": await asyncio.to_thread(skills.install, spec)}


def _connectors(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    @r.get("/mcp")
    def mcp_status():
        return {"servers": HUB.status(), "presets": PRESETS, "runtimes": runtimes()}

    @r.post("/mcp")
    async def mcp_save(request: Request):
        d = await request.json()
        cfg = load_cfg()
        name = re.sub(r"[^a-z0-9_-]+", "-", d["name"].lower()).strip("-")
        old = cfg["servers"].get(name, {})
        env = {**old.get("env", {}), **{k: v for k, v in (d.get("env") or {}).items() if v != "••••"}}
        cfg["servers"][name] = {"command": d.get("command", old.get("command", "npx")),
                                "args": d.get("args", old.get("args", [])), "env": env,
                                "enabled": d.get("enabled", old.get("enabled", True))}
        save_cfg(cfg)
        await HUB.restart(name)
        return {"ok": True, "name": name}

    @r.delete("/mcp/{name}")
    async def mcp_del(name: str):
        cfg = load_cfg()
        cfg["servers"].pop(name, None)
        save_cfg(cfg)
        await HUB.restart(name)
        return {"ok": True}

    @r.post("/mcp/{name}/restart")
    async def mcp_restart(name: str):
        await HUB.restart(name)
        return {"ok": True}


def _plugins(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    @r.get("/plugins")
    def plugins_list():
        return {"plugins": plugins.all_plugins(), "dir": str(plugins.DIR)}

    @r.post("/plugins")
    async def plugins_create(request: Request):
        d = await request.json()
        if "enabled" in d and d.get("name") and not d.get("create"):
            plugins.set_enabled(d["name"], bool(d["enabled"]))
            return {"ok": True, "restart": True}
        return plugins.create(d.get("name") or "my-plugin", d.get("description", ""))

    @r.get("/file")
    def get_file(path: str):
        """Preview of an attached picture in the chat (only inside the allowed folders)."""
        from fastapi.responses import FileResponse
        from .tools.files import ROOTS, WORKSPACE
        p = Path(path).resolve()
        allowed = [WORKSPACE, DATA_DIR] + list(ROOTS)
        if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp") and \
                any(p == a or a in p.parents for a in allowed):
            return FileResponse(str(p))
        from fastapi import HTTPException
        raise HTTPException(404)

    @r.post("/open_path")
    async def open_path(request: Request):
        """A file from an answer: open it with its program, or show it selected in Explorer (allowed folders only)."""
        import os
        import subprocess
        d = await request.json()
        p = Path(str(d.get("path", ""))).resolve()
        from .tools.files import ROOTS, WORKSPACE
        allowed = [ROOT, DATA_DIR, WORKSPACE] + list(ROOTS) + [Path(x) for x in projects_folders()]
        if not p.exists() or not any(p == a or a in p.parents for a in allowed):
            return JSONResponse({"error": "файла нет или он вне разрешённых папок"}, 400)
        if d.get("reveal"):
            subprocess.Popen(["explorer.exe", "/select,", str(p)])
        else:
            os.startfile(str(p))
        return {"ok": True}

    @r.post("/open_folder")
    async def open_folder(request: Request):
        import os
        p = Path((await request.json())["path"])
        from .tools.files import ROOTS
        allowed = [ROOT, DATA_DIR] + list(ROOTS) + [Path(x) for x in projects_folders()]
        if p.exists() and any(p == a or a in p.parents for a in allowed):
            os.startfile(str(p))
            return {"ok": True}
        return JSONResponse({"error": "папка вне Renard"}, 400)

    def projects_folders():
        return [f for pr in projects.all_projects() for f in pr.get("folders", [])]


def _ai_models(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    agent = S.agent
    @r.get("/ai")
    async def ai_info():
        try:
            tags = (await agent.llm.client.get("/api/tags")).json().get("models", [])
            models = [{"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 1),
                       "family": m.get("details", {}).get("family", ""), "params": m.get("details", {}).get("parameter_size", "")}
                      for m in tags]
            ok = True
        except Exception:
            models, ok = [], False
        loaded = [m["name"] for m in await agent.llm.loaded_models()] if ok else []
        return {"ollama": ok, "models": models, "loaded": loaded, "modes": agent.llm.modes, "url": agent.llm.url}

    @r.post("/ai")
    async def ai_set(request: Request):
        d = await request.json()
        mode = d.pop("mode")
        allowed = {"model", "temperature", "num_predict", "num_ctx", "keep_alive", "max_steps", "think"}
        patch = {k: v for k, v in d.items() if k in allowed}
        agent.llm.modes[mode].update(patch)
        cur = prefs.get("ai", {}) or {}
        cur[mode] = {**cur.get(mode, {}), **patch}
        prefs.update({"ai": cur})
        return {"ok": True, "mode": agent.llm.modes[mode]}


def _built_in_plugins(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    @r.get("/chess")
    async def chess_state():
        from .chess_game import game
        return await asyncio.to_thread(game().state)

    @r.post("/chess/{action}")
    async def chess_act(action: str, request: Request):
        from .chess_game import game
        d = await request.json() if (await request.body()) else {}
        g = game()
        async with g.lock:
            if action == "new":
                return await asyncio.to_thread(g.new, bool(d.get("white", True)), int(d.get("level") or 2))
            if action == "move":
                return await asyncio.to_thread(g.move, str(d.get("uci") or ""))
            if action == "undo":
                return await asyncio.to_thread(g.undo)
            if action == "hint":
                return await asyncio.to_thread(g.hint)
        return JSONResponse({"error": "нет такого действия"}, status_code=400)

    @r.get("/builtin_plugins")
    def builtin_plugins():
        from .chess_game import stockfish
        from .tools.code_agents import installed, NAMES, JOBS
        have = installed()
        return {"chess": {"engine": "Stockfish" if stockfish() else "встроенный"},
                "coders": [{"id": k, "name": v, "installed": k in have} for k, v in NAMES.items()],
                "jobs": [{k: j.get(k) for k in ("id", "agent", "folder", "task", "status", "seconds")} for j in list(JOBS.values())[-5:]]}


def _other_model_servers(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    @r.get("/providers")
    async def providers_list():
        from . import providers
        items = providers.all_providers()
        async def one(p):
            if p["enabled"]:
                p.update(await providers.check(p["id"]))
            return p
        return {"providers": await asyncio.gather(*(one(p) for p in items))}

    @r.post("/providers/{pid}")
    async def provider_save(pid: str, request: Request):
        from . import providers
        d = await request.json()
        p = providers.upsert(pid, d)
        return {**p, **(await providers.check(p["id"]) if p["enabled"] else {})}


def _cloud_escalation(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    agent = S.agent
    @r.get("/cloud")
    def cloud_get():
        from . import cloud, providers
        clouds = [{"id": "anthropic", "name": "Claude (Anthropic)", "help": "Ключ: console.anthropic.com → API Keys"}]
        clouds += [{"id": p["id"], "name": p["name"], "help": p["help"]} for p in providers.all_providers() if p["cloud"]]
        for c in clouds:
            c["has_key"] = bool(providers.key(c["id"]))
        return {**cloud.status(), "clouds": clouds}

    @r.post("/cloud")
    async def cloud_set(request: Request):
        from . import cloud
        d = await request.json()
        patch = {k: d[k] for k in ("provider", "model", "permission", "effort") if k in d}
        if patch.get("permission", "off") not in ("off", "ask", "auto") or                 patch.get("effort", "high") not in ("low", "medium", "high", "xhigh", "max"):
            return {"ok": False, "error": "неверное значение"}
        if "key" in d:
            cloud.save_key(d.get("provider") or cloud.settings()["provider"], d["key"] or "")
        if patch:
            prefs.update({"cloud": patch})
        if d.get("provider") and d["provider"] != "anthropic" and d.get("key"):
            from . import providers
            providers.upsert(d["provider"], {"enabled": True})
        return {"ok": True, **cloud.status()}

    @r.get("/cloud/models")
    async def cloud_models(provider: str):
        from . import cloud
        return {"models": await cloud.models(provider)}

    @r.post("/cloud/test")
    async def cloud_test():
        from . import cloud
        try:
            return {"ok": True, "answer": (await cloud.ask("Ответь одним словом: работает?"))[:300]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}

    @r.delete("/providers/{pid}")
    def provider_del(pid: str):
        from . import providers
        return {"ok": providers.remove(pid)}

    @r.post("/ai/pull")
    async def ai_pull(request: Request):
        name = (await request.json())["name"].strip()

        async def pull():
            last = 0
            try:
                async with agent.llm.client.stream("POST", "/api/pull", json={"name": name}) as resp:
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        ev = json.loads(line)
                        if time.time() - last > 1 or ev.get("status") == "success":
                            last = time.time()
                            pct = f" {ev['completed'] * 100 // ev['total']}%" if ev.get("total") and ev.get("completed") else ""
                            await S.broadcast({"type": "activity", "source": "ai", "note": f"скачиваю {name}: {ev.get('status', '')}{pct}"})
            except Exception as e:
                await S.broadcast({"type": "alert", "text": f"Не удалось скачать {name}: {e}"})
            await S.broadcast({"type": "activity", "source": "ai", "note": ""})
        asyncio.create_task(pull())
        return {"ok": True}


def _personas(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    @r.get("/personas")
    def personas_list():
        from . import personas, voiceclone, wake
        vdir = DATA_DIR / "voices"
        voices = sorted(p.stem for p in vdir.glob("ru_RU-*.onnx")) + [v["id"] for v in voiceclone.voices()]
        return {"personas": personas.all_personas(), "active": personas.active()["id"], "wake": wake.CFG.get("wake_word"),
                "voices": voices}

    @r.post("/personas")
    async def persona_save(request: Request):
        from . import personas
        d = await request.json()
        if not (d.get("name") or "").strip():
            return JSONResponse({"error": "нужно имя"}, status_code=400)
        p = personas.upsert(d)
        warn = ""
        if p.get("wake") and not await asyncio.to_thread(personas.wake_known, p["wake"]):
            warn = f"Слово «{p['wake']}» модель пробуждения не знает — будить можно будет только «Ренар». Попробуй другое написание."
        if personas.active()["id"] == p["id"]:
            await personas.activate(p["id"])
            await S.broadcast({"type": "prefs"})
        return {**p, "warn": warn}

    @r.delete("/personas/{pid}")
    async def persona_del(pid: str):
        from . import personas
        if personas.active()["id"] == pid:
            await personas.activate("renard")
        return {"ok": personas.delete(pid)}

    @r.post("/personas/{pid}/activate")
    async def persona_activate(pid: str):
        from . import personas
        try:
            res = await personas.activate(pid)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        await S.broadcast({"type": "prefs"})
        return res

    @r.get("/voice/info")
    def voice_info():
        from . import voice
        vdir = DATA_DIR / "voices"
        try:
            import sounddevice as sd
            mics = [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0][:20]
        except Exception:
            mics = []
        return {"voices": sorted(p.stem for p in vdir.glob("ru_RU-*.onnx")) if vdir.exists() else [],
                "downloadable": ["ru_RU-irina-medium", "ru_RU-dmitri-medium", "ru_RU-denis-medium", "ru_RU-ruslan-medium"],
                "other_voices": {k: v for k, v in (voice.CFG.get("tts_voices") or {}).items() if (vdir / f"{v}.onnx").exists()},
                "tts_rate": voice.CFG.get("tts_rate", 1.0), "stt_languages": voice.CFG.get("stt_languages"),
                "tts_voice": voice.CFG.get("tts_voice"), "stt_model": voice.CFG.get("stt_model"),
                "wake": S.status.get("wake", False), "wake_available": S.status.get("wake_available", False),
                "wake_device": getattr(S.wake, "device", ""), "mics": mics, "prefs": prefs.get("voice", {}),
                "wake_log": list(reversed(S.status.get("wake_log", [])))[:15]}

    @r.post("/voice/set")
    async def voice_set(request: Request):
        from . import voice
        d = await request.json()
        if d.get("tts_voice"):
            name = d["tts_voice"]
            if name.startswith("clone:"):
                from . import voiceclone
                if not any(v["id"] == name for v in voiceclone.voices()):
                    return {"ok": False, "error": "нет такого голоса"}
            elif not (DATA_DIR / "voices" / f"{name}.onnx").exists():
                await S.broadcast({"type": "activity", "source": "voice", "note": f"скачиваю голос {name}…"})
                import subprocess
                import sys
                await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "piper.download_voices", "--data-dir",
                                                        str(DATA_DIR / "voices"), name], capture_output=True, timeout=600)
                await S.broadcast({"type": "activity", "source": "voice", "note": ""})
            cur = str(voice.CFG.get("tts_voice") or "")
            if name.startswith("clone:") and cur and not cur.startswith("clone:"):
                voice.CFG["tts_piper"] = cur
                prefs.update({"voice": {"tts_piper": cur}})
            voice.CFG["tts_voice"] = name
            voice.tts.voice = None
            prefs.update({"voice": {"tts_voice": name}})
        if "prefs" in d:
            old_auto = voice.CFG.get("stt_auto_lang", True)
            prefs.update({"voice": d["prefs"]})
            voice.apply_prefs()
            if voice.CFG.get("stt_auto_lang", True) != old_auto:
                await asyncio.to_thread(voice.stt.stop)
        return {"ok": True}

    @r.get("/planner")
    def planner_get():
        from . import planner
        from datetime import date
        return {"tasks": planner.tasks("open")[:50], "done": [t for t in planner.tasks("all") if t.get("done")][-10:],
                "events": planner.events(date.today(), 45), "notes": planner.notes()[:30], "today": planner.today_short()}

    @r.post("/planner/task")
    async def planner_task(request: Request):
        from . import planner
        d = await request.json()
        if not (d.get("text") or "").strip():
            return {"ok": False}
        return {"ok": True, "task": planner.add_task(d["text"], d.get("when", ""))}

    @r.post("/planner/event")
    async def planner_event(request: Request):
        from . import planner
        d = await request.json()
        try:
            return {"ok": True, "event": planner.add_event(d.get("title", ""), d.get("when", ""), d.get("minutes", 60),
                                                           d.get("place", ""), d.get("remind_min", 15))}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    @r.post("/planner/done")
    async def planner_done(request: Request):
        from . import planner
        d = await request.json()
        t = planner.set_done(d.get("id", ""), bool(d.get("done", True)))
        return {"ok": bool(t)}

    @r.post("/planner/delete")
    async def planner_delete(request: Request):
        from . import planner
        d = await request.json()
        kind = d.get("kind") if d.get("kind") in ("tasks", "events", "notes") else "tasks"
        return {"ok": bool(planner.delete(kind, d.get("id", "")))}

    @r.get("/voice/clones")
    def voice_clones():
        from . import voiceclone
        e = voiceclone.engine
        return {"installed": voiceclone.installed(), "voices": voiceclone.voices(), "selected": voice_sel(),
                "engine": {"running": bool(e.proc and e.proc.poll() is None), "last": e.info}}

    def voice_sel():
        from . import voice
        return voice.CFG.get("tts_voice")

    @r.post("/voice/clone/add")
    async def voice_clone_add(request: Request, name: str = "", source: str = "file", consent: int = 0,
                              start: float = 0.0, dur: float = 0.0, text: str = ""):
        from . import voiceclone
        raw = await request.body()
        if len(raw) < 2000:
            return {"ok": False, "error": "пустой файл"}
        if len(raw) > 400 * 1024 * 1024:
            return {"ok": False, "error": "файл больше 400 МБ — вырежи нужный кусок"}
        try:
            return await asyncio.to_thread(voiceclone.add_voice, name, raw, source, text, start, dur or None, bool(consent))
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @r.get("/voicebake")
    def voicebake_info():
        from . import voicebake as VB
        return {"ready": VB.ready(), "jobs": VB.all_jobs(), "running": (VB.JOB or {}).get("name"),
                "can_separate": VB.can_separate()}

    @r.post("/voicebake/upload")
    async def voicebake_upload(request: Request, name: str, fn: str = "rec.webm"):
        from . import voicebake as VB
        raw = await request.body()
        if len(raw) < 5000:
            return {"ok": False, "error": "пустой файл"}
        if len(raw) > 1500 * 1024 * 1024:
            return {"ok": False, "error": "файл больше 1,5 ГБ"}
        return await asyncio.to_thread(VB.add_file, name, fn, raw)

    @r.post("/voicebake/start")
    async def voicebake_start(request: Request):
        from . import voicebake as VB
        d = await request.json()
        if d.get("resume"):
            return await asyncio.to_thread(VB.resume, d.get("name", ""))
        return await asyncio.to_thread(VB.start, d.get("name", ""), None, bool(d.get("consent")), d.get("lang") or "ru",
                                       float(d.get("minutes") or 25))

    @r.post("/voicebake/rebake")
    async def voicebake_rebake(request: Request):
        from . import voicebake as VB
        d = await request.json()
        return await asyncio.to_thread(VB.start_rebake, d.get("name", ""), d.get("steps"))

    @r.post("/voicebake/cancel")
    def voicebake_cancel():
        from . import voicebake as VB
        return VB.cancel()

    @r.post("/voice/clone/delete")
    async def voice_clone_delete(request: Request):
        from . import voice, voiceclone
        d = await request.json()
        res = await asyncio.to_thread(voiceclone.delete_voice, d.get("name", ""))
        if res.get("ok") and voice.CFG.get("tts_voice") == f"clone:{voiceclone.safe_name(d.get('name', ''))}":
            voice.CFG["tts_voice"] = voice.CFG.get("tts_piper", "ru_RU-ruslan-medium")
            prefs.update({"voice": {"tts_voice": voice.CFG["tts_voice"]}})
        return res

    @r.get("/voice/clone/sample")
    def voice_clone_sample(name: str):
        from fastapi.responses import FileResponse, JSONResponse
        from . import voiceclone
        p = voiceclone.ROOT / voiceclone.safe_name(name) / "ref.wav"
        return FileResponse(p, media_type="audio/wav") if p.exists() else JSONResponse({"error": "нет"}, 404)

    @r.post("/voice/hear_test")
    async def voice_hear_test(request: Request):
        """«Как ты меня слышишь»: the recording from the Voice page -> what Whisper heard + level/gain/language."""
        from . import voice
        audio = await request.body()
        if len(audio) < 1000:
            return {"text": "", "error": "пустая запись"}
        r = await asyncio.to_thread(voice.stt.transcribe, audio, None, "test")
        return {k: r.get(k) for k in ("text", "error", "lang", "lang_p", "peak", "gain", "dur", "ms", "load_ms", "dropped", "silent")}


def _widgets(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    @r.get("/widgets/weather")
    async def w_weather(city: str = ""):
        from .tools.extra import weather_data
        try:
            return await weather_data(city or prefs.get("home_city") or (SETTINGS.get("home_city") or "London"), 3)
        except Exception as e:
            return {"error": str(e)}


def _own_pixel_characters(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    PIX = AVATARS / "pixel"
    PIX.mkdir(exist_ok=True)

    def _sheet_meta(name: str) -> dict:
        png = PIX / (Path(name).stem + ".png")
        if not png.exists():
            return {"error": "нет такого спрайт-листа"}
        meta = {"frame_w": 32, "frame_h": 32, "fps": 6, "anims": {"idle": {"row": 0, "frames": 1}}}
        js = png.with_suffix(".json")
        if js.exists():
            meta.update(json.loads(js.read_text(encoding="utf-8")))
        return {**meta, "name": png.stem, "file": png.name, "mtime": int(png.stat().st_mtime)}

    @r.get("/pixel_sheets")
    def pixel_sheets():
        return {"sheets": [_sheet_meta(p.name) for p in sorted(PIX.glob("*.png"))]}

    @r.get("/pixel_sheets/{name}")
    def pixel_sheet(name: str):
        return _sheet_meta(name)

    @r.post("/pixel_sheets/upload")
    async def pixel_upload(request: Request, name: str, mode: str = "sheet"):
        stem = re.sub(r"[^\w\-]+", "_", Path(name).stem)[:40] or "sheet"
        data = await request.body()
        if mode == "single":
            from PIL import Image, ImageSequence
            import io
            from .pixelize import single
            try:
                src = Image.open(io.BytesIO(data))
                frames = [f.convert("RGBA") for f in ImageSequence.Iterator(src)][:16]
                dur = max(40, int(src.info.get("duration", 160) or 160))
            except Exception:
                return JSONResponse({"error": "не картинка (нужен PNG / GIF / WebP / JPG)"}, 400)
            box = None
            for f in frames:
                b = f.getchannel("A").point(lambda a: 255 if a > 40 else 0).getbbox()
                if b:
                    box = b if not box else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
            frames = [f.crop(box) for f in frames] if box else frames
            small = await asyncio.to_thread(lambda: [single(f) for f in frames])
            fw, fh = max(s.width for s in small), max(s.height for s in small)
            sheet = Image.new("RGBA", (fw * len(small), fh))
            for i, s in enumerate(small):
                sheet.paste(s, (i * fw + (fw - s.width) // 2, fh - s.height))
            sheet.save(PIX / f"{stem}.png")
            n = len(small)
            (PIX / f"{stem}.json").write_text(json.dumps({
                "frame_w": fw, "frame_h": fh, "fps": max(1, round(1000 / dur)) if n > 1 else 1, "seat": fh, "single": True,
                "title": Path(name).stem[:24], "anims": {"idle": {"row": 0, "frames": n}}}, ensure_ascii=False), encoding="utf-8")
            await S.broadcast({"type": "prefs"})
            return _sheet_meta(stem)
        if not data.startswith(b"\x89PNG"):
            return JSONResponse({"error": "нужен PNG"}, 400)
        (PIX / f"{stem}.png").write_bytes(data)
        from PIL import Image
        import io
        w, h = Image.open(io.BytesIO(data)).size
        js = PIX / f"{stem}.json"
        if not js.exists():
            fh = h if h <= 64 else (32 if h % 32 == 0 else h)
            js.write_text(json.dumps({"frame_w": fh, "frame_h": fh, "fps": 6, "seat": fh,
                                      "anims": {"idle": {"row": 0, "frames": max(1, w // fh)}}}, ensure_ascii=False), encoding="utf-8")
        return _sheet_meta(stem)

    @r.post("/pixel_sheets/bake")
    async def pixel_bake_ep():
        """The pixel chibi of the current 3D model (agent/pixel_bake.py), then it becomes the pixel companion."""
        from . import pixel_bake
        try:
            meta = await asyncio.to_thread(pixel_bake.bake)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        prefs.update({"companion": {"pixel_sheet": meta["name"]}})
        await S.broadcast({"type": "prefs"})
        return {"ok": True, **_sheet_meta(meta["name"])}

    ALIB = AVATARS.parent / "animations" / "library"

    def _acat() -> list:
        p = ALIB / "catalog.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []

    @r.delete("/anims/{aid:path}")
    async def anim_delete(aid: str):
        from .tools.files import delete_to_recycle_bin
        cat = _acat()
        it = next((x for x in cat if x["id"] == aid), None)
        if not it:
            return {"ok": False, "error": "нет такой анимации"}
        f = ALIB / it["file"].removeprefix("/anims/")
        if f.exists():
            await asyncio.to_thread(delete_to_recycle_bin, str(f))
        (ALIB / "catalog.json").write_text(json.dumps([x for x in cat if x["id"] != aid], ensure_ascii=False, indent=0), encoding="utf-8")
        rm = ALIB / "removed.json"
        gone = json.loads(rm.read_text(encoding="utf-8")) if rm.exists() else []
        rm.write_text(json.dumps(sorted(set(gone) | {aid}), ensure_ascii=False), encoding="utf-8")
        return {"ok": True}

    @r.post("/anims/upload")
    async def anim_upload(request: Request, name: str, cat: str = "misc"):
        if not name.lower().endswith(".fbx"):
            return JSONResponse({"error": "нужен .fbx (скелет Mixamo)"}, 400)
        cat = re.sub(r"[^\w]+", "", cat) or "misc"
        stem = re.sub(r"[^\w\- .']+", "", Path(name).stem).strip()[:60] or "anim"
        data = await request.body()
        dst = ALIB / "user" / cat / f"{stem}.fbx"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        items = [x for x in _acat() if x["id"] != f"user:{stem}"]
        items.append({"id": f"user:{stem}", "name": stem, "cat": cat, "src": "user",
                      "loop": cat in ("idle", "walk", "dance", "music"), "file": "/anims/" + dst.relative_to(ALIB).as_posix()})
        (ALIB / "catalog.json").write_text(json.dumps(items, ensure_ascii=False, indent=0), encoding="utf-8")
        return {"ok": True, "id": f"user:{stem}"}

    @r.delete("/pixel_sheets/{name}")
    async def pixel_delete(name: str):
        """a pixel chibi (baked or uploaded) -> the Recycle Bin (png, json and its raw 3D shots)"""
        from .tools.files import delete_to_recycle_bin
        stem = Path(name).stem
        gone = []
        for p in (PIX / f"{stem}.png", PIX / f"{stem}.json", PIX / "_raw" / stem):
            if p.exists():
                delete_to_recycle_bin(str(p)); gone.append(p.name)
        if (prefs.get("companion", {}) or {}).get("pixel_sheet") == stem:
            prefs.update({"companion": {"pixel_sheet": ""}})
        await S.broadcast({"type": "prefs"})
        return {"ok": bool(gone), "removed": gone}

    @r.post("/pixel_sheets/{name}/meta")
    async def pixel_meta(name: str, request: Request):
        js = PIX / (Path(name).stem + ".json")
        d = await request.json()
        keep = json.loads(js.read_text(encoding="utf-8")) if js.exists() else {}
        keep.update({k: d[k] for k in ("frame_w", "frame_h", "fps", "seat", "anims") if k in d})
        js.write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
        await S.broadcast({"type": "prefs"})
        return _sheet_meta(name)

    @r.get("/widgets/activity")
    def w_activity():
        from .activity import today_top
        apps = today_top(7)
        return {"apps": apps, "total": sum(a["sec"] for a in apps if a["app"] != "Renard")}

    @r.get("/widgets/media")
    async def w_media():
        from .media_now import now_playing
        return await now_playing()

    @r.post("/widgets/media/{action}")
    async def w_media_ctl(action: str):
        from .media_now import control
        return {"ok": await control(action)}

    @r.get("/widgets/volume")
    def w_volume():
        from .winput import get_volume
        try:
            return {"volume": get_volume()}
        except Exception as e:
            return {"error": str(e)}


def _avatars(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    @r.get("/avatars")
    def avatars():
        from .avatars import listing
        return {"avatars": listing()}

    @r.post("/avatars/upload")
    async def avatar_upload(request: Request, name: str = "avatar.vrm"):
        from .avatars import IMG2D
        safe = re.sub(r'[\\/:*?"<>|]+', "_", Path(name).name)
        ext = Path(safe).suffix.lower()
        if ext not in (".vrm", ".glb") and ext not in IMG2D:
            return JSONResponse({"error": "нужен .vrm (3D), .glb (робот без скелета) или картинка .png/.gif/.webp/.jpg/.svg (2D)"}, 400)
        (AVATARS / safe).write_bytes(await request.body())
        return {"ok": True, "name": safe, "kind": {".vrm": "vrm", ".glb": "robot"}.get(ext, "2d")}

    @r.post("/avatars/thumb")
    async def avatar_thumb(request: Request, name: str):
        """Snapshot rendered by the UI for VRM files without an embedded thumbnail."""
        from .avatars import thumb_path
        body = await request.body()
        if body[:8] == b"\x89PNG\r\n\x1a\n" and len(body) < 5_000_000:
            thumb_path(name).write_bytes(body)
        return {"ok": True}

    @r.delete("/avatars/{name}")
    def avatar_delete(name: str):
        from .tools.files import delete_to_recycle_bin
        p = AVATARS / Path(name).name
        return {"result": delete_to_recycle_bin(str(p)) if p.exists() else "нет файла"}


def _server(r: APIRouter, S) -> None:
    """Routes of this part of the UI (split out of build)."""
    @r.get("/health")
    async def health_get():
        """«Здоровье Renard»: every part alive?, errors of the last day, where the answer time goes, last test runs."""
        from . import health
        return await health.check(S)

    @r.post("/restart")
    async def restart():
        import os
        import subprocess
        import sys
        exe = Path(sys.executable)
        pyw = exe.with_name("pythonw.exe")
        subprocess.Popen(f'cmd /c timeout /t 2 /nobreak >nul & "{pyw if pyw.exists() else exe}" -m agent',
                         cwd=str(ROOT), creationflags=0x08000000)
        asyncio.get_running_loop().call_later(0.5, lambda: os._exit(0))
        return {"ok": True}
