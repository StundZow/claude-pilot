"""Quand « là », « tu vois », « regarde »… prennent-ils vraiment une capture ?"""
from types import SimpleNamespace

from PIL import Image, ImageDraw

from claudepilot.app import Controller
from claudepilot.model import Capture
from claudepilot.screen import Frame, Monitor, signature
from claudepilot.session import Session
from claudepilot.triggers import VoiceAction

MONITOR = Monitor(1, 1, 0, 0, 2560, 1440)
PAGE = Image.new("RGB", (2560, 1440), (240, 241, 244))
DIALOG = PAGE.copy()
ImageDraw.Draw(DIALOG).rectangle((700, 300, 1900, 1100), fill=(32, 33, 36))  # une fenêtre s'ouvre


class Screen:
    """Boîte noire de test : l'écran affiché et la souris se règlent à la main."""

    def __init__(self):
        self.image, self.cursor = PAGE, (500, 500)

    def frame_at(self, t: float) -> Frame:
        return Frame(t, MONITOR, self.cursor, sig=signature(self.image))

    def capture(self) -> Frame:
        raise AssertionError("la boîte noire suffit")


def controller(tmp_path):
    session = Session.create(tmp_path)
    ctrl = SimpleNamespace(session=session, screen=Screen(), live=True, _everyday=set(), _views={})

    def store(frame: Frame, source: str, trigger: str) -> str:
        name = f"{len(session.captures) + 1:03d}_{source}.png"
        session.add_capture(Capture(round(frame.t, 3), source, name, 1, (2560, 1440), frame.cursor, trigger))
        ctrl._views[name] = frame
        return name

    ctrl._store = store
    ctrl._same_view = lambda frame: Controller._same_view(ctrl, frame)
    return ctrl


def say(ctrl, phrase: str, t: float, everyday: bool, remove: bool = False) -> bool:
    return Controller._voice_capture(ctrl, VoiceAction("capture", t, (0,), remove, phrase, everyday))


def kept(ctrl) -> list[tuple[str, float]]:
    return [(c.trigger, c.t) for c in ctrl.session.captures if not c.cancelled]


def test_mots_du_quotidien_sans_doublons(tmp_path):
    ctrl = controller(tmp_path)
    assert say(ctrl, "là", 10.0, everyday=True)
    assert not say(ctrl, "ici", 11.5, everyday=True)  # juste après une capture
    assert not say(ctrl, "là", 18.0, everyday=True)  # même écran, souris au même endroit
    ctrl.screen.cursor = (1800, 900)
    assert say(ctrl, "là", 19.0, everyday=True)  # la souris montre autre chose
    ctrl.screen.image = DIALOG
    assert say(ctrl, "tu vois", 23.0, everyday=True)  # l'écran a changé
    assert not say(ctrl, "là", 30.0, everyday=True)
    assert say(ctrl, "là", 44.0, everyday=True)  # même vue, mais 20 s plus tard : on situe la suite du texte
    assert kept(ctrl) == [("là", 10.0), ("là", 19.0), ("tu vois", 23.0), ("là", 44.0)]


def test_regarde_remplace_le_la_qui_le_precede(tmp_path):
    ctrl = controller(tmp_path)
    assert say(ctrl, "là", 36.3, everyday=True)
    assert say(ctrl, "regarde", 38.3, everyday=False)
    assert kept(ctrl) == [("regarde", 38.3)]
    assert not say(ctrl, "ici", 38.6, everyday=True)


def test_le_mot_capture_ne_double_pas_un_raccourci(tmp_path):
    ctrl = controller(tmp_path)
    ctrl._store(ctrl.screen.frame_at(5.0), "raccourci", "")
    assert not say(ctrl, "capture", 5.8, everyday=False, remove=True)
    assert say(ctrl, "capture", 7.0, everyday=False, remove=True)  # « capture » insiste : toujours pris
    assert [c.source for c in ctrl.session.captures if not c.cancelled] == ["raccourci", "voix"]
