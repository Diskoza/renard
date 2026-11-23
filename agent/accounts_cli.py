"""Connect his accounts one by one (keys only in data/accounts, logins only in the service's own window).

  python -m agent.accounts_cli status               what is connected / what is missing
  python -m agent.accounts_cli gmail main           sign in to a Google account for mail (main, school, work…)
  python -m agent.accounts_cli calendar             sign in to Google Calendar (all accounts can be added there)
  python -m agent.accounts_cli token github         ask for a token in a hidden prompt and save it to data/accounts
"""
import getpass
import json
import os
import subprocess
import sys

from .config import DATA_DIR
from . import mcp_client as M

ACC = DATA_DIR / "accounts"
TOKENS = {"github": "GITHUB_PERSONAL_ACCESS_TOKEN", "supabase": "SUPABASE_ACCESS_TOKEN", "notion": "NOTION_TOKEN",
          "openrouter": "API_KEY"}


def status():
    cfg = M.load_cfg().get("servers", {})
    print("Коннекторы Renard:")
    for name, spec in cfg.items():
        miss = [f for f in spec.get("needs", []) if not (DATA_DIR / f).exists()]
        print(f"  {'✓' if not miss else '·'} {name:12} {'готов' if not miss else 'нужен ' + ', '.join(miss)}")


def save_token(service: str):
    key = TOKENS.get(service)
    if not key:
        print("Токены: " + ", ".join(TOKENS)); return
    tok = getpass.getpass(f"Вставь токен {service} (не отображается) и нажми Enter: ").strip()
    if not tok:
        print("Пусто — ничего не сохранил."); return
    ACC.mkdir(parents=True, exist_ok=True)
    data = {key: tok}
    if service == "notion":
        data["OPENAPI_MCP_HEADERS"] = json.dumps({"Authorization": f"Bearer {tok}", "Notion-Version": "2022-06-28"})
    (ACC / f"{service}.json").write_text(json.dumps(data), encoding="utf-8")
    print(f"Сохранил в data\\accounts\\{service}.json. Перезапусти коннектор {service} в «Плагины → Коннекторы».")


def gmail(account: str):
    if not (ACC / "google_client.json").exists():
        print("Сначала положи OAuth-клиент Google в data\\accounts\\google_client.json (шаг 2 инструкции)."); return
    spec = M.gmail_spec(account)
    env = {**os.environ, **spec["env"]}
    print(f"Откроется окно входа Google — войди в аккаунт для «{account}» и разреши доступ к почте…")
    subprocess.run(["npx.cmd", "-y", "@gongrzhe/server-gmail-autoauth-mcp", "auth"], env=env)
    cfg = M.load_cfg()
    cfg.setdefault("servers", {})[f"gmail_{account}"] = spec
    M.save_cfg(cfg)
    print(f"Готово: коннектор gmail_{account}. Перезапусти Renard или нажми «перезапустить» у него.")


def calendar():
    if not (ACC / "google_client.json").exists():
        print("Сначала положи OAuth-клиент Google в data\\accounts\\google_client.json."); return
    env = {**os.environ, "GOOGLE_OAUTH_CREDENTIALS": str(ACC / "google_client.json")}
    subprocess.run(["npx.cmd", "-y", "@cocal/google-calendar-mcp", "auth"], env=env)
    print("Готово. Ещё аккаунт — запусти ту же команду снова и войди в другой.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    a = sys.argv[1:] or ["status"]
    {"status": lambda: status(), "gmail": lambda: gmail(a[1] if len(a) > 1 else "main"), "calendar": lambda: calendar(),
     "token": lambda: save_token(a[1] if len(a) > 1 else "")}.get(a[0], lambda: print(__doc__))()
