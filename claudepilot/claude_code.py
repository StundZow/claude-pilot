"""Intégration Claude Code : skill /retour et accès en lecture au dossier des retours.

D'après la doc Claude Code (code.claude.com, vérifiée le 29/10/2026) : les commandes perso sont devenues des
« skills » (~/.claude/skills/<nom>/SKILL.md, valables dans tous les projets), et une lecture hors du dossier
de travail demande une autorisation, sauf si le dossier figure dans permissions.additionalDirectories.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
SKILL_PATH = CLAUDE_DIR / "skills" / "retour" / "SKILL.md"
SETTINGS_PATH = CLAUDE_DIR / "settings.json"


def skill_text(latest: Path) -> str:
    return f"""---
description: Lire mon dernier retour vocal Claude Pilot (transcription + captures d'écran) et le traiter.
argument-hint: "[consigne en plus, facultatif]"
disable-model-invocation: true
---
Lis mon dernier retour vocal : `{latest}`.

C'est la transcription de ce que j'ai dit à voix haute en te montrant mon écran. Les marqueurs comme [C2 · 0:31] indiquent la capture d'écran prise à ce moment précis de la phrase : lis chaque capture listée en bas du fichier (outil Read), dans l'ordre, avant de répondre. Sur les captures, le cercle rouge montre où était ma souris.

Ensuite, traite mes remarques point par point. $ARGUMENTS
"""


def is_installed() -> bool:
    return SKILL_PATH.exists()


def install(retours_dir: Path) -> list[str]:
    """Crée /retour et autorise la lecture du dossier des retours. Renvoie la liste de ce qui a été fait."""
    done = []
    SKILL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SKILL_PATH.write_text(skill_text(retours_dir / "dernier_retour.md"), encoding="utf-8")
    done.append(f"commande /retour : {SKILL_PATH}")

    settings: dict = {}
    if SETTINGS_PATH.exists():
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))  # JSON invalide : on s'arrête là
        backup = SETTINGS_PATH.with_name(f"settings.backup-{datetime.now():%Y%m%d-%H%M%S}.json")
        shutil.copy2(SETTINGS_PATH, backup)
        done.append(f"sauvegarde des réglages : {backup}")
    directories = settings.setdefault("permissions", {}).setdefault("additionalDirectories", [])
    target = retours_dir.as_posix()
    if target not in directories:
        directories.append(target)
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_PATH)
    done.append(f"lecture autorisée sans question : {target}")
    return done
