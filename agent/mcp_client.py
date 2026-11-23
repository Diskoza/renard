"""Connectors = MCP servers (Model Context Protocol). Add GitHub, Supabase, YouTube… without touching Renard code.

data/mcp.json: {"servers": {"github": {"command": "npx", "args": [...], "env": {...}, "enabled": true}}}
Each enabled server runs as a child process (stdio). The agent sees only a short index of servers in the prompt and
uses two tools: mcp_tools(server) -> list of its tools, mcp_call(server, tool, args) -> result.
"""
import asyncio
import json
import os
import shutil

from .config import DATA_DIR

PATH = DATA_DIR / "mcp.json"

PRESETS = [
    {"id": "github", "title": "GitHub", "desc": "репозитории, issues, PR, поиск кода",
     "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
     "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": ""}, "help": "Токен: github.com → Settings → Developer settings → Fine-grained tokens"},
    {"id": "supabase", "title": "Supabase", "desc": "таблицы, SQL, проекты (только чтение по умолчанию)",
     "command": "npx", "args": ["-y", "@supabase/mcp-server-supabase@latest", "--read-only"],
     "env": {"SUPABASE_ACCESS_TOKEN": ""}, "help": "Токен: supabase.com/dashboard/account/tokens"},
    {"id": "fetch", "title": "Веб-страницы", "desc": "читать любые страницы в markdown",
     "command": "uvx", "args": ["mcp-server-fetch"], "env": {}},
    {"id": "youtube", "title": "YouTube", "desc": "субтитры и описание видео по ссылке",
     "command": "npx", "args": ["-y", "@anaisbetts/mcp-youtube"], "env": {}, "help": "нужен yt-dlp в PATH"},
    {"id": "filesystem", "title": "Папка", "desc": "файлы в выбранной папке (отдельно от Renard)",
     "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", str(DATA_DIR.home())], "env": {}},
    {"id": "postgres", "title": "PostgreSQL", "desc": "запросы к базе (только чтение)",
     "command": "npx", "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://user:pass@localhost/db"], "env": {}},
    {"id": "gmail", "title": "Gmail", "desc": "почта (нужна настройка OAuth в Google Cloud)",
     "command": "npx", "args": ["-y", "@gongrzhe/server-gmail-autoauth-mcp"], "env": {},
     "help": "Первый запуск откроет вход Google; нужен gcp-oauth.keys.json — см. README пакета"},
    {"id": "browser", "title": "Браузер Renard (сайты со входом)", "desc": "свой профиль Chrome: ты один раз входишь на сайт "
     "(Moodle, YummyAnime, eduVULCAN, TikTok, Roblox, CurseForge…), дальше агент читает его сам",
     "command": "npx", "args": ["-y", "@playwright/mcp@latest", "--browser", "chrome", "--user-data-dir",
                                str(DATA_DIR / "browser_profile")], "env": {}},
    {"id": "devtools", "title": "Chrome DevTools (F12)", "desc": "консоль, сеть, ошибки и скорость страниц — как панель F12",
     "command": "npx", "args": ["-y", "chrome-devtools-mcp@latest", "--userDataDir", str(DATA_DIR / "devtools_profile")], "env": {}},
    {"id": "notion", "title": "Notion", "desc": "страницы и базы Notion",
     "command": "npx", "args": ["-y", "@notionhq/notion-mcp-server"], "env": {}, "needs": ["accounts/notion.json"],
     "help": "notion.so/profile/integrations → New integration → токен в data\\accounts\\notion.json как NOTION_TOKEN"},
    {"id": "calendar", "title": "Google Календарь", "desc": "события всех твоих Google-аккаунтов",
     "command": "npx", "args": ["-y", "@cocal/google-calendar-mcp"],
     "env": {"GOOGLE_OAUTH_CREDENTIALS": str(DATA_DIR / "accounts" / "google_client.json")},
     "needs": ["accounts/google_client.json"], "help": "OAuth-клиент Desktop app из Google Cloud → data\\accounts\\google_client.json"},
]


def gmail_spec(account: str) -> dict:
    """One Gmail server per Google account (gmail_main, gmail_school…): the same OAuth client, its own token file."""
    acc = DATA_DIR / "accounts"
    return {"command": "npx", "args": ["-y", "@gongrzhe/server-gmail-autoauth-mcp"], "enabled": True,
            "env": {"GMAIL_OAUTH_PATH": str(acc / "google_client.json"),
                    "GMAIL_CREDENTIALS_PATH": str(acc / f"gmail_{account}_token.json")},
            "needs": ["accounts/google_client.json"]}


def account_env(name: str) -> dict:
    """Keys live only in data/accounts/<server>.json ({"GITHUB_PERSONAL_ACCESS_TOKEN": "..."}), never in mcp.json / chat."""
    import json as _json
    from .config import DATA_DIR as _D
    p = _D / "accounts" / f"{name}.json"
    try:
        d = _json.loads(p.read_text(encoding="utf-8"))
        return {k: str(v) for k, v in d.items() if isinstance(k, str) and k.isupper() and v}
    except Exception:
        return {}


def load_cfg() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"servers": {}}


def save_cfg(cfg: dict):
    PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")


def runtimes() -> dict:
    return {k: bool(shutil.which(k)) for k in ("node", "npx", "uv", "uvx", "python", "docker", "git")}


class Server:
    def __init__(self, name: str, spec: dict):
        self.name, self.spec = name, spec
        self.tools: list[dict] = []
        self.status, self.error = "stopped", ""
        self.task: asyncio.Task | None = None
        self.queue: asyncio.Queue = asyncio.Queue()

    async def start(self):
        if self.task and not self.task.done():
            return
        self.status, self.error = "starting", ""
        self.task = asyncio.create_task(self._run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except BaseException:
                pass
        self.status = "stopped"

    async def _run(self):
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
        cmd = shutil.which(self.spec["command"]) or self.spec["command"]
        env = {**os.environ, **{k: v for k, v in (self.spec.get("env") or {}).items() if v}, **account_env(self.name)}
        params = StdioServerParameters(command=cmd, args=self.spec.get("args", []), env=env)
        errlog = open(DATA_DIR / f"mcp_{self.name}.log", "a", encoding="utf-8")
        try:
            async with stdio_client(params, errlog=errlog) as (r, w):
                async with ClientSession(r, w) as s:
                    await asyncio.wait_for(s.initialize(), 120)
                    res = await s.list_tools()
                    self.tools = [{"name": t.name, "description": (t.description or "")[:300],
                                   "schema": getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}}
                                  for t in res.tools]
                    self.status = "ready"
                    while True:
                        tool, args, fut = await self.queue.get()
                        try:
                            r_ = await asyncio.wait_for(s.call_tool(tool, args), 180)
                            parts = []
                            for c in r_.content:
                                parts.append(getattr(c, "text", None) or f"[{getattr(c, 'type', 'data')}]")
                            err = getattr(r_, "is_error", None) or getattr(r_, "isError", False)
                            fut.set_result(("ОШИБКА: " if err else "") + "\n".join(parts))
                        except Exception as e:
                            fut.set_result(f"Ошибка вызова {tool}: {type(e).__name__}: {e}")
        except asyncio.CancelledError:
            raise
        except BaseException as e:
            while getattr(e, "exceptions", None):
                e = e.exceptions[0]
            self.status, self.error = "error", f"{type(e).__name__}: {e}"[:500]
            import traceback
            errlog.write(traceback.format_exc())
        finally:
            errlog.close()
            if self.status != "error":
                self.status = "stopped"

    async def call(self, tool: str, args: dict) -> str:
        if self.status != "ready":
            return f"Коннектор {self.name} не готов ({self.status}{': ' + self.error if self.error else ''})."
        fut = asyncio.get_running_loop().create_future()
        await self.queue.put((tool, args or {}, fut))
        return await fut


class Hub:
    def __init__(self):
        self.servers: dict[str, Server] = {}

    async def start_all(self):
        for name, spec in load_cfg().get("servers", {}).items():
            if spec.get("enabled", True):
                await self.restart(name)

    async def restart(self, name: str):
        spec = load_cfg().get("servers", {}).get(name)
        if name in self.servers:
            await self.servers[name].stop()
        if not spec or not spec.get("enabled", True):
            self.servers.pop(name, None)
            return
        self.servers[name] = Server(name, spec)
        missing = [f for f in spec.get("needs", []) if not (DATA_DIR / f).exists()]
        if missing:
            self.servers[name].status = "needs_key"
            self.servers[name].error = "нет файла " + ", ".join("data\\" + f.replace("/", "\\") for f in missing)
            return
        await self.servers[name].start()

    def status(self) -> list[dict]:
        cfg = load_cfg().get("servers", {})
        out = []
        for name, spec in cfg.items():
            s = self.servers.get(name)
            out.append({"name": name, "enabled": spec.get("enabled", True), "command": spec.get("command"),
                        "args": spec.get("args", []), "env_keys": list((spec.get("env") or {}).keys()),
                        "status": s.status if s else "stopped", "error": s.error if s else "",
                        "tools": [t["name"] for t in (s.tools if s else [])]})
        return out

    def prompt_index(self) -> str:
        ready = [s for s in self.servers.values() if s.status == "ready" and s.tools]
        if not ready:
            return ""
        lines = ["Подключённые сервисы (коннекторы MCP). Список их инструментов — mcp_tools(server), вызов — "
                 "mcp_call(server, tool, args):"]
        for s in ready:
            names = ", ".join(t["name"] for t in s.tools[:12])
            lines.append(f"- {s.name}: {names}{'…' if len(s.tools) > 12 else ''}")
        return "\n".join(lines)


HUB = Hub()
