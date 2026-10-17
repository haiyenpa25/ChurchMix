"""
mix_assistant package:
- Voice Activity Detection (VAD) & Silence Hold
- Anti-Clipping Guard
- Conservative Speech Leveler (Inspired by M32LiveConsoleTool with Church Safety Constraints)
"""

from .leveler import (
    VoiceActivityState,
    VoiceActivityDetector,
    AntiClippingGuard,
    SpeechLeveler,
    LevelerAction,
)
from .broadcast_meter import (
    apply_k_weighting,
    compute_momentary_lufs,
    compute_short_term_lufs,
    compute_integrated_lufs,
    compute_true_peak_dbtp,
    LoudnessReport,
    BroadcastMixGuard,
)
from .gain_staging import (
    GainStagingAdvisor,
    GainStagingReport,
    trim_to_x32,
    x32_to_trim,
)
from .automixer import (
    DuganSpeechAutomixer,
    AutomixerReport,
    ChannelAutomixState,
)
from .listening_test import (
    ListeningTestCriteria,
    ListeningEvaluation,
    BlindABSession,
    ListeningTestEngine,
)
from .bleed_analyzer import (
    ExpanderSettings,
    CrossTalkReport,
    StageBleedAdvisor,
)
from .monitor_inspector import (
    P16SlotInfo,
    ChannelBusSend,
    MixBusSummary,
    MonitorMatrixAuditReport,
    MonitorMatrixInspector,
    x32_to_bus_level_db,
    bus_level_db_to_x32,
)

__all__ = [
    "VoiceActivityState",
    "VoiceActivityDetector",
    "AntiClippingGuard",
    "SpeechLeveler",
    "LevelerAction",
    "apply_k_weighting",
    "compute_momentary_lufs",
    "compute_short_term_lufs",
    "compute_integrated_lufs",
    "compute_true_peak_dbtp",
    "LoudnessReport",
    "BroadcastMixGuard",
    "GainStagingAdvisor",
    "GainStagingReport",
    "trim_to_x32",
    "x32_to_trim",
    "DuganSpeechAutomixer",
    "AutomixerReport",
    "ChannelAutomixState",
    "ListeningTestCriteria",
    "ListeningEvaluation",
    "BlindABSession",
    "ListeningTestEngine",
    "ExpanderSettings",
    "CrossTalkReport",
    "StageBleedAdvisor",
    "P16SlotInfo",
    "ChannelBusSend",
    "MixBusSummary",
    "MonitorMatrixAuditReport",
    "MonitorMatrixInspector",
    "x32_to_bus_level_db",
    "bus_level_db_to_x32",
]


