"""Captures d'écran : l'écran sous la souris, la « boîte noire » des dernières secondes, la mise en forme pour Claude."""
from __future__ import annotations

import io
import logging
import math
import queue
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

import mss
from PIL import Image, ImageDraw, ImageFont

from . import winapi

log = logging.getLogger(__name__)

new_capturer = getattr(mss, "MSS", None) or mss.mss  # mss 10 renomme mss.mss en mss.MSS

CURSOR_COLOR = (232, 30, 30)
BAND_COLOR = (32, 33, 36)
BAND_HEIGHT = 36
SIGNATURE_SIZE = (64, 36)
SAME_CURSOR = 0.05  # souris déplacée de moins de 5 % de la largeur de l'écran : même endroit
SAME_PIXELS = 2.5  # écart moyen des vignettes (sur 255) en dessous duquel l'écran n'a pas changé


@dataclass(frozen=True)
class Monitor:
    index: int  # index mss (1 = premier écran)
    number: int  # numéro Windows (\\.\DISPLAYn), comme dans Paramètres > Affichage
    left: int
    top: int
    width: int
    height: int

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.left + self.width and self.top <= y < self.top + self.height

    def distance(self, x: int, y: int) -> int:
        dx = max(self.left - x, 0, x - (self.left + self.width - 1))
        dy = max(self.top - y, 0, y - (self.top + self.height - 1))
        return dx + dy

    @property
    def region(self) -> dict:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


def list_monitors(sct) -> list[Monitor]:
    names = winapi.monitor_device_names()
    monitors = []
    for i, m in enumerate(sct.monitors[1:], start=1):
        rect = (m["left"], m["top"], m["width"], m["height"])
        match = re.search(r"(\d+)$", names.get(rect, ""))
        monitors.append(Monitor(i, int(match.group(1)) if match else i, *rect))
    return monitors


def monitor_at(monitors: list[Monitor], x: int, y: int) -> Monitor:
    return min(monitors, key=lambda m: m.distance(x, y))


@dataclass
class Frame:
    """Une image d'écran datée sur l'horloge de la session."""

    t: float
    monitor: Monitor
    cursor: tuple[int, int] | None  # position de la souris dans l'image
    img: Image.Image | None = None  # capture directe (gardée telle quelle)
    jpeg: bytes | None = None  # image de la boîte noire (compressée en mémoire)
    sig: bytes | None = None  # vignette en gris : reconnaître deux vues identiques sans garder les images

    def image(self) -> Image.Image:
        if self.img is not None:
            return self.img
        return Image.open(io.BytesIO(self.jpeg)).convert("RGB")

    def same_view(self, other: Frame) -> bool:
        """Même écran, même contenu à peu de chose près, souris presque au même endroit."""
        if self.monitor != other.monitor or not self.sig or not other.sig or len(self.sig) != len(other.sig):
            return False
        if (self.cursor is None) != (other.cursor is None):
            return False
        if self.cursor and other.cursor and math.dist(self.cursor, other.cursor) > SAME_CURSOR * self.monitor.width:
            return False
        return sum(abs(a - b) for a, b in zip(self.sig, other.sig)) / len(self.sig) < SAME_PIXELS


def signature(img: Image.Image) -> bytes:
    return img.resize(SIGNATURE_SIZE, Image.BILINEAR, reducing_gap=2.0).convert("L").tobytes()


class ScreenService(threading.Thread):
    """Un seul fil pour toutes les captures : à la demande, et en continu pour la boîte noire."""

    def __init__(
        self,
        clock: Callable[[], float],
        fps: float = 2.0,
        seconds: float = 60.0,
        avoid_rects: Callable[[], list[tuple[int, int, int, int]]] = list,
    ):
        super().__init__(name="screen", daemon=True)
        self.clock = clock
        self.period = 1.0 / fps if fps > 0 else 0.0
        self.seconds = seconds
        self.avoid_rects = avoid_rects
        self.monitors: list[Monitor] = []
        self._requests: queue.Queue = queue.Queue()
        self._ring: deque[Frame] = deque()
        self._ring_lock = threading.Lock()
        self._last_cursor: tuple[int, int] | None = None
        self._stop_event = threading.Event()
        self._ready = threading.Event()

    def capture(self, timeout: float = 3.0) -> Frame | None:
        """Capture immédiate de l'écran sous la souris."""
        request = {"done": threading.Event(), "frame": None}
        self._requests.put(request)
        request["done"].wait(timeout)
        return request["frame"]

    def frame_at(self, t: float) -> Frame | None:
        """Image de la boîte noire la plus proche d'un moment passé."""
        with self._ring_lock:
            if not self._ring:
                return None
            return min(self._ring, key=lambda f: abs(f.t - t))

    def stop(self) -> None:
        self._stop_event.set()
        self._requests.put(None)
        self.join(3)

    def wait_ready(self, timeout: float = 3.0) -> bool:
        return self._ready.wait(timeout)

    def _cursor(self) -> tuple[int, int] | None:
        """Position de la souris, en ignorant les fenêtres de Claude Pilot (on garde alors la dernière position utile)."""
        pos = winapi.cursor_pos()
        if pos and any(r[0] <= pos[0] < r[2] and r[1] <= pos[1] < r[3] for r in self.avoid_rects()):
            return self._last_cursor
        if pos:
            self._last_cursor = pos
        return pos

    def run(self) -> None:
        try:
            with new_capturer() as sct:
                self.monitors = list_monitors(sct)
                self._ready.set()
                next_frame = 0.0
                while not self._stop_event.is_set():
                    try:
                        request = self._requests.get(timeout=0.05)
                    except queue.Empty:
                        request = None
                    if request is not None:
                        try:
                            request["frame"] = self._grab(sct, keep=True)
                        except Exception:
                            log.exception("Capture d'écran impossible")
                        request["done"].set()
                        continue
                    self._cursor()
                    now = time.perf_counter()
                    if self.period and now >= next_frame:
                        next_frame = now + self.period
                        try:
                            self._push(self._grab(sct, keep=False))
                        except Exception:
                            log.exception("Image de boîte noire impossible")
        except Exception:
            log.exception("Service de capture arrêté")
        finally:
            self._ready.set()
            while True:
                try:
                    request = self._requests.get_nowait()
                except queue.Empty:
                    break
                if request is not None:
                    request["done"].set()

    def _grab(self, sct, keep: bool) -> Frame:
        t = self.clock()
        cursor = self._cursor()
        monitor = monitor_at(self.monitors, *cursor) if cursor else self.monitors[0]
        shot = sct.grab(monitor.region)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        inside = cursor is not None and monitor.contains(*cursor)
        frame = Frame(t, monitor, (cursor[0] - monitor.left, cursor[1] - monitor.top) if inside else None,
                      sig=signature(img))
        if keep:
            frame.img = img
        else:
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=90)
            frame.jpeg = buf.getvalue()
        return frame

    def _push(self, frame: Frame) -> None:
        with self._ring_lock:
            self._ring.append(frame)
            while self._ring and frame.t - self._ring[0].t > self.seconds:
                self._ring.popleft()


_fonts: dict[int, ImageFont.ImageFont] = {}


def _font(size: int):
    if size not in _fonts:
        for name in ("segoeuib.ttf", "segoeui.ttf", "arialbd.ttf", "arial.ttf"):
            try:
                _fonts[size] = ImageFont.truetype(name, size)
                break
            except OSError:
                continue
        else:
            _fonts[size] = ImageFont.load_default(size=size)
    return _fonts[size]


def render_capture(img: Image.Image, label: str, cursor: tuple[int, int] | None, max_px: int) -> Image.Image:
    """Cercle rouge autour de la souris, réduction à max_px, bandeau d'étiquette en haut."""
    img = img.convert("RGB").copy()
    if cursor is not None:
        draw = ImageDraw.Draw(img)
        radius = max(16, round(min(img.size) * 0.02))
        width = max(3, round(min(img.size) / 300))
        x, y = cursor
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=CURSOR_COLOR, width=width)
    scale = min(1.0, max_px / img.width, (max_px - BAND_HEIGHT) / img.height)
    if scale < 1.0:
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    out = Image.new("RGB", (img.width, img.height + BAND_HEIGHT), BAND_COLOR)
    out.paste(img, (0, BAND_HEIGHT))
    draw = ImageDraw.Draw(out)
    font = _font(20)
    box = draw.textbbox((0, 0), label, font=font)
    draw.text((12, (BAND_HEIGHT - (box[3] - box[1])) // 2 - box[1]), label, font=font, fill=(255, 255, 255))
    return out
