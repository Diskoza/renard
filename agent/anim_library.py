"""Build the companion's mocap library: data/animations/library/<source>/<category>/*.fbx + catalog.json.
Sources: Mixamo FBX (downloaded into ~/Downloads, names = Mixamo names), Rokoko packs (data/animations/raw/rokoko).
BVH sets (CMU, Bandai Namco, 100STYLE) stay in raw/ for a later conversion.
python -m agent.anim_library"""
import json
import re
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "animations" / "raw"
LIB = ROOT / "data" / "animations" / "library"
MIXAMO_CATS = json.loads((ROOT / "data" / "animations" / "mixamo_cats.json").read_text(encoding="utf-8"))
LOOP_CATS = {"idle", "walk", "dance", "music"}
NOT_AUTO = re.compile(r"(?i)thriller|chicken|ymca|macarena")
DROP = re.compile(r"(?i)^(silly dancing|rockin' shackle a|shopping cart dance|dancing maraschino step|male dance pose|female dance pose)$")
FEMALE = re.compile(r"(?i)^(belly dance|dancing|jazz dancing|rumba dancing|booty hip hop dance|salsa dancing)$")
LOOP_NAMES = re.compile(r"(?i)idle|texting|typing|gaming|guitar|piano|singing|sleeping|lying|laying|talking|tablet|pose|dancing|"
                        r"dance|drinking|phone|calling|petting|rapping|listening")


def slug(s):
    return re.sub(r"[^\w\- .']+", "", s).strip()


def add(cat_list, src, cat, name, f):
    dst = LIB / src / cat / f"{slug(name)}.fbx"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists() or dst.stat().st_size != f.stat().st_size:
        shutil.copy2(f, dst)
    loop = cat in LOOP_CATS or bool(LOOP_NAMES.search(name)) and cat != "gesture"
    cat_list.append({"id": f"{src}:{slug(name)}", "name": name, "cat": cat, "src": src, "loop": loop,
                     "file": "/anims/" + dst.relative_to(LIB).as_posix()})


def main():
    items = []
    src_dirs = [RAW / "mixamo", Path.home() / "Downloads"]
    found = 0
    for name, cat in MIXAMO_CATS.items():
        hits = [p for d in src_dirs for p in d.glob("*.fbx") if p.stem == name or re.fullmatch(re.escape(name) + r" \(\d+\)", p.stem)]
        if not hits:
            hits = list((LIB / "mixamo" / cat).glob(f"{slug(name)}.fbx"))
        if hits:
            add(items, "mixamo", cat, name, max(hits, key=lambda p: p.stat().st_mtime)); found += 1
    rok = {"EVERYDAY-IDLES": "idle", "WalkCycles": "walk", "WALK-RUN": "walk", "Dancing": "dance", "Magic": "gesture"}
    for f in (RAW / "rokoko").rglob("*.fbx"):
        if f.name.startswith("._") or not re.search(r"(?i)mixamo", f.name):
            continue
        cat = next((c for k, c in rok.items() if k.lower() in str(f).lower()), "misc")
        if cat == "walk" and re.search(r"(?i)run|sprint|jog", f.stem):
            continue
        name = re.sub(r"(?i)[_ -]*(mixamo|whs|769|segment|loop|-?\d+)(?=[_ -]|$)", "", f.stem)
        name = re.sub(r"[_-]+", " ", re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)).strip()
        add(items, "rokoko", cat, "Rokoko " + name, f)
    LIB.mkdir(parents=True, exist_ok=True)
    tempo = {}
    if (LIB / "tempo.json").exists():
        tempo = json.loads((LIB / "tempo.json").read_text(encoding="utf-8"))
    items = [it for it in items if not DROP.search(it["name"])]
    old = json.loads((LIB / "catalog.json").read_text(encoding="utf-8")) if (LIB / "catalog.json").exists() else []
    items += [it for it in old if it.get("src") == "user"]
    removed = set(json.loads((LIB / "removed.json").read_text(encoding="utf-8"))) if (LIB / "removed.json").exists() else set()
    items = [it for it in items if it["id"] not in removed]
    for it in items:
        if it["cat"] == "dance":
            it["female"] = bool(FEMALE.search(it["name"]))
            it["bpm"] = (tempo.get(it["name"]) or {}).get("bpm")
            it["auto"] = not NOT_AUTO.search(it["name"])
    (LIB / "catalog.json").write_text(json.dumps(items, ensure_ascii=False, indent=0), encoding="utf-8")
    by = {}
    for it in items:
        by.setdefault(it["cat"], 0); by[it["cat"]] += 1
    print(f"mixamo {found}/{len(MIXAMO_CATS)}, всего {len(items)}: {by}")


if __name__ == "__main__":
    main()
