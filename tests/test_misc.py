import wave

import numpy as np
import pytest

from claudepilot import sounds
from claudepilot.winapi import MOD_ALT, MOD_CONTROL, MOD_SHIFT, parse_hotkey


def test_raccourcis():
    assert parse_hotkey("Ctrl+Alt+Space") == (MOD_CONTROL | MOD_ALT, 0x20)
    assert parse_hotkey("F8") == (0, 0x77)
    assert parse_hotkey("ctrl+shift+r") == (MOD_CONTROL | MOD_SHIFT, ord("R"))
    for bad in ("", "Ctrl+", "Hyper+X", "Ctrl+Alt+Machin"):
        with pytest.raises(ValueError):
            parse_hotkey(bad)


def test_tous_les_bruitages_sont_propres(tmp_path, monkeypatch):
    monkeypatch.setattr(sounds, "SOUND_DIR", tmp_path)
    for name, (peak_db, _priority) in sounds.SOUNDS.items():
        with wave.open(str(sounds._file(name, 100))) as w:
            assert w.getframerate() == sounds.SR
            x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2") / 32767
        assert 0.05 < len(x) / sounds.SR < 2.0, name
        assert abs(20 * np.log10(np.max(np.abs(x))) - peak_db) < 0.5, name  # niveau prévu, sans saturation
        assert abs(np.mean(x)) < 0.01, name
