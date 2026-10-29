"""Mots déclencheurs (« capture », « regarde »…) et commandes vocales repérés dans la transcription."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .model import Word

COMMANDS = {
    "cancel": (
        "annule la capture", "annule la dernière capture", "annule capture",
        "supprime la capture", "efface la capture",
    ),
    "point": ("point suivant", "nouveau point", "sujet suivant"),
}
# Verbes qui ne déclenchent une capture qu'à l'impératif : « Regarde, ce bouton » oui, « je regarde » non.
IMPERATIVE_ONLY = {"regarde", "regardez", "vois", "voyez", "check"}
_SUBJECTS = {"je", "j", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles"}
_CLITICS = {"ne", "n", "me", "m", "te", "t", "se", "s", "le", "la", "les", "l", "lui", "leur", "y", "en"}
_EDGE_PUNCT = re.compile(r"^[^\w']+|[^\w']+$")


@dataclass(frozen=True)
class VoiceAction:
    kind: str  # "capture", "cancel" ou "point"
    t: float  # fin du dernier mot prononcé
    words: tuple[int, ...]  # index des mots concernés
    remove: bool  # retirer ces mots du texte final
    phrase: str


def norm(token: str) -> str:
    text = unicodedata.normalize("NFC", token).lower().replace("’", "'").replace("`", "'")
    return _EDGE_PUNCT.sub("", text)


def _split(phrase: str) -> tuple[str, ...]:
    return tuple(t for t in (norm(part) for part in phrase.split()) if t)


def _is_imperative(tokens: list[str], i: int) -> bool:
    j, skipped = i - 1, 0
    while j >= 0 and skipped < 3:
        tok = tokens[j]
        if "'" in tok:  # « j' », « qu'on » -> « j », « on »
            tail = tok.split("'")[-1]
            tok = tail or tok.split("'")[0]
        if tok in _SUBJECTS:
            return False
        if tok in _CLITICS:
            j, skipped = j - 1, skipped + 1
            continue
        return True
    return True


def detect(words: list[Word], triggers: list[str], kept: list[str], commands: bool = True) -> list[VoiceAction]:
    """Repère les captures vocales et les commandes, du plus long motif au plus court."""
    tokens = [norm(w.text) for w in words]
    kept_set = {" ".join(_split(k)) for k in kept}
    patterns: list[tuple[str, tuple[str, ...], bool, str]] = []
    if commands:
        for kind, phrases in COMMANDS.items():
            patterns.extend((kind, _split(p), True, p) for p in phrases)
    for trigger in triggers:
        toks = _split(trigger)
        if toks:
            patterns.append(("capture", toks, " ".join(toks) not in kept_set, trigger))
    patterns.sort(key=lambda p: len(p[1]), reverse=True)

    actions: list[VoiceAction] = []
    i = 0
    while i < len(tokens):
        for kind, pattern, remove, phrase in patterns:
            n = len(pattern)
            window = tokens[i:i + n]
            if len(window) < n:
                continue
            if n == 1:
                matched = window[0] == pattern[0] or window[0].split("-")[0] == pattern[0]
            else:
                matched = tuple(window) == pattern
            if not matched:
                continue
            if kind == "capture" and n == 1 and pattern[0] in IMPERATIVE_ONLY and not _is_imperative(tokens, i):
                continue
            actions.append(VoiceAction(kind, words[i + n - 1].end, tuple(range(i, i + n)), remove, phrase))
            i += n
            break
        else:
            i += 1
    return actions
