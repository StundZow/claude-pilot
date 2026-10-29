"""Bruitages doux et satisfaisants, dans l'esprit des sons Apple, entièrement synthétisés ici (aucun fichier emprunté)."""
from __future__ import annotations

import logging
import threading
import time
import wave
import winsound

import numpy as np

from .config import DATA_DIR

log = logging.getLogger(__name__)

SR = 48000
VERSION = 2  # à augmenter quand on retouche un son : les fichiers sont régénérés
SOUND_DIR = DATA_DIR / "sons"

GLASS = ((1.0, 1.0, 1.0), (2.32, 0.42, 0.55), (4.25, 0.2, 0.35), (6.63, 0.08, 0.22))
BELL = ((1.0, 1.0, 1.0), (2.0, 0.3, 0.6), (3.0, 0.12, 0.4), (4.2, 0.05, 0.25))
WOOD = ((1.0, 1.0, 1.0), (3.93, 0.28, 0.35), (9.2, 0.07, 0.18))


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(SR * seconds)) / SR


def _place(parts: list[tuple[float, np.ndarray]]) -> np.ndarray:
    """Assemble des sons décalés dans le temps."""
    out = np.zeros(max(int(SR * at) + len(x) for at, x in parts))
    for at, x in parts:
        start = int(SR * at)
        out[start:start + len(x)] += x
    return out


def _tone(freq: float, seconds: float, partials, decay: float, attack: float = 0.003) -> np.ndarray:
    """Note de cloche / verre / bois : partiels qui s'éteignent plus vite dans les aigus."""
    t = _t(seconds)
    out = np.zeros_like(t)
    for ratio, amp, decay_mul in partials:
        f = freq * ratio
        if f > SR * 0.45:
            continue
        env = np.exp(-t / (decay * decay_mul))
        out += amp * env * np.sin(2 * np.pi * f * t)
        out += 0.3 * amp * env * np.sin(2 * np.pi * f * 2 ** (3 / 1200) * t + 0.7)  # léger chorus : son plus rond
    return out * np.clip(t / attack, 0.0, 1.0)


def _glide(f_start: float, f_end: float, seconds: float, glide: float, decay: float, attack: float = 0.0015) -> np.ndarray:
    """Hauteur qui glisse très vite : « pop » de bulle (vers le grave) ou goutte d'eau (vers l'aigu)."""
    t = _t(seconds)
    freq = f_end + (f_start - f_end) * np.exp(-t / glide)
    return np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.clip(t / attack, 0.0, 1.0) * np.exp(-t / decay)


def _bandpass(x: np.ndarray, low: float, high: float, taps: int = 129) -> np.ndarray:
    n = np.arange(taps) - (taps - 1) / 2
    kernel = 2 * high / SR * np.sinc(2 * high / SR * n) - 2 * low / SR * np.sinc(2 * low / SR * n)
    return np.convolve(x, kernel * np.hamming(taps), mode="same")


def _click(pitch: float, rng: np.random.Generator) -> np.ndarray:
    """Un « clac » d'obturateur : souffle filtré très bref + résonances du boîtier."""
    t = _t(0.06)
    noise = _bandpass(rng.normal(0, 1, len(t)), 1800 * pitch, 7000 * pitch) * np.exp(-t / 0.0035)
    noise /= np.max(np.abs(noise)) + 1e-9
    body = sum(
        a * np.exp(-t / tau) * np.sin(2 * np.pi * f * pitch * t)
        for f, a, tau in ((2300, 0.5, 0.006), (3700, 0.3, 0.004), (720, 0.35, 0.012))
    )
    return noise + body


def _room(x: np.ndarray, rng: np.random.Generator, wet: float = 0.16, length: float = 0.35) -> np.ndarray:
    """Une pointe de réverbération : le son « respire » au lieu de s'arrêter net."""
    t = _t(length)
    ir = np.convolve(rng.normal(0, 1, len(t)) * np.exp(-t / (length / 6)), np.ones(24) / 24, mode="same")
    ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
    size = len(x) + len(ir)
    tail = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)
    out = np.zeros(size)
    out[:len(x)] = x
    return out + wet * tail


def _design(name: str, rng: np.random.Generator) -> np.ndarray:
    if name == "start":  # deux notes de verre qui montent
        return _room(_place([(0.0, _tone(1046.5, 0.6, GLASS, 0.22)), (0.085, _tone(1568.0, 0.8, GLASS, 0.3))]), rng)
    if name == "stop":  # les mêmes, qui redescendent
        return _room(_place([(0.0, _tone(1568.0, 0.6, GLASS, 0.22)), (0.085, _tone(1046.5, 0.8, GLASS, 0.3))]), rng)
    if name == "capture":  # obturateur « clic-clac »
        return _room(_place([(0.0, _click(1.0, rng)), (0.075, 0.75 * _click(0.82, rng))]), rng, wet=0.1, length=0.2)
    if name == "cancel":  # deux bulles qui descendent, comme un retour en arrière
        return _room(_place([(0.0, _glide(950, 420, 0.12, 0.014, 0.03)), (0.07, _glide(700, 300, 0.14, 0.016, 0.035))]),
                     rng, wet=0.1)
    if name == "point":  # tintement de verre
        return _room(_tone(1760.0, 0.6, GLASS, 0.18), rng, wet=0.2)
    if name == "pause":  # petit bloc de bois
        return _room(_tone(392.0, 0.35, WOOD, 0.07, attack=0.001), rng, wet=0.12)
    if name == "resume":
        return _room(_place([(0.0, _tone(392.0, 0.3, WOOD, 0.06, attack=0.001)),
                             (0.07, _tone(523.25, 0.35, WOOD, 0.07, attack=0.001))]), rng, wet=0.12)
    if name == "phrase":  # « plip » de goutte, très discret
        return _room(_glide(1100, 2400, 0.06, 0.012, 0.016, attack=0.001), rng, wet=0.12, length=0.2)
    if name == "copy":  # « pop » de bulle
        return _room(_glide(1400, 520, 0.09, 0.011, 0.022), rng, wet=0.12)
    if name == "ready":  # arpège de réussite
        return _room(_place([(0.0, _tone(1046.5, 0.9, BELL, 0.28)), (0.06, _tone(1318.5, 0.9, BELL, 0.28)),
                             (0.12, _tone(1568.0, 1.2, BELL, 0.4))]), rng, wet=0.2, length=0.5)
    if name == "engine":  # moteur de transcription prêt
        return _room(_place([(0.0, _tone(1975.5, 0.5, GLASS, 0.12)), (0.07, _tone(2637.0, 0.6, GLASS, 0.16))]), rng, wet=0.18)
    if name == "error":  # « bonk » grave et rond, pas agressif
        return _room(_glide(250, 185, 0.3, 0.03, 0.09, attack=0.002) + 0.3 * _glide(500, 370, 0.3, 0.03, 0.05, attack=0.002),
                     rng, wet=0.1)
    raise ValueError(name)


# nom : (niveau maximal en dBFS à 100 % de volume, priorité : un son ne coupe pas un son plus important)
SOUNDS = {
    "start": (-9, 4), "stop": (-9, 4), "ready": (-8, 4), "error": (-8, 4),
    "capture": (-7, 3), "cancel": (-10, 3),
    "point": (-12, 2), "pause": (-10, 2), "resume": (-10, 2), "engine": (-15, 2),
    "copy": (-11, 1),
    "phrase": (-24, 0),
}


def _finish(x: np.ndarray, peak_db: float) -> np.ndarray:
    audible = np.nonzero(np.abs(x) > np.max(np.abs(x)) * 10 ** (-60 / 20))[0]
    x = x[: audible[-1] + 1].copy() if len(audible) else x.copy()
    fade = min(len(x), int(SR * 0.012))
    x[-fade:] *= np.linspace(1.0, 0.0, fade)
    return x / (np.max(np.abs(x)) + 1e-9) * 10 ** (peak_db / 20)


_lock = threading.Lock()
_durations: dict[str, float] = {}
_last = ("", 0.0, 0.0, -1)  # nom, début, durée, priorité


def _file(name: str, volume: int):
    path = SOUND_DIR / f"{name}-v{VERSION}-{volume}.wav"
    with _lock:
        if not path.exists():
            peak_db = SOUNDS[name][0] + 20 * np.log10(volume / 100)
            samples = _finish(_design(name, np.random.default_rng(7)), peak_db)
            SOUND_DIR.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            with wave.open(str(tmp), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(SR)
                out.writeframes((samples * 32767).astype("<i2").tobytes())
            tmp.replace(path)
        if path.name not in _durations:
            with wave.open(str(path), "rb") as w:
                _durations[path.name] = w.getnframes() / w.getframerate()
    return path


def prepare(volume: int) -> None:
    """Fabrique d'avance tous les sons au volume choisi (en arrière-plan) et efface les anciennes versions."""
    if volume <= 0:
        return

    def work():
        for name in SOUNDS:
            try:
                _file(name, volume)
            except Exception:
                log.exception("Son %s impossible à fabriquer", name)
        for old in SOUND_DIR.glob("*.wav"):
            if not old.name.endswith(f"-v{VERSION}-{volume}.wav"):
                try:
                    old.unlink()
                except OSError:
                    pass

    threading.Thread(target=work, name="sons", daemon=True).start()


def play(name: str, volume: int = 70) -> None:
    global _last
    if volume <= 0:
        return
    try:
        path = _file(name, volume)
        priority = SOUNDS[name][1]
        now = time.perf_counter()
        with _lock:
            _name, started, duration, last_priority = _last
            if now - started < duration and priority < last_priority:
                return  # un « plip » ne coupe pas le « clic-clac » d'une capture
            _last = (name, now, _durations[path.name], priority)
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        log.debug("Son %s impossible", name, exc_info=True)


def demo(volume: int) -> None:
    """Petite visite de tous les bruitages, dans l'ordre d'un vrai retour."""
    sequence = [("start", 0.7), ("phrase", 0.6), ("capture", 0.7), ("phrase", 0.5), ("point", 0.7),
                ("cancel", 0.7), ("pause", 0.6), ("resume", 0.7), ("stop", 0.8), ("ready", 1.4), ("copy", 0.6)]

    def run():
        global _last
        for name, wait in sequence:
            with _lock:
                _last = ("", 0.0, 0.0, -1)
            play(name, volume)
            time.sleep(wait)

    threading.Thread(target=run, name="demo-sons", daemon=True).start()
