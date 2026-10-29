"""Téléchargement des moteurs de transcription depuis Hugging Face, avec une vraie progression.

Chaque fichier est téléchargé directement (reprise possible après une coupure) ; un fichier .complete
marque un moteur entièrement téléchargé.

En ligne de commande (utilisé par l'installateur) : python -m claudepilot.models parakeet-v3
affiche des lignes « PROGRESS <fait> <total> » puis « DONE ».
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable

from .config import MODELS_DIR

HF = "https://huggingface.co"
PARAKEET_DIR = MODELS_DIR / "parakeet-tdt-0.6b-v3"
PARAKEET_FILES = ["config.json", "vocab.txt", "encoder-model.onnx", "encoder-model.onnx.data", "decoder_joint-model.onnx"]
LEGACY_WHISPER_DIR = MODELS_DIR / "whisper"  # anciens téléchargements (cache Hugging Face de faster-whisper)
_WHISPER_FILES = re.compile(r"^(config\.json|preprocessor_config\.json|model\.bin|tokenizer\.json|vocabulary\.\w+)$")
MODELS = {  # moteur : (dépôt Hugging Face, dossier local, fichiers à prendre)
    "parakeet-v3": ("istupakov/parakeet-tdt-0.6b-v3-onnx", PARAKEET_DIR,
                    re.compile("^(" + "|".join(re.escape(f) for f in PARAKEET_FILES) + ")$")),
    "whisper-large-v3": ("Systran/faster-whisper-large-v3", MODELS_DIR / "whisper-large-v3", _WHISPER_FILES),
    "whisper-large-v3-turbo": ("mobiuslabsgmbh/faster-whisper-large-v3-turbo", MODELS_DIR / "whisper-large-v3-turbo",
                               _WHISPER_FILES),
}
WHISPER_NAMES = {"whisper-large-v3": "large-v3", "whisper-large-v3-turbo": "large-v3-turbo"}


def model_dir(key: str) -> Path:
    return MODELS[key][1]


def is_downloaded(key: str) -> bool:
    folder = model_dir(key)
    if (folder / ".complete").exists():
        return True
    if key == "parakeet-v3":  # téléchargé avant l'existence du marqueur
        return all((folder / name).exists() for name in PARAKEET_FILES)
    return _legacy_whisper(key)


def _legacy_whisper(key: str) -> bool:
    try:
        from faster_whisper.utils import download_model

        download_model(WHISPER_NAMES[key], cache_dir=str(LEGACY_WHISPER_DIR), local_files_only=True)
        return True
    except Exception:
        return False


def _open(url: str, headers: dict | None = None):
    request = urllib.request.Request(url, headers={"User-Agent": "Claude-Pilot", **(headers or {})})
    return urllib.request.urlopen(request, timeout=30)


def remote_files(key: str) -> dict[str, int]:
    """Fichiers utiles du moteur sur Hugging Face, avec leur taille."""
    repo, _folder, wanted = MODELS[key]
    with _open(f"{HF}/api/models/{repo}/tree/main") as response:
        entries = json.load(response)
    return {e["path"]: int(e.get("size") or 0) for e in entries if e.get("type") == "file" and wanted.match(e["path"])}


def download(key: str, progress: Callable[[int, int], None] = lambda done, total: None) -> None:
    repo, folder, _wanted = MODELS[key]
    folder.mkdir(parents=True, exist_ok=True)
    files = remote_files(key)
    if not files:
        raise RuntimeError(f"aucun fichier trouvé pour {key} sur Hugging Face")
    total = sum(files.values())
    done = 0
    for name, size in files.items():
        dest = folder / name
        if dest.exists() and (not size or dest.stat().st_size == size):
            done += size
            progress(done, total)
            continue
        done = _fetch(f"{HF}/{repo}/resolve/main/{name}", dest, size, done, total, progress)
    (folder / ".complete").write_text("ok", encoding="utf-8")
    progress(total, total)


def _fetch(url: str, dest: Path, size: int, done: int, total: int, progress) -> int:
    """Télécharge un fichier dans <nom>.part (en reprenant si possible), puis le met en place."""
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    with _open(url, {"Range": f"bytes={have}-"} if have else None) as response:
        if have and response.status != 206:
            have = 0  # le serveur repart du début
        done += have
        last = 0.0
        with open(part, "ab" if have else "wb") as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)
                done += len(chunk)
                now = time.monotonic()
                if now - last > 0.3:
                    progress(min(done, total), total)
                    last = now
    if size and part.stat().st_size != size:
        raise RuntimeError(f"{dest.name} est incomplet, relance le téléchargement")
    part.replace(dest)
    return done


def main() -> int:
    key = sys.argv[1] if len(sys.argv) > 1 else "parakeet-v3"
    if is_downloaded(key):
        print("DONE", flush=True)
        return 0
    try:
        download(key, lambda done, total: print(f"PROGRESS {done} {total}", flush=True))
    except Exception as exc:
        print(f"ERROR {exc}", flush=True)
        return 1
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
