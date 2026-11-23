"""Bridge to coding agents installed on the PC (Astra plugin «AI coding agents»): Claude Code, Codex CLI, Gemini CLI,
aider (aider can run fully local on Ollama). Renard hands over a programming task in a folder, the agent works in the
background, Renard reports when it is done (what changed, the end of the log). Starting one needs his «да»."""
import asyncio
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from . import S, tool
from ..config import DATA_DIR
from ..logs import quiet

LOGS = DATA_DIR / "code_agents"
JOBS: dict[str, dict] = {}
PENDING: dict[str, dict] = {}
NAMES = {"claude": "Claude Code", "codex": "Codex CLI", "gemini": "Gemini CLI", "aider": "aider (локально, Ollama)"}
FORBIDDEN = re.compile(r"(?i)^[a-z]:\\?$|\\windows(\\|$)|\\program files|\\programdata|\\appdata\\(local|roaming)\\microsoft")


def _exe(name: str) -> str | None:
    p = shutil.which(name)
    if not p and name == "claude":
        cand = Path(os.path.expandvars(r"%USERPROFILE%\.local\bin\claude.exe"))
        p = str(cand) if cand.exists() else None
    return p


def installed() -> dict[str, str]:
    return {k: p for k in NAMES if (p := _exe(k))}


def _cmd(agent: str, exe: str, task: str) -> tuple[list[str], dict]:
    env = {}
    if agent == "claude":
        return [exe, "-p", task, "--permission-mode", "acceptEdits"], env
    if agent == "codex":
        return [exe, "exec", "--full-auto", task], env
    if agent == "gemini":
        return [exe, "-p", task, "--approval-mode", "auto_edit"], env
    from ..config import SETTINGS
    model = (SETTINGS.get("modes", {}).get("medium") or {}).get("model") or "qwen2.5-coder:14b"
    env["OLLAMA_API_BASE"] = SETTINGS.get("ollama_url", "http://127.0.0.1:11434")
    return [exe, "--model", f"ollama_chat/{model}", "--yes-always", "--no-auto-commits", "--no-show-model-warnings",
            "--no-pretty", "--message", task], env


def _folder(folder: str, ctx: dict | None) -> Path | None:
    f = (folder or "").strip().strip('"')
    if not f and ctx and ctx.get("agent") and getattr(ctx["agent"], "current_project", ""):
        try:
            from .. import projects
            pr = projects.get(ctx["agent"].current_project) or {}
            f = (pr.get("folders") or [""])[0]
        except Exception:
            f = ""
    if not f:
        return None
    p = Path(os.path.expandvars(os.path.expanduser(f)))
    return p if p.is_dir() else None


async def _diffstat(folder: Path) -> str:
    if not (folder / ".git").exists():
        return ""
    try:
        pr = await asyncio.create_subprocess_exec("git", "-C", str(folder), "status", "--short", stdout=asyncio.subprocess.PIPE,
                                                  stderr=asyncio.subprocess.DEVNULL, creationflags=0x08000000)
        out = (await asyncio.wait_for(pr.communicate(), 20))[0].decode("utf-8", "replace").strip()
        lines = out.splitlines()
        return ("Изменённые файлы:\n" + "\n".join(lines[:25]) + (f"\n… и ещё {len(lines) - 25}" if len(lines) > 25 else "")) if lines else "Файлы не изменены."
    except Exception:
        return ""


async def _run(job: dict, agent_obj):
    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"{job['id']}.log"
    args, env = _cmd(job["agent"], job["exe"], job["task"])
    t0 = time.time()
    with open(log, "wb") as f:
        f.write(f"$ {job['agent']} в {job['folder']}\nЗадача: {job['task']}\n\n".encode("utf-8"))
        try:
            pr = await asyncio.create_subprocess_exec(*args, cwd=job["folder"], stdout=asyncio.subprocess.PIPE,
                                                      stderr=asyncio.subprocess.STDOUT, stdin=asyncio.subprocess.DEVNULL,
                                                      env={**os.environ, **env, "PYTHONIOENCODING": "utf-8"},
                                                      creationflags=0x08000000)
            job["pid"] = pr.pid
            while True:
                try:
                    line = await asyncio.wait_for(pr.stdout.readline(), timeout=max(1.0, job["timeout"] - (time.time() - t0)))
                except asyncio.TimeoutError:
                    pr.kill(); job["status"] = "timeout"; break
                if not line:
                    break
                f.write(line); f.flush()
                job["tail"] = (job.get("tail", "") + line.decode("utf-8", "replace"))[-4000:]
                if job.get("stop"):
                    pr.kill(); job["status"] = "stopped"; break
            await pr.wait()
            if job["status"] == "running":
                job["status"] = "done" if pr.returncode == 0 else f"error {pr.returncode}"
        except Exception as e:
            job["status"] = f"error: {e}"
            f.write(f"\n{e}\n".encode("utf-8"))
    job["seconds"] = int(time.time() - t0)
    job["changes"] = await _diffstat(Path(job["folder"]))
    text = (f"{NAMES[job['agent']]} {'закончил' if job['status'] == 'done' else job['status']} за {job['seconds'] // 60} мин "
            f"{job['seconds'] % 60} с: «{job['task'][:80]}».\n{job['changes']}\n\nКонец лога:\n{job.get('tail', '')[-1200:]}")
    job["result"] = text
    try:
        from .system import toast
        toast("Renard", f"{NAMES[job['agent']]}: {job['status']}")
        if agent_obj is not None:
            await agent_obj.command_runner.broadcast({"type": "task", "name": NAMES[job["agent"]], "kind": "reminder", "text": text})
    except Exception:
        quiet()


@tool("code_agent",
      "Передать задачу по программированию агенту-программисту на ПК (Claude Code, Codex, Gemini CLI или aider на "
      "локальной модели) — он сам правит файлы проекта в папке и работает в фоне. Для больших задач в коде проекта: "
      "«пусть Claude Code допишет…», «поручи кодексу…», «сделай рефакторинг проекта X». task — подробная задача; "
      "folder — папка проекта (пусто = папка текущего проекта); agent: claude | codex | gemini | aider | auto. "
      "Запуск только после «да» пользователя.",
      {"task": S, "folder": S, "agent": S}, ["task"])
def code_agent(task: str, folder: str = "", agent: str = "auto", ctx: dict | None = None) -> str:
    have = installed()
    if not have:
        return ("На ПК нет агентов-программистов. Можно поставить: Claude Code (claude.ai/code), Codex CLI "
                "(npm i -g @openai/codex) или aider (pip install aider-chat — работает на локальной модели).")
    a = (agent or "auto").lower().strip()
    a = {"клод": "claude", "claude code": "claude", "кодекс": "codex", "айдер": "aider", "джемини": "gemini"}.get(a, a)
    if a not in have:
        a = next((k for k in ("claude", "codex", "gemini", "aider") if k in have), "")
    path = _folder(folder, ctx)
    if not path:
        return f"Не нашёл папку «{folder}». Скажи полный путь к папке проекта (или открой проект в Renard)."
    if FORBIDDEN.search(str(path)):
        return f"В папку {path} агента-программиста не пускаю — это системная папка или корень диска."
    if a == "aider":
        from ..llm import gaming
        if gaming():
            return "Сейчас идёт игра — aider на локальной модели займёт видеокарту. Запусти позже или выбери Claude Code."
    tok = uuid.uuid4().hex[:8]
    PENDING[tok] = {"agent": a, "exe": have[a], "folder": str(path), "task": task.strip()}
    if ctx and ctx.get("agent") is not None:
        ctx["agent"].pending = {"name": "code_agent_run", "args": {"token": tok}}
    others = ", ".join(NAMES[k] for k in have if k != a)
    return (f"Запущу {NAMES[a]} в папке {path} с задачей: «{task.strip()[:300]}». Он сможет менять файлы только в этой "
            f"папке. Спроси пользователя «да?»" + (f" Другие агенты на ПК: {others}." if others else ""))


@tool("code_agent_run", "Запустить агента-программиста, на которого пользователь ответил «да» (token из code_agent)",
      {"token": S}, ["token"])
async def code_agent_run(token: str, ctx: dict | None = None) -> str:
    p = PENDING.pop((token or "").strip(), None)
    if not p:
        return "Нет такого ожидающего запуска."
    jid = uuid.uuid4().hex[:6]
    job = {"id": jid, **p, "status": "running", "started": time.time(), "timeout": 45 * 60, "tail": ""}
    JOBS[jid] = job
    asyncio.create_task(_run(job, (ctx or {}).get("agent")))
    return (f"Запустил {NAMES[p['agent']]} (задача {jid}) в {p['folder']}. Работает в фоне — когда закончит, пришлю "
            f"уведомление с тем, что изменилось. Спроси «как там код?» — покажу прогресс.")


@tool("code_agent_status", "Как идёт работа агента-программиста: прогресс / результат; action: status | stop",
      {"job": S, "action": S})
def code_agent_status(job: str = "", action: str = "status") -> str:
    if not JOBS:
        return "Агенты-программисты сейчас ничего не делали."
    j = JOBS.get(job) or list(JOBS.values())[-1]
    if (action or "").lower() == "stop" and j["status"] == "running":
        j["stop"] = True
        return f"Останавливаю {NAMES[j['agent']]} (задача {j['id']})."
    if j["status"] == "running":
        mins = int((time.time() - j["started"]) // 60)
        return f"{NAMES[j['agent']]} работает уже {mins} мин над «{j['task'][:80]}». Последнее в логе:\n{j['tail'][-800:]}"
    return j.get("result") or j["status"]
