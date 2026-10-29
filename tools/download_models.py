"""Télécharge une fois pour toutes les modèles de transcription dans models/."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claudepilot.config import MODELS_DIR  # noqa: E402


def folder_size(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e9


def main() -> None:
    from faster_whisper.utils import download_model

    for name in ("large-v3", "large-v3-turbo"):
        start = time.perf_counter()
        path = download_model(name, cache_dir=str(MODELS_DIR / "whisper"))
        print(f"Whisper {name} : {folder_size(Path(path)):.2f} Go en {time.perf_counter() - start:.0f} s", flush=True)

    import onnx_asr

    start = time.perf_counter()
    target = MODELS_DIR / "parakeet-tdt-0.6b-v3"
    onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", target, providers=["CPUExecutionProvider"])
    print(f"Parakeet v3 : {folder_size(target):.2f} Go en {time.perf_counter() - start:.0f} s", flush=True)


if __name__ == "__main__":
    main()
