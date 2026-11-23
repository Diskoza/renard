import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
MEMORY_DIR = DATA_DIR / "memory"
WEB_DIR = ROOT / "web"

DATA_DIR.mkdir(exist_ok=True)
MEMORY_DIR.mkdir(exist_ok=True)


def load_json(name: str) -> dict:
    p = CONFIG_DIR / name
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


SETTINGS = load_json("settings.json")
APPS = load_json("apps.json")
RADIO = load_json("radio.json")
