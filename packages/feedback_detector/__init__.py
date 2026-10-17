"""
feedback_detector package:
- Multi-evidence acoustic feedback detection
- Harmonic overtone rejection to prevent false alarms on held singing notes or organ
- Confidence scoring and conservative recommendation generator
"""

from .detector import FeedbackCandidate, FeedbackDetector

__all__ = ["FeedbackCandidate", "FeedbackDetector"]
