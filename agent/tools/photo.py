"""Photo tools: make photos pretty (soft retouch / colour grade), pick the best shots of a series, crop for Instagram,
check a photo, and repaint a part with AI (SDXL inpainting on the GPU: fix a smeared hand, remove a stranger,
replace an object). The math lives in agent/photo.py, the GPU part in agent/photo_ai_worker.py (own venv).
Originals are never changed: results go to <folder>/edited, /best, /crop."""
import json
import os
import subprocess
import threading
import time
from pathlib import Path

from . import tool
from .. import photo as P
from ..config import DATA_DIR

S = {"type": "string"}
N = {"type": "number"}
AI_PY = Path(os.environ.get("USERPROFILE", "")) / "photo-ai" / "venv" / "Scripts" / "python.exe"
AI_MODEL = Path(os.environ.get("USERPROFILE", "")) / ".cache" / "huggingface" / "hub" / "models--diffusers--stable-diffusion-xl-1.0-inpainting-0.1"
JOBS = DATA_DIR / "photo_ai"
BASE = "http://127.0.0.1:8790"


def _targets(path: str) -> list:
    from .files import safe
    out = []
    for part in [x.strip() for x in str(path).replace("\n", ";").split(";") if x.strip()]:
        p = safe(part)
        if p.is_dir():
            out += P.images_in(p)
        elif p.exists():
            out.append(p)
        else:
            raise FileNotFoundError(f"нет такого файла / папки: {p}")
    return out


def mask_path(src: Path) -> Path:
    return src.parent / "edited" / "masks" / f"{src.stem}_mask.png"


@tool("photo_fix",
      "Красиво обработать фото как ретушёр (свет, тени, цвет, шум, резкость) — мягко, без «пережара». path — фото, "
      "несколько через «;» или ПАПКА (все фото в ней). style: natural (по умолчанию) | warm (теплее) | night (ночные с "
      "огнями) | cold | vivid (сочнее) | soft (нежно) | bw (чёрно-белое). strength 0.5 (чуть-чуть) … 1.5 (сильно). "
      "darken: auto (светлые фото сам чуть затемнит) | yes (затемнить) | no. floor: yes — затемнить мягким градиентом "
      "низ кадра (светлый пол / плитка отвлекает). ratio: 4:5 / 9:16 / 1:1 — ещё и обрезать (лица остаются в кадре). "
      "Оригиналы не трогаются: результат в папку edited рядом + сравнение до/после.",
      {"path": S, "style": S, "strength": N, "darken": S, "floor": S, "ratio": S}, ["path"])
def photo_fix(path: str, style: str = "natural", strength: float = 1.0, darken: str = "auto", floor: str = "no",
              ratio: str = "") -> str:
    files = _targets(path)
    if not files:
        return "В этой папке нет фото (jpg / png / heic / webp)."
    lines, shown = [], []
    for f in files[:200]:
        rgb, ex = P.load(f)
        new, did = P.enhance(rgb, style or "natural", float(strength or 1), darken or "auto")
        if str(floor).lower() in ("yes", "да", "1", "true"):
            new = P.floor_fade(new); did.append("пол затемнён градиентом")
        if ratio:
            new, _ = P.crop(new, P.ratio_name(ratio)); did.append(f"обрезка {P.ratio_name(ratio)}")
        dst = P.save(new, P.out_path(f, "edited"), ex)
        if len(files) <= 30:
            cmp = P.compare(rgb, new, dst.parent / "_до_после" / f"{f.stem}.jpg")
            if len(shown) < 3:
                shown.append(cmp)
        lines.append(f"{f.name}: {', '.join(did)}")
    pics = "".join(f"Сохранил до/после: {p}\n" for p in shown)
    head = f"Обработал {len(lines)} фото → {files[0].parent / 'edited'} (оригиналы не тронуты)."
    return pics + head + "\n" + "\n".join(lines[:15]) + ("\n…" if len(lines) > 15 else "") + \
        "\n(Сравнения до/после уже показаны в чате картинками — пути не перечисляй, скажи коротко, что сделано.)"


@tool("photo_best",
      "Выбрать лучшие фото из папки (серии похожих кадров): похожие группирует, из каждой берёт самый резкий (по лицу) "
      "и нормально экспонированный. n — сколько лучших оставить (0 = по одному из каждой серии). Копирует их в папку "
      "best (оригиналы на месте) + _preview.jpg превью.", {"folder": S, "n": N}, ["folder"])
def photo_best(folder: str, n: int = 0) -> str:
    from .files import safe
    d = safe(folder)
    r = P.pick(d, int(n or 0))
    if not r["total"]:
        return "В папке нет фото."
    rows = [f'{x["path"].name}: оценка {x["score"]:.0f}, резкость {x["sharp"]:.0f}{" (лицо)" if x["sharp_face"] else ""}, '
            f'яркость {x["bright"]}' for x in r["best"]]
    worst = sorted(r["all"], key=lambda x: x["score"])[:3]
    return (f'Из {r["total"]} фото — {r["groups"]} разных кадров/серий. Лучшие ({len(r["best"])}) скопировал в {r["dir"]}.\n'
            f'Сохранил превью: {r["dir"] / "_preview.jpg"}\n' + "\n".join(rows) +
            "\nСлабее всего: " + ", ".join(f'{x["path"].name} ({x["score"]:.0f})' for x in worst))


@tool("photo_crop",
      "Обрезать фото под формат так, чтобы лица остались в кадре: ratio 4:5 (лента Instagram, по умолчанию) | 9:16 "
      "(сторис / reels / tiktok) | 1:1 | 16:9 | любое a:b. path — фото, несколько через «;» или папка. Результат в папку crop.",
      {"path": S, "ratio": S}, ["path"])
def photo_crop(path: str, ratio: str = "4:5") -> str:
    files = _targets(path)
    ratio = P.ratio_name(ratio)
    out = []
    for f in files[:200]:
        rgb, ex = P.load(f)
        c, box = P.crop(rgb, ratio)
        dst = P.save(c, P.out_path(f, "crop", "_" + ratio.replace(":", "x")), ex)
        out.append(f"Сохранил {dst}" if len(out) < 3 else f"{f.name} → {dst.name}")
    return f"Обрезал {len(out)} фото под {ratio} → {files[0].parent / 'crop'}\n" + "\n".join(out[:15])


@tool("photo_info",
      "Проверить фото: размер, резкость (смаз?), яркость, пересветы, есть ли лица — чтобы решить, что исправлять.",
      {"path": S}, ["path"])
def photo_info(path: str) -> str:
    f = _targets(path)[0]
    rgb, _ = P.load(f)
    a = P.analyze(rgb)
    verdict = []
    verdict.append("смазано/нерезко" if a["sharp"] < 150 else "резкость средняя" if a["sharp"] < 500 else "резкое")
    verdict.append("тёмное" if a["bright"] < .25 else "светлое" if a["bright"] > .6 else "нормальная яркость")
    if a["clipped"] > 2:
        verdict.append(f"пересвечено {a['clipped']}% кадра")
    return f"{f.name}: {a['w']}x{a['h']}, лиц: {a['faces']}, " + ", ".join(verdict) + f" (оценка {a['score']:.0f}/100)"


@tool("photo_mask",
      "Открыть окно, где пользователь КИСТЬЮ закрашивает место на фото, которое надо перерисовать нейросетью (рука, "
      "лишний человек, предмет). После «Сохранить» вызывай photo_ai с тем же path.", {"path": S}, ["path"])
def photo_mask(path: str) -> str:
    from urllib.parse import quote
    f = _targets(path)[0]
    if _OPENED.get(str(f), 0) < time.time() - 60:
        os.startfile(f"{BASE}/app/photo_mask.html?path={quote(str(f))}")
        _OPENED[str(f)] = time.time()
    return (f"ГОТОВО: окно с фото {f.name} уже открыто у него на экране. Скажи ему: «закрась кистью место, которое "
            "перерисовать (с запасом), нажми «Сохранить» и напиши мне, что там должно быть». Больше ничего не "
            "вызывай; когда он ответит — photo_ai с этим path и prompt по-английски.")


_OPENED: dict = {}


_RUNNING: dict = {}


def _watch(job_id: str, job_file: Path, status_file: Path, title: str):
    """starts the worker when VRAM is free enough, pauses it while he plays, tells him when done"""
    import httpx
    import psutil
    from ..jobwatch import telegram, toast
    from ..llm import gaming
    time.sleep(12)
    try:
        httpx.post(BASE + "/api/unload", timeout=60)
    except Exception:
        pass
    try:
        from .. import voiceclone
        voiceclone.engine.stop()
    except Exception:
        pass
    proc = subprocess.Popen([str(AI_PY), str(Path(__file__).resolve().parent.parent / "photo_ai_worker.py"), str(job_file)],
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                            stdout=open(JOBS / f"{job_id}.log", "w", encoding="utf-8"), stderr=subprocess.STDOUT)
    _RUNNING[job_id] = proc
    paused = False
    while proc.poll() is None:
        try:
            g = gaming()
            if g and not paused:
                psutil.Process(proc.pid).suspend(); paused = True
            elif not g and paused:
                psutil.Process(proc.pid).resume(); paused = False
        except Exception:
            pass
        time.sleep(5)
    _RUNNING.pop(job_id, None)
    try:
        st = json.loads(status_file.read_text(encoding="utf-8"))
    except Exception:
        st = {"state": "error", "error": "воркер упал, смотри лог"}
    if st.get("state") == "done":
        msg = f"Renard: нейросеть перерисовала {title} — {len(st.get('outputs', []))} варианта, сравнение: {st.get('sheet')}"
        toast("Renard — фото готово", f"{title}: варианты в папке edited")
    else:
        msg = f"Renard: перерисовка {title} не получилась: {st.get('error', '?')[:200]}"
        toast("Renard — фото", "перерисовка не получилась")
    telegram(msg)


@tool("photo_ai",
      "Перерисовать ЧАСТЬ фото нейросетью на видеокарте (Stable Diffusion XL): what=fix (исправить смазанную/кривую "
      "руку, лицо, деталь) | remove (убрать лишнего человека / предмет) | replace (заменить на другое — prompt что "
      "нарисовать) | detail (вернуть мелкие детали) | status (как идёт). Где: mask — файл маски (белое = перерисовать) "
      "ИЛИ area x1,y1,x2,y2 (пиксели или 10%,20%,40%,60%) ИЛИ маска, нарисованная кистью через photo_mask (берётся "
      "сама). prompt — ПО-АНГЛИЙСКИ что должно быть в этом месте (например 'woman's hand with slender fingers, "
      "natural nails'). n — сколько вариантов (3). Идёт в фоне 3–10 минут, по готовности придёт уведомление.",
      {"path": S, "what": S, "prompt": S, "area": S, "mask": S, "n": N}, ["path"], confirm=True)
def photo_ai(path: str = "", what: str = "fix", prompt: str = "", area: str = "", mask: str = "", n: int = 3) -> str:
    if what == "status" or not path:
        sts = sorted(JOBS.glob("*.status.json"), key=lambda p: p.stat().st_mtime)[-3:] if JOBS.exists() else []
        if not sts:
            return "Перерисовок ещё не было."
        out = []
        for s in sts:
            st = json.loads(s.read_text(encoding="utf-8"))
            out.append(f"{s.name.split('.')[0]}: {st.get('state')} {st.get('done', '')}/{st.get('n', '')} "
                       f"{st.get('sheet') or st.get('error') or ''}")
        return "\n".join(out)
    if not AI_PY.exists() or not AI_MODEL.exists():
        return ("Нейросеть для фото не установлена (нужен %USERPROFILE%\\photo-ai\\venv с diffusers и модель SDXL "
                "inpainting, ~10 ГБ). Скажи пользователю — поставлю, если он разрешит скачать.")
    from ..llm import gaming
    if gaming():
        return "Он сейчас играет — видеокарта занята. Перерисовку запущу, когда закончит (попроси напомнить)."
    if _RUNNING:
        return "Уже идёт одна перерисовка, дождись её (photo_ai what=status)."
    f = _targets(path)[0]
    job = {"image": str(f), "mode": what if what in ("fix", "remove", "replace", "detail") else "fix",
           "prompt": prompt, "n": max(1, min(6, int(n or 3))), "out_dir": str(f.parent / "edited"), "name": f.stem}
    if mask:
        from .files import safe
        m = safe(mask)
        mask = str(m) if m.exists() and m != f and m.suffix.lower() == ".png" and "mask" in m.stem.lower() else ""
    if mask:
        job["mask"] = mask
    elif mask_path(f).exists():
        job["mask"] = str(mask_path(f))
    elif area:
        from PIL import Image
        from .images import _box
        with Image.open(f) as im:
            from PIL import ImageOps
            im = ImageOps.exif_transpose(im)
            job["box"] = list(_box(area, im))
    else:
        return ("Не знаю, где перерисовывать: нужна область. Вызови photo_mask — пользователь закрасит место кистью — "
                "или передай area x1,y1,x2,y2.")
    if job["image"].lower().endswith((".heic", ".heif")):
        rgb, ex = P.load(f)
        job["image"] = str(P.save(rgb, f.parent / "edited" / f"{f.stem}.jpg", ex))
    JOBS.mkdir(parents=True, exist_ok=True)
    job_id = time.strftime("%Y%m%d_%H%M%S")
    job["status"] = str(JOBS / f"{job_id}.status.json")
    jf = JOBS / f"{job_id}.json"
    jf.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(job["status"]).write_text(json.dumps({"state": "queued"}), encoding="utf-8")
    threading.Thread(target=_watch, args=(job_id, jf, Path(job["status"]), f.name), daemon=True).start()
    return (f"Запустил перерисовку {f.name} ({job['mode']}, {job['n']} варианта). Займёт 3–10 минут, на это время "
            f"нейросеть ответов выгружается из видеокарты. Результат: {f.parent / 'edited'} (*_ai1.jpg … и "
            f"{f.stem}_ai_variants.jpg для сравнения), придёт уведомление.")
