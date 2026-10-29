"""Vérifie que la barre flottante est invisible dans les captures d'écran.

Affiche ~1 s, en bas à gauche de l'écran principal : la barre, puis une fenêtre témoin magenta (visible, elle).
On compare des captures de cette zone : rien n'est enregistré ni affiché.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from claudepilot import winapi  # noqa: E402
from claudepilot.screen import new_capturer  # noqa: E402
from claudepilot.ui import Overlay  # noqa: E402


def grab(rect) -> np.ndarray:
    left, top, right, bottom = rect
    with new_capturer() as sct:
        shot = sct.grab({"left": left, "top": top, "width": right - left, "height": bottom - top})
    return np.asarray(shot)[..., :3].astype(np.int16)


def pump(app: QApplication, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.01)


def main() -> None:
    app = QApplication(sys.argv)
    area = QGuiApplication.primaryScreen().availableGeometry()
    overlay = Overlay()
    overlay.show_message("Test d'invisibilité de la barre Claude Pilot", timeout_ms=5000)
    overlay.move(area.left() + 20, area.bottom() - 80)
    pump(app, 0.4)
    rect = winapi.window_rect(int(overlay.winId()))
    excluded = winapi.user32.GetWindowDisplayAffinity if hasattr(winapi.user32, "GetWindowDisplayAffinity") else None
    with_overlay = grab(rect)
    overlay.hide()
    pump(app, 0.3)
    without = grab(rect)

    witness = QWidget(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
    witness.setStyleSheet("background: #ff00ff;")
    witness.setGeometry(overlay.geometry())
    witness.show()
    pump(app, 0.3)
    with_witness = grab(rect)
    witness.hide()
    pump(app, 0.1)

    diff_overlay = float(np.mean(np.abs(with_overlay - without)))
    diff_witness = float(np.mean(np.abs(with_witness - without)))
    print(f"zone testée : {rect}, affinité lue : {excluded is not None}")
    print(f"écart barre / sans rien : {diff_overlay:.1f}   (proche de 0 = barre invisible)")
    print(f"écart témoin / sans rien : {diff_witness:.1f}  (grand = la méthode voit bien une vraie fenêtre)")
    print("RÉSULTAT :", "barre invisible dans les captures" if diff_overlay < 3 < diff_witness else "À VÉRIFIER")


if __name__ == "__main__":
    main()
