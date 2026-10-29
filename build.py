"""Construit dans dist/ :

  Claude-Pilot-app.zip     le code de l'appli : l'installateur le télécharge et le met dans app\\
  Claude-Pilot-Setup.exe   l'installateur (avec uv embarqué) : le seul fichier que téléchargent les utilisateurs

    uv run python build.py            # les deux
    uv run python build.py app        # le zip seulement
    uv run python build.py installer  # l'installateur seulement
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
ICON = ROOT / "claudepilot" / "assets" / "icon.ico"
APP_FILES = ["pyproject.toml", "uv.lock", "README.md", "LICENSE", "CHANGELOG.md"]


def build_app_zip() -> Path:
    out = DIST / "Claude-Pilot-app.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((ROOT / "claudepilot").rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, path.relative_to(ROOT).as_posix())
        for name in APP_FILES:
            archive.write(ROOT / name, name)
    return out


def build_setup() -> Path:
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("uv introuvable : il est embarqué dans l'installateur.")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
                    "--name", "Claude-Pilot-Setup", "--icon", str(ICON), "--paths", str(ROOT),
                    "--add-binary", f"{uv};.", "--add-data", f"{ICON};.",
                    "--exclude-module", "PySide6", "--exclude-module", "numpy",
                    "--distpath", str(DIST), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
                    str(ROOT / "installer" / "setup_claudepilot.py")], check=True)
    return DIST / "Claude-Pilot-Setup.exe"


def main() -> None:
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    DIST.mkdir(exist_ok=True)
    if what in ("all", "app"):
        print("OK :", build_app_zip())
    if what in ("all", "installer"):
        print("OK :", build_setup())
    shutil.rmtree(ROOT / "build", ignore_errors=True)


if __name__ == "__main__":
    main()
