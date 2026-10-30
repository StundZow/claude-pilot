import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from claudepilot.viewer import CaptureViewer  # noqa: E402


@pytest.fixture(scope="module")
def qt():
    return QApplication.instance() or QApplication([])


def image(color: str) -> QImage:
    img = QImage(2560, 1476, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    return img


def press(viewer: CaptureViewer, key: Qt.Key) -> None:
    viewer.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def test_visionneuse(qt):
    def gone():
        raise OSError("capture supprimée entre-temps")

    items = [("C1 · 0:05", lambda: image("#dc2626")), ("C2 · 0:09", gone), ("C3 · 0:12", lambda: image("#2563eb"))]
    viewer = CaptureViewer(items, 0)
    viewer.resize(1600, 900)
    assert viewer.index == 0 and viewer.prev_btn.isHidden() and not viewer.next_btn.isHidden()
    pixmap = viewer._scaled()
    size, area = pixmap.deviceIndependentSize(), viewer._area()
    assert size.width() <= area.width() and size.height() <= area.height()  # tient dans l'écran, proportions gardées
    assert max(size.width() - area.width(), size.height() - area.height()) > -2  # et le remplit

    press(viewer, Qt.Key.Key_Right)
    assert viewer.index == 1 and viewer._scaled() is None  # image introuvable : message, pas de plantage
    viewer.grab()
    press(viewer, Qt.Key.Key_End)
    press(viewer, Qt.Key.Key_Right)
    assert viewer.index == 2 and viewer.next_btn.isHidden()
    press(viewer, Qt.Key.Key_Home)
    assert viewer.index == 0
    viewer.deleteLater()
