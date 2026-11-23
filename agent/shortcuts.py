"""Windows shortcuts for Renard (.lnk with AppUserModelID, so the window groups under the fox icon on the taskbar)."""
from pathlib import Path

from .config import ROOT

PYW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
ICO = ROOT / "web" / "assets" / "renard.ico"
APP_ID = "Renard.Agent"


def special(name: str) -> Path:
    from win32com.shell import shell, shellcon
    csidl = {"desktop": shellcon.CSIDL_DESKTOPDIRECTORY, "programs": shellcon.CSIDL_PROGRAMS,
             "startup": shellcon.CSIDL_STARTUP}[name]
    return Path(shell.SHGetFolderPath(0, csidl, None, 0))


def make_lnk(path: Path, args: str, desc: str):
    import pythoncom
    from win32com.client import Dispatch
    from win32com.propsys import propsys, pscon
    from win32com.shell import shellcon
    pythoncom.CoInitialize()
    sh = Dispatch("WScript.Shell").CreateShortcut(str(path))
    sh.TargetPath, sh.Arguments, sh.WorkingDirectory = str(PYW), args, str(ROOT)
    sh.IconLocation, sh.Description = str(ICO), desc
    sh.Save()
    store = propsys.SHGetPropertyStoreFromParsingName(str(path), None, shellcon.GPS_READWRITE, propsys.IID_IPropertyStore)
    store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_ID, pythoncom.VT_LPWSTR))
    store.Commit()


def autostart_path() -> Path:
    return special("startup") / "Renard.lnk"


def autostart_enabled() -> bool:
    try:
        return autostart_path().exists()
    except Exception:
        return False


def set_autostart(on: bool) -> bool:
    """Called only from the Settings toggle (the user's explicit choice)."""
    p = autostart_path()
    if on:
        make_lnk(p, "-m agent.desktop --tray", "Renard в трее при входе в Windows")
    elif p.exists():
        p.unlink()
    return p.exists()
