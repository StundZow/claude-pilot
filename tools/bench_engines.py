"""Banc d'essai des moteurs : précision (WER), vitesse, horodatage des mots, bruit, silence.

Usage : .venv\\Scripts\\python.exe tools\\bench_engines.py [--cpu] [moteur ...]
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from claudepilot import vad  # noqa: E402
from claudepilot.config import DATA_DIR, ENGINE_LABELS  # noqa: E402
from claudepilot.engines import create_engine  # noqa: E402

SR = 16000
DATA = ROOT / "tests" / "data"


def wer_tokens(text: str) -> list[str]:
    text = text.lower().replace("’", "'")
    text = re.sub(r"(\w)'", r"\1' ", text)
    text = re.sub(r"[^\w'\s]", " ", text.replace("-", " "))
    return text.split()


def wer(ref: str, hyp: str) -> float:
    r, h = wer_tokens(ref), wer_tokens(hyp)
    prev = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        cur = [i] + [0] * len(h)
        for j in range(1, len(h) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r[i - 1] != h[j - 1]))
        prev = cur
    return prev[-1] / max(1, len(r))


def key(word: str) -> str:
    return re.sub(r"[^\w']", "", word.lower().replace("’", "'"))


def timing_errors(ref_words: list[dict], hyp_words) -> list[float]:
    a = [key(w["text"]) for w in ref_words]
    b = [key(w.text) for w in hyp_words]
    errors = []
    for block in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(block.size):
            errors.append(abs(ref_words[block.a + k]["t"] - hyp_words[block.b + k].start))
    return errors


def run_engine(engine, pcm: np.ndarray, segments) -> tuple[list, float]:
    audio = pcm.astype(np.float32) / 32768.0
    words, compute = [], 0.0
    for start, end in segments:
        t0 = time.perf_counter()
        words.extend(engine.transcribe(audio[start:end], offset=start / SR))
        compute += time.perf_counter() - t0
    return words, compute


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("engines", nargs="*", default=list(ENGINE_LABELS))
    parser.add_argument("--cpu", action="store_true", help="forcer le calcul sur processeur")
    args = parser.parse_args()

    pcm, sr = sf.read(DATA / "tts_fr.wav", dtype="int16")
    assert sr == SR
    meta = json.loads((DATA / "tts_fr_words.json").read_text(encoding="utf-8-sig"))
    reference, ref_words = meta["reference"], meta["words"]
    duration = len(pcm) / SR

    rng = np.random.default_rng(42)
    signal_rms = np.sqrt(np.mean((pcm.astype(np.float64)) ** 2))
    noise = rng.normal(0, signal_rms / 10 ** (15 / 20), len(pcm))  # bruit à 15 dB sous la voix
    noisy = np.clip(pcm + noise, -32768, 32767).astype(np.int16)
    silence = np.clip(rng.normal(0, 30, SR * 10), -32768, 32767).astype(np.int16)  # 10 s de souffle léger

    t0 = time.perf_counter()
    segments = vad.segment(pcm)
    vad_ms = (time.perf_counter() - t0) * 1000
    lines = [
        f"# Banc d'essai — {datetime.now():%d/%m/%Y %H:%M}",
        "",
        f"Audio : voix de synthèse française, {duration:.1f} s, {len(ref_words)} mots ; "
        f"détecteur de voix : {len(segments)} phrases en {vad_ms:.0f} ms.",
        "",
        "| Moteur | Chargement | Calcul (49 s d'audio) | Vitesse | Erreurs de mots | Avec bruit | Silence | Décalage des mots (médian / 90 %) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    details = []
    for key_name in args.engines:
        engine = create_engine(key_name, "cpu" if args.cpu else "auto")
        t0 = time.perf_counter()
        try:
            engine.load()
        except Exception as exc:
            lines.append(f"| {ENGINE_LABELS[key_name]} | échec : {exc} | | | | | | |")
            continue
        load_s = time.perf_counter() - t0
        words, compute = run_engine(engine, pcm, segments)
        hyp = " ".join(w.text for w in words)
        noisy_words, _ = run_engine(engine, noisy, vad.segment(noisy))
        silent_words, _ = run_engine(engine, silence, [(0, len(silence))])
        errs = timing_errors(ref_words, words)
        med = statistics.median(errs) if errs else float("nan")
        p90 = sorted(errs)[int(len(errs) * 0.9)] if errs else float("nan")
        lines.append(
            f"| {engine.label} | {load_s:.1f} s | {compute:.2f} s | {duration / compute:.0f}× temps réel | "
            f"{wer(reference, hyp):.1%} | {wer(reference, ' '.join(w.text for w in noisy_words)):.1%} | "
            f"{len(silent_words)} mot(s) inventé(s) | {med * 1000:.0f} ms / {p90 * 1000:.0f} ms |"
        )
        details += [f"## {engine.label}", "", hyp, ""]
        if silent_words:
            details += [f"Silence → « {' '.join(w.text for w in silent_words)} »", ""]
        print(lines[-1], flush=True)
        del engine

    report = "\n".join(lines + ["", "Référence :", "", reference, ""] + details)
    out_dir = DATA_DIR / "bench"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"bench_{datetime.now():%Y-%m-%d_%H-%M}{'_cpu' if args.cpu else ''}.md"
    out.write_text(report, encoding="utf-8")
    print(f"Rapport : {out}")


if __name__ == "__main__":
    main()
