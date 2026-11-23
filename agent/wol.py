"""Wake-on-LAN: switching the PC on from Telegram while it is off.

The PC cannot run a bot while it is off, so the «waker» (waker/renard_waker.py, stdlib only) runs on another device at
home that stays on (old Android phone with Termux, Raspberry Pi, NAS…). It is its own small Telegram bot; on /on it sends
the magic packet to this PC's network card, which stays powered while the PC is off.

This module: readiness check of this PC (network card, Windows settings, BIOS hints) and the waker package
(waker.json + the script) that can be sent to the phone through the Renard bot.
"""
import json
import re
import shutil
import socket
import subprocess
import time
import zipfile
from pathlib import Path

from .config import DATA_DIR

ROOT = Path(__file__).resolve().parents[1]
WAKER_SRC = ROOT / "waker" / "renard_waker.py"
OUT = DATA_DIR / "waker"
CFG = OUT / "waker_settings.json"


def _ps(cmd: str, timeout: int = 20) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + cmd],
                       capture_output=True, timeout=timeout)
    return r.stdout.decode("utf-8", "replace")


def readiness() -> dict:
    """What this PC needs for Wake-on-LAN, checked one by one."""
    info = {"ok": False, "checks": [], "mac": "", "ip": "", "broadcast": "", "adapter": ""}
    try:
        raw = _ps("Get-NetAdapter -Physical | ? { $_.MediaType -eq '802.3' } | Select Name,InterfaceDescription,Status,"
                  "MacAddress | ConvertTo-Json; '---'; Get-NetIPConfiguration | ? IPv4DefaultGateway | Select "
                  "InterfaceAlias,@{n='ip';e={$_.IPv4Address.IPAddress}},@{n='len';e={$_.IPv4Address.PrefixLength}},"
                  "@{n='gw';e={$_.IPv4DefaultGateway.NextHop}} | ConvertTo-Json")
        a_raw, ip_raw = raw.split("---", 1)
        ads = json.loads(a_raw or "[]")
        ads = ads if isinstance(ads, list) else [ads]
        ips = json.loads(ip_raw or "[]")
        ips = ips if isinstance(ips, list) else [ips]
    except Exception as e:
        info["checks"].append({"name": "Сетевые карты", "ok": False, "text": f"не удалось прочитать: {e}"})
        return info
    eth = next((a for a in ads if a.get("Status") == "Up"), ads[0] if ads else None)
    if not eth:
        info["checks"].append({"name": "Проводная сеть", "ok": False,
                               "text": "Нет проводной сетевой карты. Wake-on-LAN работает только по кабелю."})
        return info
    info["adapter"], info["mac"] = eth["Name"], eth["MacAddress"].replace("-", ":")
    up = eth.get("Status") == "Up"
    info["checks"].append({"name": "ПК подключён кабелем", "ok": up,
                           "text": f"{eth['InterfaceDescription']}" + ("" if up else " — кабель не подключён: по Wi-Fi включение не работает")})
    ip = next((i for i in ips if i.get("InterfaceAlias") == eth["Name"]), None)
    if ip:
        info["ip"], info["gateway"] = ip["ip"], ip.get("gw") or ""
        n = int(ip.get("len") or 24)
        o = [int(x) for x in ip["ip"].split(".")]
        mask = (0xFFFFFFFF << (32 - n)) & 0xFFFFFFFF
        b = (int.from_bytes(bytes(o), "big") & mask) | (~mask & 0xFFFFFFFF)
        info["broadcast"] = socket.inet_ntoa(b.to_bytes(4, "big"))
    props = {}
    for line in _ps(f"Get-NetAdapterAdvancedProperty -Name '{eth['Name']}' | % {{ $_.RegistryKeyword + '=' + ($_.RegistryValue -join ',') }}").splitlines():
        if "=" in line:
            k, v = line.strip().split("=", 1)
            props[k] = v
    magic = props.get("*WakeOnMagicPacket") == "1"
    info["checks"].append({"name": "Пробуждение по Magic Packet", "ok": magic,
                           "text": "включено в драйвере" if magic else "Диспетчер устройств → сетевая карта → Дополнительно → "
                                                                     "«Wake on Magic Packet» = Включено"})
    if "S5WakeOnLan" in props:
        s5 = props["S5WakeOnLan"] == "1"
        info["checks"].append({"name": "Включение из выключенного состояния", "ok": s5,
                               "text": "включено (Shutdown Wake-On-LAN)" if s5 else "Дополнительно → «Shutdown Wake-On-LAN» = Включено"})
    armed = eth["InterfaceDescription"].split("(")[0].strip()[:20].lower() in _ps("powercfg /devicequery wake_armed").lower()
    info["checks"].append({"name": "Windows разрешает карте будить ПК", "ok": armed,
                           "text": "да" if armed else "Диспетчер устройств → сетевая карта → Управление электропитанием → "
                                                     "«Разрешить этому устройству выводить компьютер из ждущего режима» и «только magic packet»"})
    fast = _ps("(Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Power').HiberbootEnabled").strip()
    info["checks"].append({"name": "Быстрый запуск Windows", "ok": None if fast == "1" else True,
                           "text": "включён — обычно не мешает, но если ПК не просыпается после «Завершения работы», выключи: "
                                   "Панель управления → Электропитание → Действия кнопок питания → «Включить быстрый запуск»"
                           if fast == "1" else "выключен — хорошо для Wake-on-LAN"})
    board = _ps("(Get-CimInstance Win32_BaseBoard | % { $_.Manufacturer + ' ' + $_.Product })").strip()
    bios = ("BIOS (Del при включении) → Advanced → APM Configuration → «Power On By PCI-E» = Enabled и «ErP Ready» = Disabled"
            if "ASUS" in board.upper() else
            "BIOS: включи «Wake on LAN / Power On By PCI-E / PME» и выключи «ErP / Deep Sleep / EuP»")
    info["checks"].append({"name": f"BIOS ({board})", "ok": None, "text": bios + ". Проверить это можно только перезагрузкой."})
    info["board"] = board
    info["ok"] = up and magic and bool(info["ip"])
    if info["mac"] and settings().get("mac") != info["mac"]:
        save_settings(mac=info["mac"])
    return info


def settings() -> dict:
    try:
        return json.loads(CFG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(**kw) -> dict:
    s = {**settings(), **{k: v for k, v in kw.items() if v is not None}}
    OUT.mkdir(parents=True, exist_ok=True)
    CFG.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    return s


LISTEN_OUT = OUT / "listen.json"
_listen = {"proc": None}


def _private(ip: str) -> bool:
    import ipaddress
    try:
        a = ipaddress.ip_address(ip)
        return a.is_private or a.is_loopback or a in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return False


_pub = {"ip": "", "t": 0.0}


def public_ip(max_age: float = 300) -> str:
    """The home network's address on the internet (cached 5 min: the settings page asks it on every open)."""
    import httpx
    if _pub["ip"] and time.time() - _pub["t"] < max_age:
        return _pub["ip"]
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            ip = httpx.get(url, timeout=4).text.strip()
            if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ip):
                _pub.update(ip=ip, t=time.time())
                return ip
        except Exception:
            continue
    return ""


def wan_port() -> int:
    """A random high port, chosen once: bots scan the usual 7/9 and the round numbers."""
    s = settings()
    if not s.get("wan_port"):
        import random
        s = save_settings(wan_port=random.randint(20000, 60999))
    return int(s["wan_port"])


def internet_info(r: dict | None = None) -> dict:
    r = r or {}
    s = settings()
    ip = public_ip()
    if ip:
        save_settings(last_public_ip=ip)
    port = wan_port()
    bcast = r.get("broadcast") or "192.168.0.255"
    return {"public_ip": ip, "host": s.get("wan_host") or ip, "custom_host": bool(s.get("wan_host")), "port": port,
            "cgnat": bool(ip) and _private(ip), "router": f"https://{r['gateway']}" if r.get("gateway") else "",
            "rule": {"proto": "UDP", "ext_port": port, "to_ip": bcast, "to_ip_alt": r.get("ip", ""), "to_port": 9},
            "tested": s.get("wan_tested", "")}


def start_listen(seconds: int = 180) -> dict:
    """Listen for this PC's magic packet (ports 9 and the forwarded one) with the system python.exe — Windows Firewall
    already allows it on this network; the Renard pythonw is not in the rules."""
    import sys
    stop_listen()
    r = {"mac": settings().get("mac")} if settings().get("mac") else readiness()
    exe = Path(getattr(sys, "_base_executable", "") or sys.executable)
    exe = exe.with_name("python.exe") if exe.name.lower() == "pythonw.exe" else exe
    OUT.mkdir(parents=True, exist_ok=True)
    LISTEN_OUT.unlink(missing_ok=True)
    _listen["proc"] = subprocess.Popen([str(exe), "-I", str(ROOT / "waker" / "wol_listen.py"), r["mac"], str(seconds),
                                        str(LISTEN_OUT), "9", str(wan_port())],
                                       creationflags=0x08000000, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "seconds": seconds, "mac": r["mac"]}


def stop_listen():
    p = _listen.get("proc")
    if p and p.poll() is None:
        p.terminate()
    _listen["proc"] = None


def listen_status() -> dict:
    try:
        st = json.loads(LISTEN_OUT.read_text(encoding="utf-8"))
    except Exception:
        return {"running": bool(_listen.get("proc") and _listen["proc"].poll() is None), "hits": []}
    for h in st.get("hits", []):
        h["external"] = not _private(h["from"])
    st["running"] = not st.get("done") and bool(_listen.get("proc") and _listen["proc"].poll() is None)
    if any(h["external"] for h in st.get("hits", [])):
        save_settings(wan_tested=time.strftime("%d.%m.%Y %H:%M"))
        stop_listen()
        st["running"] = False
    return st


def public_ip_changed() -> tuple[str, str] | None:
    """For the «ПК включён» message: the home IP changed while the PC was off -> the phone widget needs the new one
    (only when internet mode is set up and no DDNS name is used)."""
    s = settings()
    if not s.get("wan_port") or s.get("wan_host"):
        return None
    old, new = s.get("last_public_ip", ""), public_ip(max_age=0)
    if new:
        save_settings(last_public_ip=new)
    return (old, new) if old and new and old != new else None


def build_package(token: str = "") -> Path:
    """waker.json (MAC, IP, the second bot's token, who may use it) + renard_waker.py, zipped, ready for the phone."""
    from .telegram_bot import CFG_PATH as TG
    token = token or settings().get("token", "")
    if not token:
        raise ValueError("нужен токен второго бота (будильника) от @BotFather")
    if not re.fullmatch(r"\d+:[\w-]{30,}", token):
        raise ValueError("это не похоже на токен бота (пример: 123456:ABC…)")
    s = save_settings(token=token)
    r = readiness()
    try:
        tg = json.loads(TG.read_text(encoding="utf-8"))
    except Exception:
        tg = {}
    if s["token"] == tg.get("token"):
        raise ValueError("нужен ОТДЕЛЬНЫЙ бот: у основного бота Renard этот токен уже занят")
    cfg = {"token": s["token"], "allowed": tg.get("allowed", []), "mac": r["mac"], "ip": r["ip"],
           "broadcast": r["broadcast"] or "255.255.255.255", "check_ports": [445, 135, 3389]}
    if s.get("wan_port"):
        cfg.update(wan_host=s.get("wan_host") or s.get("last_public_ip") or public_ip(), wan_port=int(s["wan_port"]))
    return _zip(cfg, with_bot=True)


def build_phone_package() -> Path:
    """No bot, no device at home: a home-screen button on the phone (Termux:Widget) that sends the packet through
    the router's forwarded port."""
    s = settings()
    r = readiness()
    cfg = {"mac": r["mac"], "ip": r["ip"], "broadcast": r["broadcast"] or "255.255.255.255",
           "wan_host": s.get("wan_host") or s.get("last_public_ip") or public_ip(), "wan_port": wan_port()}
    return _zip(cfg, with_bot=False)


def _zip(cfg: dict, with_bot: bool) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "waker.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.copy(WAKER_SRC, OUT / "renard_waker.py")
    (OUT / "README.txt").write_text(INSTRUCTIONS if with_bot else PHONE_INSTRUCTIONS, encoding="utf-8")
    assets = WAKER_SRC.parent / "assets"
    z = OUT / ("renard_waker.zip" if with_bot else "renard_button.zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        for n in ("renard_waker.py", "waker.json", "README.txt"):
            f.write(OUT / n, n)
        if cfg.get("wan_host"):
            f.writestr("shortcuts/tasks/Включить ПК", (assets / "button.sh").read_bytes().replace(b"\r\n", b"\n"))
            f.write(assets / "fox_button.png", "shortcuts/icons/Включить ПК.png")
    return z


INSTRUCTIONS = """Renard Waker — включение ПК из Telegram

1. На устройстве, которое всегда включено и подключено к домашнему Wi-Fi/роутеру (старый Android, Raspberry Pi):
   Android: установи Termux (из F-Droid), затем в Termux:
       pkg install python
       termux-setup-storage
       mkdir -p ~/waker && cp /sdcard/Download/renard_waker.zip ~/waker/ && cd ~/waker && unzip -o renard_waker.zip
       python renard_waker.py
   Raspberry Pi / Linux: unzip renard_waker.zip && python3 renard_waker.py
2. Напиши своему боту-будильнику /status — он ответит, включён ли ПК. /on — включит.
3. Чтобы Android не усыплял Termux: уведомление Termux → «Acquire wakelock», и отключи оптимизацию батареи для Termux.
4. Проверка без Telegram: python renard_waker.py waker.json --wake

Выключить ПК можно как раньше — основному боту Renard: «выключи пк».
"""

PHONE_INSTRUCTIONS = """Renard — кнопка «Включить ПК» на телефоне (через интернет, без устройства дома)

Сначала в роутере: проброс порта UDP (внешний порт — в waker.json, wan_port) на домашний широковещательный адрес
(broadcast в waker.json), порт 9. Renard → Настройки → «Включение ПК» показывает точные значения и проверяет проброс.

Вариант А — без кода: приложение «Wake On Lan» (Android) → добавить устройство:
    MAC = mac, адрес/хост = wan_host, порт = wan_port из waker.json. У приложения есть виджет-кнопка.

Вариант Б — эта кнопка (Android, Termux + Termux:Widget — оба из F-Droid или оба с GitHub; Termux из Google Play
с виджетом не работает):
    Поставь ещё Termux:API (из того же источника) — для вибрации и подсказки «сигнал отправлен».
    pkg install python termux-api
    termux-setup-storage
    mkdir -p ~/waker ~/.shortcuts && cp /sdcard/Download/renard_button.zip ~/waker/ && cd ~/waker && python -m zipfile -e renard_button.zip .
    (не unzip: он портит русское имя кнопки)
    cp -r shortcuts/tasks shortcuts/icons ~/.shortcuts/ && chmod 700 ~/.shortcuts ~/.shortcuts/tasks ~/.shortcuts/tasks/*
    Затем добавь круглую кнопку на рабочий стол (работает на любом лаунчере, в т.ч. OnePlus/Samsung):
    am start -n com.termux.widget/.TermuxCreateShortcutActivity
    → tasks/ → «Включить ПК» → «Добавить». (Если лаунчер показывает виджет «Termux shortcut» 1×1 — можно и через него.)
    Появится круглая кнопка с лисой. Она работает в фоне: короткая вибрация и «⚡ сигнал отправлен».
    Чтобы Android её не «усыплял»: Настройки → Приложения → Termux, Termux:API, Termux:Widget → Батарея → «Без ограничений».
Проверка: python ~/waker/renard_waker.py ~/waker/waker.json --wake

Когда Windows загрузится, основной бот Renard напишет «ПК включён».
"""
