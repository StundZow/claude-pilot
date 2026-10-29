"""Crée le raccourci « Claude Pilot » (sans console) dans le dossier du projet, avec son icône.

Usage : .venv\\Scripts\\python.exe tools\\make_shortcut.py [dossier où poser un raccourci en plus]
L'icône elle-même se dessine avec tools\\make_icon.py.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from make_icon import ICON, save_ico

ROOT = Path(__file__).resolve().parent.parent


def make_shortcut(folder: Path) -> Path:
    link = folder / "Claude Pilot.lnk"
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:CP_LINK);"
        "$s.TargetPath = $env:CP_TARGET; $s.Arguments = '-m claudepilot';"
        "$s.WorkingDirectory = $env:CP_ROOT; $s.IconLocation = $env:CP_ICON;"
        "$s.Description = 'Claude Pilot : retours vocaux avec captures pour Claude Code'; $s.Save()"
    )
    env = {
        **os.environ,
        "CP_LINK": str(link),
        "CP_TARGET": str(ROOT / ".venv" / "Scripts" / "pythonw.exe"),
        "CP_ROOT": str(ROOT),
        "CP_ICON": str(ICON),
    }
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, env=env)
    return link


if __name__ == "__main__":
    if not ICON.exists():
        save_ico("A")
    print("Raccourci :", make_shortcut(ROOT))
    if len(sys.argv) > 1:
        print("Raccourci :", make_shortcut(Path(sys.argv[1])))
