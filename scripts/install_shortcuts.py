"""Renard shortcuts: Desktop, Start menu and the `pc` terminal command (autostart: toggle in Settings or --autostart).
All .lnk carry AppUserModelID = Renard.Agent, so the window groups under the fox icon and a taskbar pin works.
Usage: .venv\\Scripts\\python scripts\\install_shortcuts.py [--autostart | --no-autostart] [--remove]"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.shortcuts import ROOT, make_lnk, set_autostart, special


def main():
    remove = "--remove" in sys.argv
    desc = "Renard — локальный ИИ-агент (Ctrl+Alt+Space)"
    targets = [special("desktop") / "Renard.lnk", special("programs") / "Renard.lnk"]
    old = special("desktop") / "PC Agent.lnk"
    if old.exists():
        old.unlink(); print("del", old)
    for path in targets:
        if remove:
            if path.exists():
                path.unlink(); print("del", path)
        else:
            make_lnk(path, "-m agent.desktop", desc); print("ok ", path)
    if "--autostart" in sys.argv or "--no-autostart" in sys.argv or remove:
        print("autostart:", set_autostart("--autostart" in sys.argv and not remove))
    if not remove:
        bin_dir = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "WindowsApps"
        (bin_dir / "pc.cmd").write_text(f'@echo off\r\ncall "{ROOT / "pc.cmd"}" %*\r\n', encoding="utf-8")
        print("ok ", bin_dir / "pc.cmd")
        print("\nЗакрепить на панели задач: правый клик по Renard в Пуске -> «Закрепить на панели задач».")


if __name__ == "__main__":
    main()
