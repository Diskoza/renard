"""Skills in the agentskills.io format (SKILL.md + YAML frontmatter), compatible with Hermes Agent and OpenClaw.

skills/<name>/SKILL.md            ← installed / own skills (progressive disclosure: only name+description go to the prompt)
data/skill-cache/<source>/        ← partial git clones of skill repos (blob-less + sparse checkout: only what you install)

CLI:  python -m agent.skills list
      python -m agent.skills search <query> [--source hermes|openclaw]
      python -m agent.skills install hermes:arxiv | openclaw:<owner>/<name> | github:<owner>/<repo>/<path>
      python -m agent.skills remove <name>
"""
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .config import DATA_DIR, ROOT
from .logs import quiet

SKILLS_DIR = ROOT / "skills"
CACHE = DATA_DIR / "skill-cache"
SOURCES = {
    "hermes": {"url": "https://github.com/NousResearch/hermes-agent.git", "roots": ["skills", "optional-skills"]},
}
CLAWHUB = "https://clawhub.ai/api/v1"
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def parse_skill(md: Path) -> dict:
    raw = md.read_text(encoding="utf-8", errors="replace")
    meta, body = {}, raw
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            fm, body = raw[3:end], raw[end + 4:]
            meta = _mini_yaml(fm)
    name = str(meta.get("name") or md.parent.name)
    desc = str(meta.get("description") or "").strip()
    if not desc:
        first = next((l.strip("# ").strip() for l in body.splitlines() if l.strip()), "")
        desc = first[:200]
    return {"name": name, "description": desc, "body": body.strip(), "dir": md.parent, "meta": meta}


def _mini_yaml(text: str) -> dict:
    """Small YAML subset (top-level 'key: value'); uses PyYAML if installed."""
    try:
        import yaml
        d = yaml.safe_load(text)
        return d if isinstance(d, dict) else {}
    except Exception:
        quiet()
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def _disabled() -> set:
    try:
        from .prefs import get
        return set(get("disabled_skills", []) or [])
    except Exception:
        return set()


def installed(include_disabled: bool = False) -> list[dict]:
    SKILLS_DIR.mkdir(exist_ok=True)
    out, off = [], _disabled()
    files = [(md, None) for md in sorted(SKILLS_DIR.glob("*/SKILL.md"))]
    files += [(md, md.parents[2].name) for md in sorted((ROOT / "plugins").glob("*/skills/*/SKILL.md"))]
    for md, plugin in files:
        try:
            s = parse_skill(md)
            src = (md.parent / ".source.json")
            s["source"] = (f"plugin:{plugin}" if plugin else
                           json.loads(src.read_text(encoding="utf-8")).get("source", "local") if src.exists() else "local")
            s["enabled"] = s["name"] not in off
            if s["enabled"] or include_disabled:
                out.append(s)
        except Exception as e:
            print("skill parse error", md, e)
    return out


def save_skill(name: str, description: str, body: str) -> Path:
    """Create or update an own skill (skills/<slug>/SKILL.md) from the UI."""
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "skill"
    d = SKILLS_DIR / slug
    d.mkdir(parents=True, exist_ok=True)
    desc = description.replace("\n", " ").strip()
    (d / "SKILL.md").write_text(f"---\nname: {slug}\ndescription: {desc}\n---\n\n{body.strip()}\n", encoding="utf-8")
    return d / "SKILL.md"


def prompt_index(limit_chars: int = 1800) -> str:
    sk = installed()
    if not sk:
        return ""
    lines = ["Навыки (инструкции под типовые задачи). Если задача подходит — СНАЧАЛА вызови use_skill(name):"]
    for s in sk:
        lines.append(f"- {s['name']}: {s['description'][:160]}")
    return "\n".join(lines)[:limit_chars]


TOOL_MAP_NOTE = ("Примечание Renard: в навыке могут упоминаться инструменты других агентов. Соответствие: "
                 "terminal/shell → run_command (белый список программ), read_file/write_file/search_files → такие же, "
                 "patch → edit_file, web_search/web_extract → web_search/fetch_page. Скрипты навыка лежат в его папке; "
                 "запускай их через run_command с cwd = папка навыка.")


def load(name: str) -> str:
    for s in installed():
        if s["name"].lower() == name.lower() or s["dir"].name.lower() == name.lower():
            files = [str(p.relative_to(s["dir"])) for p in s["dir"].rglob("*")
                     if p.is_file() and p.name not in ("SKILL.md", ".source.json")][:30]
            extra = ("\n\nФайлы навыка (" + str(s["dir"]) + "):\n" + "\n".join("- " + f for f in files)) if files else ""
            return f"# Навык {s['name']}\n{s['body'][:12000]}{extra}\n\n{TOOL_MAP_NOTE}"
    return f"Навык '{name}' не найден. Установлены: {', '.join(x['name'] for x in installed()) or 'нет'}"


def _git(args: list[str], cwd: Path | None = None, timeout: int = 600) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd) if cwd else None, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}: {r.stderr.strip()[:300]}")
    return r.stdout


def sync_source(source: str, max_age_h: float = 24) -> Path:
    if source not in SOURCES:
        raise ValueError(f"Неизвестный источник {source}. Есть: {', '.join(SOURCES)}")
    repo = CACHE / source
    stamp = repo / ".renard_synced"
    if (repo / ".git").exists():
        if stamp.exists() and time.time() - stamp.stat().st_mtime < max_age_h * 3600:
            return repo
        _git(["fetch", "--depth", "1", "origin"], repo)
        _git(["reset", "--hard", "FETCH_HEAD"], repo)
    else:
        CACHE.mkdir(parents=True, exist_ok=True)
        _git(["clone", "--depth", "1", "--filter=blob:none", "--sparse", SOURCES[source]["url"], str(repo)])
    stamp.write_text(str(time.time()))
    return repo


def remote_index(source: str) -> list[str]:
    """Paths of all skill folders in the remote repo (from the file tree only, no downloads)."""
    repo = sync_source(source)
    roots = tuple(r + "/" for r in SOURCES[source]["roots"])
    paths = [p[: -len("/SKILL.md")] for p in _git(["ls-tree", "-r", "--name-only", "HEAD"], repo).splitlines()
             if p.endswith("/SKILL.md") and p.startswith(roots)]
    return sorted(paths)


def clawhub_search(query: str, limit: int = 20) -> list[dict]:
    import httpx
    r = httpx.get(CLAWHUB + "/search", params={"q": query, "limit": limit, "nonSuspiciousOnly": "true"}, timeout=20)
    r.raise_for_status()
    out = []
    for it in r.json().get("results", []):
        sk = (it.get("native") or {}).get("skill") or {}
        out.append({"slug": sk.get("slug") or it.get("install", {}).get("reference", ""), "name": it.get("displayName", ""),
                    "owner": (it.get("native") or {}).get("ownerHandle", ""), "downloads": it.get("downloads", 0),
                    "suspicious": bool(sk.get("isSuspicious")), "summary": (sk.get("summary") or "")[:140]})
    return out


def clawhub_install(slug: str) -> str:
    import io
    import zipfile
    import httpx
    slug = slug.split("/")[-1]
    meta = httpx.get(f"{CLAWHUB}/skills/{slug}", timeout=20)
    if meta.status_code == 200:
        sk = meta.json().get("skill") or meta.json()
        if isinstance(sk, dict) and sk.get("isSuspicious"):
            return f"Навык {slug} помечен ClawHub как подозрительный — не устанавливаю."
    r = httpx.get(f"{CLAWHUB}/download", params={"slug": slug}, timeout=60, follow_redirects=True)
    if r.status_code != 200 or not r.content[:2] == b"PK":
        return f"ClawHub не отдал архив навыка {slug} (HTTP {r.status_code})."
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    md = next((n for n in names if n.endswith("SKILL.md")), None)
    if not md:
        return f"В архиве {slug} нет SKILL.md"
    prefix = md[: -len("SKILL.md")]
    dest = SKILLS_DIR / re.sub(r"[^\w.-]", "-", slug)
    if dest.exists():
        shutil.rmtree(dest)
    for n in names:
        if not n.startswith(prefix) or n.endswith("/"):
            continue
        rel = Path(n[len(prefix):])
        if ".." in rel.parts:
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(z.read(n))
    (dest / ".source.json").write_text(json.dumps({"source": f"openclaw:{slug}", "installed": time.strftime("%Y-%m-%d")}),
                                      encoding="utf-8")
    info = parse_skill(dest / "SKILL.md")
    scripts = [p.name for p in dest.rglob("*") if p.suffix in (".py", ".js", ".sh", ".ps1")]
    warn = f" ⚠ Есть скрипты ({', '.join(scripts[:5])}) — запускаются только через run_command." if scripts else ""
    return f"Установил навык «{info['name']}» из ClawHub (OpenClaw): {info['description'][:150]}{warn}"


def search(query: str, source: str = "hermes", limit: int = 25) -> list[str]:
    if source == "openclaw":
        return [f"{h['slug']} — {h['name']} ({h['downloads']} загрузок){' ⚠' if h['suspicious'] else ''}"
                for h in clawhub_search(query, limit)]
    q = query.lower()
    return [p for p in remote_index(source) if q in p.lower()][:limit]


def install(spec: str) -> str:
    """hermes:<name> | openclaw:<owner>/<name> | github:<owner>/<repo>/<path-to-skill-dir>"""
    if ":" not in spec:
        spec = "hermes:" + spec
    source, ident = spec.split(":", 1)
    ident = ident.strip().strip("/")
    if source == "openclaw":
        return clawhub_install(ident)
    if source == "github":
        owner, repo_name, *rest = ident.split("/")
        SOURCES[f"gh-{owner}-{repo_name}"] = {"url": f"https://github.com/{owner}/{repo_name}.git", "roots": [""]}
        source, path = f"gh-{owner}-{repo_name}", "/".join(rest)
        repo = sync_source(source)
    else:
        repo = sync_source(source)
        cands = [p for p in remote_index(source) if p.endswith("/" + ident) or p == ident]
        if not cands:
            near = search(ident.split("/")[-1], source, 8)
            return f"Навык '{ident}' не найден в {source}." + (f" Похожие: {', '.join(near)}" if near else "")
        path = min(cands, key=len)
    _git(["sparse-checkout", "add", path], repo)
    src_dir = repo / path
    md = src_dir / "SKILL.md"
    if not md.exists():
        return f"В {spec} нет SKILL.md"
    info = parse_skill(md)
    dest = SKILLS_DIR / re.sub(r"[^\w.-]", "-", info["name"])
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src_dir, dest, ignore=shutil.ignore_patterns(".git"))
    (dest / ".source.json").write_text(json.dumps({"source": f"{source}:{path}", "installed": time.strftime("%Y-%m-%d")},
                                                  ensure_ascii=False), encoding="utf-8")
    scripts = [p.name for p in dest.rglob("*") if p.suffix in (".py", ".js", ".sh", ".ps1")]
    warn = f" ⚠ В навыке есть скрипты ({', '.join(scripts[:5])}) — они запускаются только через run_command." if scripts else ""
    return f"Установил навык «{info['name']}» из {source}: {info['description'][:150]}{warn}"


def remove(name: str) -> str:
    for s in installed(True):
        if s["name"].lower() == name.lower() or s["dir"].name.lower() == name.lower():
            from .tools.files import delete_to_recycle_bin
            delete_to_recycle_bin(str(s["dir"]))
            return f"Удалил навык {s['name']}."
    return f"Навык {name} не найден."


def main(argv: list[str]):
    if not argv or argv[0] == "list":
        for s in installed():
            print(f"{s['name']:<28} [{s['source']}] {s['description'][:90]}")
    elif argv[0] == "search":
        src = argv[argv.index("--source") + 1] if "--source" in argv else "hermes"
        for p in search(argv[1], src):
            print(f"{src}:{p}")
    elif argv[0] == "install":
        print(install(argv[1]))
    elif argv[0] == "remove":
        print(remove(argv[1]))
    elif argv[0] == "show":
        print(load(argv[1]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
