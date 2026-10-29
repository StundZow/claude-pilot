"""Mises à jour : vérification au lancement, changelog, téléchargement de l'installateur et redémarrage.

L'installateur téléchargé est lancé avec --update : il attend la fermeture de Claude Pilot, remplace le
code (dossier app\\), met à jour les composants si besoin, puis relance l'appli.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import webbrowser
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressDialog, QPushButton, QTextBrowser, QVBoxLayout

from . import APP_NAME, APP_VERSION, GITHUB_REPO, github
from .config import INSTALL_DIR, Config


class UpdateChecker(QObject):
    found = Signal(dict)
    finished = Signal(str)  # message (vérification manuelle) : « à jour » ou erreur

    def check(self, manual: bool = False, skipped: str = "") -> None:
        def work():
            try:
                release = github.latest_release(GITHUB_REPO)
            except github.GitHubError as exc:
                if manual:
                    self.finished.emit(str(exc))
                return
            tag = release.get("tag_name") or ""
            if github.is_newer(tag, APP_VERSION) and (manual or tag != skipped):
                self.found.emit(release)
            elif manual:
                self.finished.emit(f"{APP_NAME} est à jour (version {APP_VERSION}).")

        threading.Thread(target=work, name="mises-a-jour", daemon=True).start()


class UpdateDialog(QDialog):
    LATER, SKIP, INSTALL = 0, 1, 2

    def __init__(self, release: dict, parent=None):
        super().__init__(parent)
        self.choice = self.LATER
        tag = release.get("tag_name", "")
        self.setWindowTitle("Mise à jour disponible")
        self.setMinimumSize(560, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        title = QLabel(f"{APP_NAME} {tag.lstrip('v')} est disponible")
        title.setStyleSheet("font-size: 13pt; font-weight: 600;")
        layout.addWidget(title)
        subtitle = QLabel(f"Tu as la version {APP_VERSION}. Tes retours, tes réglages et les moteurs de "
                          "transcription sont conservés.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(release.get("body") or "_Pas de notes pour cette version._")
        layout.addWidget(notes, 1)
        row = QHBoxLayout()
        skip = QPushButton("Ignorer cette version")
        skip.clicked.connect(lambda: self._done(self.SKIP))
        row.addWidget(skip)
        row.addStretch(1)
        later = QPushButton("Plus tard")
        later.clicked.connect(lambda: self._done(self.LATER))
        row.addWidget(later)
        install = QPushButton("Mettre à jour")
        install.setObjectName("primary")
        install.setDefault(True)
        install.clicked.connect(lambda: self._done(self.INSTALL))
        row.addWidget(install)
        layout.addLayout(row)

    def _done(self, choice: int) -> None:
        self.choice = choice
        self.accept()


class Updater(QObject):
    """Câblage côté fenêtre principale."""

    progress = Signal(int, int)
    downloaded = Signal(str)
    failed = Signal(str)

    def __init__(self, window, cfg: Config, quit_app: Callable[[], None]):
        super().__init__(window)
        self.window = window
        self.cfg = cfg
        self.quit_app = quit_app
        self.checker = UpdateChecker(self)
        self.checker.found.connect(self._on_found)
        self.checker.finished.connect(self._on_message)
        self.progress.connect(self._on_progress)
        self.downloaded.connect(self._run_setup)
        self.failed.connect(self._on_failed)
        self._manual = False
        self._dialog: QProgressDialog | None = None

    def check_on_startup(self) -> None:
        if self.cfg.check_updates:
            self._manual = False
            self.checker.check(manual=False, skipped=self.cfg.skipped_version)

    def check_now(self) -> None:
        self._manual = True
        self.checker.check(manual=True)

    def _on_message(self, text: str) -> None:
        if self._manual:
            QMessageBox.information(self.window, APP_NAME, text)

    def _on_found(self, release: dict) -> None:
        dialog = UpdateDialog(release, self.window)
        dialog.exec()
        if dialog.choice == UpdateDialog.SKIP:
            self.cfg.skipped_version = release.get("tag_name", "")
            self.cfg.save()
        elif dialog.choice == UpdateDialog.INSTALL:
            self.install(release)

    def install(self, release: dict) -> None:
        asset = github.find_asset(release, github.SETUP_ASSET)
        if INSTALL_DIR is None or asset is None:
            QMessageBox.information(
                self.window, APP_NAME,
                "Cette copie de Claude Pilot tourne depuis les sources : mets-la à jour avec « git pull ».\n"
                "La page de la version va s'ouvrir." if INSTALL_DIR is None else
                "Cette version ne contient pas d'installateur : la page va s'ouvrir.",
            )
            webbrowser.open(release.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases")
            return
        setup = Path(tempfile.gettempdir()) / f"Claude-Pilot-Setup-{release.get('tag_name', 'new')}.exe"
        self._dialog = QProgressDialog("Téléchargement de la mise à jour…", "", 0, 100, self.window)
        self._dialog.setWindowTitle(APP_NAME)
        self._dialog.setCancelButton(None)
        self._dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._dialog.setMinimumDuration(0)
        self._dialog.show()
        private = bool(release.get("_token_used"))

        def work():
            try:
                github.download_asset(asset, setup, lambda done, total: self.progress.emit(done, total), private)
                self.downloaded.emit(str(setup))
            except Exception as exc:
                self.failed.emit(str(exc))

        threading.Thread(target=work, name="telechargement-maj", daemon=True).start()

    def _on_progress(self, done: int, total: int) -> None:
        if self._dialog is not None and total:
            self._dialog.setValue(int(done * 100 / total))
            self._dialog.setLabelText(f"Téléchargement de la mise à jour… {done // 1048576} / {total // 1048576} Mo")

    def _on_failed(self, text: str) -> None:
        if self._dialog is not None:
            self._dialog.close()
        QMessageBox.warning(self.window, APP_NAME, f"Mise à jour impossible : {text}")

    def _run_setup(self, setup: str) -> None:
        """L'installateur attend la fermeture de Claude Pilot, remplace le code et le relance."""
        if self._dialog is not None:
            self._dialog.close()
        try:
            subprocess.Popen(
                [setup, "--update", "--dir", str(INSTALL_DIR), "--wait-pid", str(os.getpid())],
                close_fds=True, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        except OSError as exc:
            QMessageBox.critical(self.window, APP_NAME, f"Impossible de lancer la mise à jour :\n{exc}")
            return
        self.quit_app()
