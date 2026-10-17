"""
AI Copilot Package for ChurchMix.
Provides RAG Knowledge Base and Vietnamese Audio Sound Engineer Copilot.
"""
from .knowledge_base import (
    ChurchMixCopilot,
    KnowledgeArticle,
    KNOWLEDGE_DATABASE,
    strip_accents,
)

__all__ = [
    "ChurchMixCopilot",
    "KnowledgeArticle",
    "KNOWLEDGE_DATABASE",
    "strip_accents",
]
