"""Visionneuse des captures : un clic sur une image de l'aperçu l'affiche en grand."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QToolButton, QWidget

from . import winapi
from .ui import glyph_icon

BACKDROP = QColor(10, 10, 12)
BUTTON_STYLE = (
    "QToolButton { background: rgba(255, 255, 255, 0.07); border: none; border-radius: 26px; }"
    "QToolButton:hover { background: rgba(255, 255, 255, 0.18); }"
)


class CaptureViewer(QWidget):
    """Plein écran sur l'écran de la fenêtre. Échap ou clic : fermer · ← →, molette : capture précédente, suivante."""

    SIDE, TOP, BOTTOM = 84, 24, 80  # marges autour de l'image (flèches, croix, légende)

    def __init__(self, items: list[tuple[str, Callable[[], QImage | None]]], index: int, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Capture · Claude Pilot")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.items = items  # (légende, chargement de l'image en grand)
        self.index = -1
        self._image: QImage | None = None
        self._pixmap: QPixmap | None = None
        self._wheel = 0
        self.prev_btn = self._button("prev", "Capture précédente (←)", lambda: self.show_index(self.index - 1))
        self.next_btn = self._button("next", "Capture suivante (→)", lambda: self.show_index(self.index + 1))
        self.close_btn = self._button("close", "Fermer (Échap)", self.close)
        screen = (parent.screen() if parent is not None else None) or QGuiApplication.primaryScreen()
        self.setGeometry(screen.availableGeometry())
        self.show_index(index)

    def _button(self, icon: str, tip: str, action: Callable[[], object]) -> QToolButton:
        button = QToolButton(self)
        button.setIcon(glyph_icon(icon, size=24))
        button.setIconSize(QSize(24, 24))
        button.setFixedSize(52, 52)
        button.setToolTip(tip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Espace et Entrée ferment la visionneuse
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(BUTTON_STYLE)
        button.clicked.connect(action)
        return button

    def show_index(self, index: int) -> None:
        index = max(0, min(index, len(self.items) - 1))
        if index == self.index:
            return
        self.index = index
        try:
            self._image = self.items[index][1]()
        except Exception:
            self._image = None
        self._pixmap = None
        several = len(self.items) > 1
        self.prev_btn.setVisible(several and index > 0)
        self.next_btn.setVisible(several and index < len(self.items) - 1)
        self.update()

    def _area(self) -> QRect:
        return self.rect().adjusted(self.SIDE, self.TOP, -self.SIDE, -self.BOTTOM)

    def _scaled(self) -> QPixmap | None:
        """L'image à la taille de l'écran, calculée une fois (en pixels réels, nette même avec une mise à l'échelle)."""
        if self._image is None or self._image.isNull():
            return None
        if self._pixmap is None:
            ratio = self.devicePixelRatioF()
            area = self._area()
            target = QSize(round(area.width() * ratio), round(area.height() * ratio))
            pixmap = QPixmap.fromImage(self._image.scaled(target, Qt.AspectRatioMode.KeepAspectRatio,
                                                          Qt.TransformationMode.SmoothTransformation))
            pixmap.setDevicePixelRatio(ratio)
            self._pixmap = pixmap
        return self._pixmap

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), BACKDROP)
        area = self._area()
        pixmap = self._scaled()
        font = QFont("Segoe UI")
        if pixmap is None:
            font.setPixelSize(16)
            p.setFont(font)
            p.setPen(QColor("#9a9aa2"))
            p.drawText(area, Qt.AlignmentFlag.AlignCenter, "Capture introuvable")
        else:
            size = pixmap.deviceIndependentSize()
            p.drawPixmap(QPointF(area.x() + (area.width() - size.width()) / 2,
                                 area.y() + (area.height() - size.height()) / 2), pixmap)
        caption = self.items[self.index][0]
        hint = "Échap ou clic pour fermer"
        if len(self.items) > 1:
            caption += f"   ·   {self.index + 1} / {len(self.items)}"
            hint += "  ·  ← → pour passer d'une capture à l'autre"
        center = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        font.setPixelSize(16)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor("#f4f4f5"))
        p.drawText(QRect(0, self.height() - self.BOTTOM + 14, self.width(), 26), center, caption)
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.Normal)
        p.setFont(font)
        p.setPen(QColor("#71717a"))
        p.drawText(QRect(0, self.height() - self.BOTTOM + 44, self.width(), 22), center, hint)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._pixmap = None
        middle = (self.height() - self.BOTTOM + self.TOP) // 2 - 26
        self.prev_btn.move(16, middle)
        self.next_btn.move(self.width() - 68, middle)
        self.close_btn.move(self.width() - 68, 16)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.close()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp):
            self.show_index(self.index - 1)
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_PageDown):
            self.show_index(self.index + 1)
        elif key == Qt.Key.Key_Home:
            self.show_index(0)
        elif key == Qt.Key.Key_End:
            self.show_index(len(self.items) - 1)
        else:
            super().keyPressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.close()

    def wheelEvent(self, event) -> None:
        self._wheel += event.angleDelta().y()
        while abs(self._wheel) >= 120:  # un cran de molette (les pavés tactiles envoient des petits pas)
            step = -1 if self._wheel > 0 else 1
            self._wheel += 120 * step
            self.show_index(self.index + step)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        winapi.exclude_from_capture(int(self.winId()))  # pendant un enregistrement, elle n'apparaît pas sur les captures
        self.activateWindow()
        self.setFocus()
