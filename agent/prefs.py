"""User preferences changed from the UI (data/prefs.json). config/settings.json stays the base config."""
import copy
import json
import threading

from .config import DATA_DIR

PATH = DATA_DIR / "prefs.json"
DEFAULTS = {
    "user_name": "",
    "ui": {
        "accent": "#D97757",
        "background": "smoke",
        "bg_colors": ["#0F0E14", "#221D40", "#3A2230"],
        "bg_speed": 1.0,
        "glass": True,
        "animations": True,
        "corner_fox": True,
        "orb": {"particles": 1800, "size": 1.0, "speed": 1.0, "rings": True, "glow": 1.0, "style": "sphere"},
    },
    "voice": {"wake_beep": True, "speak_answers": False, "wake_sensitivity": "high", "followup": True, "followup_s": 6,
              "barge_in": True, "voice_acks": True, "tts_rate": 1.0, "conversation": True, "conversation_idle_s": 120,
              "english_voice": True, "stt_auto_lang": True, "debug_keep": 20},
    "chat": {"permission": "manual", "mode": ""},
    "widgets": {"show": True, "items": ["system", "weather", "media", "activity", "calendar", "tasks", "notes"]},
    "notes": "",
    "music": {"service": "youtube"},
    "companion": {"enabled": False, "kind": "fox2d", "vrm": "", "scale": 1.0, "outline": 0.0, "msaa": True,
                  "desktop": False, "walk": False, "sleep": True, "sleep_after": 300, "bubbles": True, "size": 1.0,
                  "hide_fullscreen": True, "idle_pixel": True, "pixel_after": 25, "perch": "auto",
                  "activities": True, "pixel_size": 1.0},
    "cloud": {"provider": "", "model": "", "permission": "off", "effort": "high"},
    "ai": {},
    "pinned_sessions": [],
    "session_titles": {},
    "session_projects": {},
}
_lock = threading.Lock()


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load() -> dict:
    try:
        return _merge(DEFAULTS, json.loads(PATH.read_text(encoding="utf-8")))
    except Exception:
        return copy.deepcopy(DEFAULTS)


def update(patch: dict) -> dict:
    with _lock:
        cur = load()
        new = _merge(cur, patch)
        PATH.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
        return new


def get(path: str, default=None):
    cur = load()
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur
