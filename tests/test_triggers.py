from claudepilot.model import Word
from claudepilot.triggers import detect

TRIGGERS = ["capture d'écran", "capture", "screenshot", "screen", "regarde"]
KEPT = ["regarde"]


def words(text: str, step: float = 0.4) -> list[Word]:
    return [Word(w, i * step, i * step + 0.3) for i, w in enumerate(text.split())]


def kinds(text: str) -> list[tuple[str, str, bool]]:
    return [(a.kind, a.phrase, a.remove) for a in detect(words(text), TRIGGERS, KEPT)]


def test_regarde_imperatif_reste_dans_le_texte():
    assert kinds("Regarde, le bouton Valider") == [("capture", "regarde", False)]
    assert kinds("Et là, regarde ce menu") == [("capture", "regarde", False)]


def test_je_regarde_ne_declenche_rien():
    assert kinds("Je regarde aussi le fichier") == []
    assert kinds("je le regarde depuis hier") == []
    assert kinds("on regarde ça ensemble") == []
    assert kinds("qu'on regarde demain") == []


def test_capture_est_retiree_du_texte():
    assert kinds("une erreur rouge. Capture.") == [("capture", "capture", True)]


def test_annule_la_capture_ne_declenche_pas_de_capture():
    assert kinds("Capture. Annule la capture.") == [
        ("capture", "capture", True),
        ("cancel", "annule la capture", True),
    ]


def test_point_suivant():
    assert kinds("Point suivant. Le menu") == [("point", "point suivant", True)]


def test_capture_d_ecran_ne_compte_qu_une_fois():
    actions = detect(words("fais une capture d'écran ici"), TRIGGERS, KEPT)
    assert [(a.kind, a.words) for a in actions] == [("capture", (2, 3))]


def test_moment_de_la_capture_est_la_fin_du_mot():
    w = words("Regarde ici")
    assert detect(w, TRIGGERS, KEPT)[0].t == w[0].end


def test_commandes_desactivables():
    assert detect(words("Point suivant."), TRIGGERS, KEPT, commands=False) == []
