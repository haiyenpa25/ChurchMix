"""
Virtual Soundcheck Rehearsal Engine for ChurchMix.
Provides realistic multitrack rehearsal playback for tuning church sound offline.
"""
from packages.virtual_soundcheck.player import (
    VirtualSoundcheckEngine,
    VirtualSoundcheckSession,
    SESSION_PRESETS,
)

__all__ = ["VirtualSoundcheckEngine", "VirtualSoundcheckSession", "SESSION_PRESETS"]
