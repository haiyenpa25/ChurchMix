"""
Sprint 14 Test Suite:
AI Copilot RAG Knowledge Base & Vietnamese Audio Assistant
==========================================================
Tests:
1. Vietnamese accent stripping & phonetic matching
2. Knowledge article retrieval across 7 core church sound categories
3. Context-aware answer generation (incorporating active feedback alerts & invariant status)
4. Rule 7 compliance verification (advisory only, no direct OSC commands)
5. FastAPI /api/v1/copilot/ask endpoint integration
"""

import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from packages.ai_copilot.knowledge_base import (
    ChurchMixCopilot,
    strip_accents,
    KNOWLEDGE_DATABASE,
)
from apps.api.main import app
from fastapi.testclient import TestClient


class TestSprint14AICopilotRAG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.copilot = ChurchMixCopilot()
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_strip_accents(self):
        """Verify Vietnamese diacritic removal for resilient fuzzy searching."""
        self.assertEqual(strip_accents("Mục sư giảng luận"), "muc su giang luan")
        self.assertEqual(strip_accents("Cắt hú dải trầm"), "cat hu dai tram")
        self.assertEqual(strip_accents("Đồng bộ Stagebox"), "dong bo stagebox")

    def test_search_feedback_prevention(self):
        """Queries about feedback or squeals retrieve the anti-feedback article."""
        matches = self.copilot.search_knowledge("Làm sao để xử lý micro bị rít hú?")
        self.assertTrue(len(matches) > 0)
        art, score = matches[0]
        self.assertEqual(art.id, "ART-001")
        self.assertEqual(art.category, "FEEDBACK_PREVENTION")

    def test_search_pastor_speech_clarity(self):
        """Queries about sermon clarity retrieve the pastor speech calibration article."""
        matches = self.copilot.search_knowledge("Chỉnh tiếng Mục sư cho rõ lời bài giảng")
        self.assertTrue(len(matches) > 0)
        art, score = matches[0]
        self.assertEqual(art.id, "ART-002")
        self.assertEqual(art.category, "PASTOR_SPEECH")

    def test_search_talkback_dl16_invariant(self):
        """Queries about Talkback or P16 retrieve the DL16 #11 protection article."""
        matches = self.copilot.search_knowledge("Kiểm tra đường truyền Talkback ban nhạc qua cổng DL16 11")
        self.assertTrue(len(matches) > 0)
        art, score = matches[0]
        self.assertEqual(art.id, "ART-003")
        self.assertEqual(art.category, "TALKBACK_PROTECTION")

    def test_search_no_boost_in_nulls(self):
        """Queries about acoustic nulls retrieve the No-Boost-in-Nulls article."""
        matches = self.copilot.search_knowledge("Đo âm học hội trường gặp hố triệt tiêu null có nên tăng EQ?")
        self.assertTrue(len(matches) > 0)
        art, score = matches[0]
        self.assertEqual(art.id, "ART-004")
        self.assertEqual(art.category, "ACOUSTIC_MEASUREMENT")

    def test_answer_with_live_context_injection(self):
        """Live feedback alerts and stop auto state must be dynamically injected into advice."""
        live_ctx = {
            "stop_auto": True,
            "feedback_alerts": [{"channel_id": 3, "freq_hz": 3150.0}],
            "talkback_safe": True,
        }
        resp = self.copilot.answer_question("Làm sao để chỉnh micro ca sĩ?", live_context=live_ctx)

        # Injected warnings check
        self.assertIn("STOP AUTO", resp["answer"])
        self.assertIn("Kênh 3 (3150Hz)", resp["answer"])
        self.assertIn("Talkback DL16 #11", resp["answer"])
        self.assertIn("Đang cách ly an toàn", resp["answer"])
        self.assertIn("Rule 7", resp["disclaimer"])
        self.assertTrue(len(resp["citations"]) > 0)

    def test_rule7_advisory_compliance(self):
        """The Copilot answer must always emphasize operator authority and auditioning."""
        resp = self.copilot.answer_question("Hãy tăng fader kênh 1 lên 3 dB ngay bây giờ!")
        self.assertIn("Rule 7", resp["disclaimer"])
        # Should not claim to execute commands
        self.assertIn("AI chỉ hướng dẫn kỹ thuật", resp["disclaimer"])

    def test_api_copilot_ask_endpoint(self):
        """FastAPI POST /api/v1/copilot/ask returns structured answer with citations."""
        res = self.client.post("/api/v1/copilot/ask", json={
            "question": "Chỉnh micro Mục sư rõ lời",
            "include_live_context": True,
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("85 Hz", data["answer"])
        self.assertIn("250 Hz", data["answer"])
        self.assertEqual(data["category"], "PASTOR_SPEECH")
        self.assertTrue(data["is_authoritative"])
        self.assertTrue(len(data["citations"]) > 0)


if __name__ == "__main__":
    unittest.main()
