"""Intégration Windows de l'installation (sans Qt : sert aussi à l'installateur).

Tout est par utilisateur (pas de droits admin) : raccourcis menu Démarrer / bureau et
entrée « Applications installées » (HKCU) pour la désinstallation.

Disposition du dossier d'installation :
  app\\       le code de l'appli (remplacé à chaque mise à jour)
  venv\\      Python et les composants (installés par uv)
  runtime\\   uv et le Python géré par uv
  models\\    les moteurs de transcription
  data\\      réglages et journaux
  install.json, claude-pilot.ico, Claude-Pilot-Setup.exe (sert à désinstaller)
"""
import json
import os
import subprocess
import winreg
from pathlib import Path

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ClaudePilot"
SHORTCUT_NAME = "Claude Pilot.lnk"
SETUP_NAME = "Claude-Pilot-Setup.exe"
INFO_NAME = "install.json"


def default_install_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Programs" / "Claude Pilot"


def app_dir(install_dir: Path) -> Path:
    return install_dir / "app"


def pythonw(install_dir: Path) -> Path:
    return install_dir / "venv" / "Scripts" / "pythonw.exe"


def python(install_dir: Path) -> Path:
    return install_dir / "venv" / "Scripts" / "python.exe"


def icon_path(install_dir: Path) -> Path:
    return install_dir / "claude-pilot.ico"


def read_info(install_dir: Path) -> dict:
    try:
        return json.loads((install_dir / INFO_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_info(install_dir: Path, **values) -> None:
    info = read_info(install_dir) | values
    (install_dir / INFO_NAME).write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")


def _ps(script: str) -> bool:
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-Command", script], capture_output=True, text=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _ps_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def create_shortcuts(install_dir: Path, desktop: bool, start_menu: bool = True) -> bool:
    folders = []
    if start_menu:
        folders.append("[Environment]::GetFolderPath('Programs')")
    if desktop:
        folders.append("[Environment]::GetFolderPath('Desktop')")
    if not folders:
        return True
    script = "$w = New-Object -ComObject WScript.Shell; "
    for folder in folders:
        # Parenthèses obligatoires : sans elles PowerShell passe « [Environment]::… » comme du texte.
        script += (f"$s = $w.CreateShortcut((Join-Path ({folder}) {_ps_str(SHORTCUT_NAME)})); "
                   f"$s.TargetPath = {_ps_str(str(pythonw(install_dir)))}; $s.Arguments = '-m claudepilot'; "
                   f"$s.WorkingDirectory = {_ps_str(str(app_dir(install_dir)))}; "
                   f"$s.IconLocation = {_ps_str(str(icon_path(install_dir)) + ',0')}; "
                   "$s.Description = 'Claude Pilot'; $s.Save(); ")
    return _ps(script)


def remove_shortcuts() -> None:
    _ps("foreach ($f in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) "
        f"{{ $p = Join-Path $f {_ps_str(SHORTCUT_NAME)}; if (Test-Path $p) {{ Remove-Item $p -Force }} }}")


def register(install_dir: Path, version: str) -> None:
    setup = install_dir / SETUP_NAME
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        values = {
            "DisplayName": "Claude Pilot",
            "DisplayVersion": version,
            "Publisher": "StundZow",
            "InstallLocation": str(install_dir),
            "DisplayIcon": f"{icon_path(install_dir)},0",
            "UninstallString": f'"{setup}" --uninstall --dir "{install_dir}"',
            "URLInfoAbout": "https://github.com/StundZow/claude-pilot",
        }
        for name, value in values.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, 6 * 1024 * 1024)  # ≈ 6 Go, en Ko
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)


def registered_location() -> Path | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            return Path(winreg.QueryValueEx(k, "InstallLocation")[0])
    except OSError:
        return None


def update_registered_version(version: str, install_dir: Path) -> None:
    """Après une mise à jour : version affichée dans « Applications installées »."""
    loc = registered_location()
    if loc and install_dir.resolve() == loc.resolve():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, version)
        except OSError:
            pass


def unregister() -> None:
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
