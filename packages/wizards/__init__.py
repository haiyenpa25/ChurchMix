"""
wizards package:
- 7 Guided Sound Engineering Wizards according to Master Plan Section 7:
  * Wizard 1: Connect & Inventory (Full Markdown Audit & Freeze Protected Routes)
  * Wizard 2: Pre-service Line Check (Mutes, clips, talkback isolation, battery & cable checklist)
  * Wizard 3: Vocal/Speech Calibration
  * Wizard 4: Room/PA Calibration (Transfer function & no-boost-null)
  * Wizard 5: Feedback Ring-out (Safe rehearsal check)
  * Wizard 6: Live Service Assistant
  * Wizard 7: End-of-service Review (Full report generation)
"""

from .service import (
    WizardService,
    LineCheckItem,
    PreServiceLineCheckResult,
)

__all__ = [
    "WizardService",
    "LineCheckItem",
    "PreServiceLineCheckResult",
]
