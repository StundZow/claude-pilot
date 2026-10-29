"""Photographie l'interface dans chaque état, sans rien afficher à l'écran (retour simulé, écrans de synthèse).

Usage : .venv\\Scripts\\python.exe tools\\snapshot_ui.py <dossier de sortie>
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "windows"  # vrai rendu Windows (polices, icônes), mais fenêtres invisibles
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import simulate_session as sim  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dataclasses import fields  # noqa: E402

from claudepilot import app as app_module  # noqa: E402
from claudepilot.audio import input_devices  # noqa: E402
from claudepilot.config import Config  # noqa: E402
from claudepilot.settings_dialog import SettingsDialog  # noqa: E402


def pump(qt: QApplication, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        qt.processEvents()
        time.sleep(0.01)


def main() -> None:
    out = Path(sys.argv[1])
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    app_module.Recorder = sim.FakeRecorder
    app_module.ScreenService = sim.FakeScreen

    qt = QApplication(sys.argv)
    ctrl = app_module.Controller(qt)
    ctrl.hotkeys = sim.NoHotkeys()
    fresh = Config()  # réglages par défaut : aucun réglage personnel (nom de micro…) sur les images
    for field in fields(Config):
        setattr(ctrl.cfg, field.name, getattr(fresh, field.name))
    ctrl.cfg.retours_dir = str(out / "retours")
    ctrl.cfg.sounds = False
    ctrl.cfg.copy_prompt_on_stop = False
    ctrl.cfg.save = lambda: None  # ne touche pas aux vrais réglages
    for widget in (ctrl.window, ctrl.overlay):
        widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

    ctrl.cfg.retours_path.mkdir(parents=True, exist_ok=True)
    ctrl.window.init_controls(ctrl.cfg, input_devices())
    ctrl.window.set_mode("idle", ctrl.cfg)
    ctrl.refresh_history(select_latest=True)
    ctrl.window.show()
    ctrl._update_engine_status()
    ctrl.ticker.start()
    pump(qt, 0.4)
    ctrl.window.grab().save(str(out / "1_accueil.png"))

    ctrl.engines.get(ctrl.cfg.engine)
    ctrl._update_engine_status()
    ctrl.start_recording()
    recorder = ctrl.recorder
    shots = {}

    def script():
        while recorder.now() < sim.HOTKEY_AT:
            time.sleep(0.01)
        ctrl.run(lambda: ctrl.capture("raccourci"))
        while recorder.now() < 36.0:
            time.sleep(0.01)
        ctrl.run(lambda: shots.setdefault("live", True))
        recorder.wait_end()
        ctrl.run(ctrl.stop_recording)

    threading.Thread(target=script, daemon=True).start()
    t0 = time.perf_counter()
    while ctrl.state != "idle" or ctrl.last_result is None:
        qt.processEvents()
        time.sleep(0.01)
        if shots.pop("live", False):
            pump(qt, 0.5)
            ctrl.window.grab().save(str(out / "2_en_direct.png"))
            ctrl.overlay.grab().save(str(out / "3_barre.png"))
        if time.perf_counter() - t0 > 300:
            raise SystemExit("Simulation bloquée")

    pump(qt, 0.8)
    ctrl.window.grab().save(str(out / "4_retour_pret.png"))
    ctrl.overlay.grab().save(str(out / "5_barre_prete.png"))
    dialog = SettingsDialog(ctrl.cfg, input_devices(), parent=ctrl.window,
                            selected_label=app_module.describe(ctrl.selected)["title"])
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dialog.show()
    for index in range(dialog.tabs.count()):
        dialog.tabs.setCurrentIndex(index)
        pump(qt, 0.2)
        dialog.grab().save(str(out / f"6_reglages_{index + 1}_{dialog.tabs.tabText(index)}.png"))
    dialog.close()
    ctrl._png.shutdown(wait=True)
    print("Photos :", ", ".join(sorted(p.name for p in out.glob("*.png"))))


if __name__ == "__main__":
    main()
