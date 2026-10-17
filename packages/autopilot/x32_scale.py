"""
X32 fader law: normalized fader value (0.0–1.0) <-> dB.

Piecewise-linear law used by the X32/M32 for channel, bus and main faders:
    f >= 0.5     : dB = f * 40  - 30   (−10 .. +10 dB)
    f >= 0.25    : dB = f * 80  - 50   (−30 .. −10 dB)
    f >= 0.0625  : dB = f * 160 - 70   (−60 .. −30 dB)
    f >  0       : dB = f * 480 - 90   (−90 .. −60 dB)
    f == 0       : −inf (fader down)
Unity (0 dB) is f = 0.75.
"""

from __future__ import annotations

import math

MIN_DB = -90.0
MAX_DB = 10.0


def fader_to_db(f: float) -> float:
    f = min(1.0, max(0.0, float(f)))
    if f >= 0.5:
        return f * 40.0 - 30.0
    if f >= 0.25:
        return f * 80.0 - 50.0
    if f >= 0.0625:
        return f * 160.0 - 70.0
    if f > 0.0:
        return f * 480.0 - 90.0
    return -math.inf


def db_to_fader(db: float) -> float:
    if db is None or db == -math.inf or db <= MIN_DB:
        return 0.0
    db = min(MAX_DB, float(db))
    if db >= -10.0:
        f = (db + 30.0) / 40.0
    elif db >= -30.0:
        f = (db + 50.0) / 80.0
    elif db >= -60.0:
        f = (db + 70.0) / 160.0
    else:
        f = (db + 90.0) / 480.0
    return round(min(1.0, max(0.0, f)), 4)
