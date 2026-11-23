"""Tool: drivers — what hardware is in this PC, which drivers are old / broken, and installing the driver updates
Windows Update has for it (the same as «Дополнительные обновления → драйверы», with his UAC «да»).
Firmware / BIOS is never installed unless he asked for it in words: a failed BIOS flash can kill the board."""
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

from . import S, tool
from .installer import _allowed, _ask, _confirmed
from ..logs import quiet

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FIRMWARE = re.compile(r"(?i)firmware|bios|uefi|прошив")


def _ps(script: str, timeout: int = 240) -> str:
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, timeout=timeout,
                           creationflags=NO_WINDOW)
        return (r.stdout or b"").decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return ""


def _inventory() -> dict:
    js = _ps("[Console]::OutputEncoding=[Text.Encoding]::UTF8; @{"
             "gpu=@(Get-CimInstance Win32_VideoController | select Name,DriverVersion,@{n='Date';e={$_.DriverDate.ToString('yyyy-MM-dd')}});"
             "board=(Get-CimInstance Win32_BaseBoard | select Manufacturer,Product);"
             "bios=(Get-CimInstance Win32_BIOS | select SMBIOSBIOSVersion,@{n='Date';e={$_.ReleaseDate.ToString('yyyy-MM-dd')}});"
             "cpu=(Get-CimInstance Win32_Processor | select -First 1 Name);"
             "net=@(Get-CimInstance Win32_NetworkAdapter -Filter 'PhysicalAdapter=True' | select Name);"
             "broken=@(Get-CimInstance Win32_PnPEntity | ? { $_.ConfigManagerErrorCode -ne 0 } | select Name,ConfigManagerErrorCode)"
             "} | ConvertTo-Json -Depth 4 -Compress")
    try:
        return json.loads(js)
    except Exception:
        return {}


def _wu_drivers() -> list[str]:
    out = _ps("[Console]::OutputEncoding=[Text.Encoding]::UTF8; $s=New-Object -ComObject Microsoft.Update.Session; "
              "$r=$s.CreateUpdateSearcher().Search(\"IsInstalled=0 and Type='Driver'\"); $r.Updates | % { $_.Title }", 300)
    return [x.strip() for x in out.splitlines() if x.strip()]


def _nvidia_version(drv: str) -> str:
    """Windows driver 32.0.16.2101 → NVIDIA 621.01 (the last 5 digits)."""
    d = re.sub(r"\D", "", drv or "")[-5:]
    return f"{d[:3]}.{d[3:]}" if len(d) == 5 else ""


def _nvidia_app() -> str:
    for p in (r"C:\Program Files\NVIDIA Corporation\NVIDIA App\CEF\NVIDIA App.exe",
              r"C:\Program Files\NVIDIA Corporation\NVIDIA GeForce Experience\NVIDIA GeForce Experience.exe"):
        if Path(p).exists():
            return Path(p).stem
    return ""


@tool("drivers",
      "Драйверы этого ПК. action=check — какое железо (видеокарта, плата, BIOS, сеть), версии и даты драйверов, "
      "устройства с ошибками и какие обновления драйверов есть в Windows Update. action=update — установить эти "
      "обновления драйверов (Windows спросит «Разрешить изменения»); прошивки/BIOS — только если он прямо попросил "
      "(firmware=yes). «Обнови драйвера» в его сообщении — это разрешение.",
      {"action": S, "firmware": S}, [])
def drivers(action: str = "check", firmware: str = "", ctx: dict | None = None, _ok: str = "") -> str:
    action = (action or "check").lower()
    want_fw = str(firmware).lower() in ("yes", "да", "true", "1") or bool(
        FIRMWARE.search(str((ctx or {}).get("user_text") or "")))
    inv = _inventory()
    ups = _wu_drivers()
    lines = []
    for g in inv.get("gpu") or []:
        if not isinstance(g, dict) or re.search(r"(?i)virtual|parsec|meta", g.get("Name", "")):
            continue
        nv = _nvidia_version(g.get("DriverVersion", "")) if "nvidia" in g.get("Name", "").lower() else ""
        lines.append(f"Видеокарта: {g.get('Name')} — драйвер {nv or g.get('DriverVersion')} от {g.get('Date')}")
    b = inv.get("board") or {}
    bios = inv.get("bios") or {}
    if b:
        lines.append(f"Плата: {b.get('Manufacturer')} {b.get('Product')}; BIOS {bios.get('SMBIOSBIOSVersion')} от {bios.get('Date')}")
    if inv.get("cpu"):
        lines.append(f"Процессор: {inv['cpu'].get('Name')}")
    nets = [n.get("Name") for n in inv.get("net") or [] if isinstance(n, dict)]
    if nets:
        lines.append("Сеть: " + "; ".join(nets[:4]))
    broken = [f"{d.get('Name')} (код {d.get('ConfigManagerErrorCode')})" for d in inv.get("broken") or [] if isinstance(d, dict)]
    lines.append("Устройства с ошибкой: " + ("; ".join(broken[:8]) if broken else "нет"))
    fw = [u for u in ups if FIRMWARE.search(u)]
    normal = [u for u in ups if u not in fw]
    lines.append("Windows Update предлагает драйверы: " + ("; ".join(normal) if normal else "нет"))
    if fw:
        lines.append("Прошивки/BIOS (ставлю только по отдельной просьбе): " + "; ".join(fw))
    app = _nvidia_app()
    if any("nvidia" in (g.get("Name", "") if isinstance(g, dict) else "").lower() for g in inv.get("gpu") or []):
        lines.append("Драйвер NVIDIA обновляется через " + (f"{app} (уже стоит: app_do «{app}» → «Драйверы» → "
                     "«Проверить обновления»)" if app else "NVIDIA App — install_app name=«NVIDIA App» или nvidia.com/drivers"))
    report = "\n".join(lines)
    if action != "update":
        return report
    todo = normal + (fw if want_fw else [])
    if not todo:
        return report + "\n\nУстанавливать через Windows Update нечего."
    if ctx is not None and _allowed(ctx, "драйвер driver"):
        ctx["_install_ok"] = True
    if not ((ctx or {}).get("_install_ok") or _confirmed(_ok)):
        return report + "\n\n" + _ask(ctx, "drivers", {"action": "update", "firmware": "yes" if want_fw else ""},
                                      "установить драйверы: " + "; ".join(todo))
    res = _install_wu(todo)
    after = _wu_drivers()
    left = [u for u in todo if u in after]
    return (report + "\n\nУСТАНОВКА:\n" + res + "\n\nПРОВЕРКА: " +
            ("всё установлено" if not left else "НЕ установились: " + "; ".join(left)) +
            "\n(Некоторым драйверам нужна перезагрузка — скажи ему, перезагружать сам не надо.)")


def _install_wu(titles: list[str]) -> str:
    """Download + install the chosen Windows Update driver updates in an elevated PowerShell (UAC)."""
    log = Path(tempfile.gettempdir()) / f"renard_drivers_{int(time.time())}.txt"
    want = json.dumps(titles, ensure_ascii=False).replace("'", "''")
    script = (
        "$ErrorActionPreference='Continue'; $want = ConvertFrom-Json '" + want + "'; "
        "$s=New-Object -ComObject Microsoft.Update.Session; "
        "$r=$s.CreateUpdateSearcher().Search(\"IsInstalled=0 and Type='Driver'\"); "
        "$c=New-Object -ComObject Microsoft.Update.UpdateColl; "
        "foreach($u in $r.Updates){ if($want -contains $u.Title){ $u.AcceptEula(); [void]$c.Add($u) } }; "
        "if($c.Count -eq 0){ 'nothing'; exit 0 }; "
        "$d=$s.CreateUpdateDownloader(); $d.Updates=$c; $dr=$d.Download(); \"download: $($dr.ResultCode)\"; "
        "$i=$s.CreateUpdateInstaller(); $i.Updates=$c; $ir=$i.Install(); "
        "for($k=0;$k -lt $c.Count;$k++){ \"$($c.Item($k).Title) => $($ir.GetUpdateResult($k).ResultCode)\" }; "
        "\"reboot: $($ir.RebootRequired)\"")
    path = Path(tempfile.gettempdir()) / f"renard_drivers_{int(time.time())}.ps1"
    path.write_text("& { " + script + f" }} *> '{log}'", encoding="utf-8-sig")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"$p = Start-Process powershell -Verb RunAs -WindowStyle Hidden -Wait -PassThru "
                            f"-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','{path}'; exit $p.ExitCode"],
                           capture_output=True, timeout=1800, creationflags=NO_WINDOW)
        code = r.returncode
    except subprocess.TimeoutExpired:
        return "не уложилось в 30 минут (возможно, ещё ставится в фоне)"
    text = ""
    for f in (log,):
        try:
            raw = f.read_bytes()
            text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "replace")
        except Exception:
            quiet()
    try:
        path.unlink()
        log.unlink()
    except Exception:
        quiet()
    text = re.sub(r"=> 2\b", "=> установлено", re.sub(r"=> [345]\b", "=> ОШИБКА", text))
    return text.strip() or f"(код {code}) окно «Разрешить изменения» отклонено или закрыто"
