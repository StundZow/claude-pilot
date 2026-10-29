"""Moteurs de transcription interchangeables : Whisper (faster-whisper) et Parakeet (onnx-asr)."""
from __future__ import annotations

import gc
import logging
import os
import re
import threading
from pathlib import Path
from typing import Callable

import numpy as np

from . import models
from .config import ENGINE_LABELS
from .model import Word

log = logging.getLogger(__name__)

SR = 16000
PARAKEET_DIR = models.PARAKEET_DIR

# Phrases que Whisper invente sur les silences ou les bruits, surtout en français.
_HALLUCINATIONS = re.compile(
    r"sous-titr|amara\.org|merci d'avoir regardé|abonnez-vous|n'oubliez pas de vous abonner|"
    r"traduction et sous-titr|radio-canada|www\.|\.com\b",
    re.IGNORECASE,
)

_cuda_ready = False


def prepare_cuda() -> None:
    """Rend visibles les DLL CUDA / cuDNN installées par pip, pour ctranslate2 comme pour onnxruntime."""
    global _cuda_ready
    if _cuda_ready:
        return
    _cuda_ready = True
    try:
        import nvidia

        for base in nvidia.__path__:
            for bin_dir in Path(base).glob("*/bin"):
                os.add_dll_directory(str(bin_dir))
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    except ImportError:
        log.info("Librairies CUDA de pip absentes : calcul sur processeur")
    try:
        import onnxruntime

        onnxruntime.preload_dlls()
    except Exception:
        log.debug("Préchargement des DLL CUDA impossible", exc_info=True)


class Engine:
    def __init__(self, key: str, requested_device: str):
        self.key = key
        self.requested_device = requested_device
        self.device = "cpu"
        self._lock = threading.Lock()

    @property
    def label(self) -> str:
        return f"{ENGINE_LABELS[self.key]} ({'GPU' if self.device == 'cuda' else 'CPU'})"

    def load(self) -> None:
        raise NotImplementedError

    def transcribe(self, audio: np.ndarray, offset: float = 0.0, lexicon: list[str] | None = None) -> list[Word]:
        raise NotImplementedError


class WhisperEngine(Engine):
    def __init__(self, key: str, requested_device: str):
        super().__init__(key, requested_device)
        self.model_name = "large-v3-turbo" if key.endswith("turbo") else "large-v3"
        self.model = None

    def load(self) -> None:
        import ctranslate2
        from faster_whisper import WhisperModel

        attempts = []
        if self.requested_device in ("auto", "cuda"):
            prepare_cuda()
            if ctranslate2.get_cuda_device_count() > 0:
                attempts.append(("cuda", "float16"))
        if self.requested_device in ("auto", "cpu"):
            attempts.append(("cpu", "int8"))
        local = models.model_dir(self.key)  # téléchargé par models.py ; sinon ancien cache de faster-whisper
        source = str(local) if (local / "model.bin").exists() else self.model_name
        errors = []
        for device, compute_type in attempts:
            options = dict(
                device=device,
                compute_type=compute_type,
                download_root=str(models.LEGACY_WHISPER_DIR),
                cpu_threads=8 if device == "cpu" else 0,
            )
            try:
                try:
                    model = WhisperModel(source, local_files_only=True, **options)  # pas d'accès réseau
                except Exception:
                    model = WhisperModel(source, **options)  # modèle absent : téléchargement
                self._segments(model, np.zeros(SR, dtype=np.float32), None)  # révèle tout de suite un GPU non pris en charge
                self.model, self.device = model, device
                return
            except Exception as exc:
                log.warning("Whisper %s sur %s impossible : %s", self.model_name, device, exc)
                errors.append(f"{device} : {exc}")
        raise RuntimeError("Whisper impossible à charger (" + " ; ".join(errors) + ")")

    @staticmethod
    def _segments(model, audio: np.ndarray, lexicon: list[str] | None):
        segments, _info = model.transcribe(
            audio,
            language="fr",
            beam_size=5,
            word_timestamps=True,
            vad_filter=False,
            condition_on_previous_text=False,
            hotwords=", ".join(lexicon) if lexicon else None,
        )
        return list(segments)

    def transcribe(self, audio, offset=0.0, lexicon=None):
        with self._lock:
            segments = self._segments(self.model, audio, lexicon)
        words: list[Word] = []
        for seg in segments:
            text = seg.text.strip()
            if not text or _HALLUCINATIONS.search(text):
                continue
            if seg.no_speech_prob > 0.6 and (seg.avg_logprob < -1.0 or len(text.split()) <= 2):
                continue  # « Merci. » inventé sur un souffle
            first = True
            for w in seg.words or []:
                token = w.word.strip()
                if not token:
                    continue
                if words and not first and not w.word.startswith(" "):
                    # suite du mot précédent : « l » + « 'application » -> « l'application »
                    prev = words[-1]
                    words[-1] = Word(prev.text + token, prev.start, round(offset + w.end, 3))
                else:
                    words.append(Word(token, round(offset + w.start, 3), round(offset + w.end, 3)))
                first = False
        return words


class ParakeetEngine(Engine):
    def __init__(self, key: str, requested_device: str):
        super().__init__(key, requested_device)
        self.model = None

    def load(self) -> None:
        import onnx_asr
        import onnxruntime as ort

        attempts = []
        if self.requested_device in ("auto", "cuda"):
            prepare_cuda()
            if "CUDAExecutionProvider" in ort.get_available_providers():
                cuda = ("CUDAExecutionProvider", {"cudnn_conv_algo_search": "HEURISTIC"})
                attempts.append(("cuda", [cuda, "CPUExecutionProvider"]))
        if self.requested_device in ("auto", "cpu"):
            attempts.append(("cpu", ["CPUExecutionProvider"]))
        options = ort.SessionOptions()
        options.log_severity_level = 3  # pas d'avertissements techniques dans le journal
        errors = []
        for device, providers in attempts:
            try:
                model = onnx_asr.load_model(
                    "nemo-parakeet-tdt-0.6b-v3", PARAKEET_DIR, sess_options=options, providers=providers
                )
                model = model.with_timestamps()
                model.recognize(np.zeros(SR, dtype=np.float32), sample_rate=SR)
                if device == "cuda" and not _uses_cuda(model):
                    raise RuntimeError("onnxruntime est retombé sur le processeur")
                self.model, self.device = model, device
                return
            except Exception as exc:
                log.warning("Parakeet sur %s impossible : %s", device, exc)
                errors.append(f"{device} : {exc}")
        raise RuntimeError("Parakeet impossible à charger (" + " ; ".join(errors) + ")")

    def transcribe(self, audio, offset=0.0, lexicon=None):
        with self._lock:
            result = self.model.recognize(np.ascontiguousarray(audio, dtype=np.float32), sample_rate=SR)
        return tokens_to_words(result.tokens or [], result.timestamps or [], offset, len(audio) / SR)


def _uses_cuda(model) -> bool:
    asr = getattr(model, "asr", None)
    for value in vars(asr).values() if asr is not None else []:
        if hasattr(value, "get_providers") and "CUDAExecutionProvider" in value.get_providers():
            return True
    return False


def tokens_to_words(tokens: list[str], times: list[float], offset: float, duration: float) -> list[Word]:
    """Regroupe les morceaux de mots de Parakeet (« ▁bon », « jour », « , ») en mots datés."""
    groups: list[tuple[str, float, float]] = []
    for token, t in zip(tokens, times):
        starts_word = token.startswith(("▁", " "))
        piece = token.replace("▁", " ").strip()
        if not piece:
            continue
        if starts_word or not groups:
            groups.append((piece, t, t))
        else:
            text, start, _ = groups[-1]
            groups[-1] = (text + piece, start, t)
    words = []
    for i, (text, start, last) in enumerate(groups):
        end = min(last + 0.12, groups[i + 1][1] if i + 1 < len(groups) else duration, duration)
        words.append(Word(text, round(offset + start, 3), round(offset + max(end, start), 3)))
    return words


def create_engine(key: str, device: str) -> Engine:
    if key.startswith("whisper"):
        return WhisperEngine(key, device)
    if key == "parakeet-v3":
        return ParakeetEngine(key, device)
    raise ValueError(f"moteur inconnu : {key}")


class EngineManager:
    """Charge les moteurs à la demande (en arrière-plan) et les garde prêts en mémoire."""

    def __init__(self, device: str = "auto"):
        self.device = device
        self._engines: dict[str, Engine] = {}
        self._errors: dict[str, str] = {}
        self._loading: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def loaded(self, key: str) -> Engine | None:
        with self._lock:
            return self._engines.get(key)

    def error(self, key: str) -> str | None:
        with self._lock:
            return self._errors.get(key)

    def get(self, key: str) -> Engine:
        """Renvoie le moteur prêt à l'emploi ; attend la fin de son chargement si besoin."""
        with self._lock:
            if key in self._engines:
                return self._engines[key]
            event = self._loading.get(key)
            owner = event is None
            if owner:
                event = self._loading[key] = threading.Event()
        if not owner:
            event.wait()
            with self._lock:
                if key in self._engines:
                    return self._engines[key]
                raise RuntimeError(self._errors.get(key, "chargement impossible"))
        try:
            engine = create_engine(key, self.device)
            engine.load()
            with self._lock:
                self._engines[key] = engine
                self._errors.pop(key, None)
            log.info("Moteur prêt : %s", engine.label)
            return engine
        except Exception as exc:
            with self._lock:
                self._errors[key] = str(exc)
            raise
        finally:
            event.set()
            with self._lock:
                self._loading.pop(key, None)

    def preload(self, key: str, on_done: Callable[[str, str | None], None] | None = None) -> None:
        def run():
            error = None
            try:
                self.get(key)
            except Exception as exc:
                error = str(exc)
            if on_done:
                on_done(key, error)

        threading.Thread(target=run, name=f"load-{key}", daemon=True).start()

    def unload(self, key: str) -> None:
        with self._lock:
            engine = self._engines.pop(key, None)
        if engine is not None:
            del engine
            gc.collect()

    def set_device(self, device: str) -> None:
        """Change GPU/CPU : les moteurs seront rechargés au prochain usage."""
        self.device = device
        for key in list(self._engines):
            self.unload(key)
