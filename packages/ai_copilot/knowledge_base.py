"""
AI Copilot Knowledge Base & Retrieval-Augmented Generation (RAG) Engine.
Provides Vietnamese church sound engineering guidance, acoustic diagnostics, and
troubleshooting SOPs without allowing direct OSC mutations.
"""
from __future__ import annotations
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple


def strip_accents(text: str) -> str:
    """Strip Vietnamese accents for resilient keyword search."""
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return text.replace('đ', 'd').replace('Đ', 'D').lower()


@dataclass
class KnowledgeArticle:
    id: str
    title: str
    category: str
    keywords: List[str]
    summary_vi: str
    detailed_steps_vi: List[str]
    citations: List[str]
    confidence_score: float = 0.95


KNOWLEDGE_DATABASE: List[KnowledgeArticle] = [
    KnowledgeArticle(
        id="ART-001",
        title="Nguyên Tắc Xử Lý Hú (Feedback) & Giữ Chất Giọng",
        category="FEEDBACK_PREVENTION",
        keywords=["hú", "feedback", "rít", "rú", "hu", "chong hu", "tieng rit"],
        summary_vi="Chống hú triệt để phải bắt đầu từ vật lý và gain structure, không bao giờ dùng EQ cắt rộng làm méo giọng hát.",
        detailed_steps_vi=[
            "1. Bố trí vật lý: Yêu cầu ca sĩ đứng sau loa chính (FOH), hướng micro tránh xa loa monitor sàn (Wedge).",
            "2. Kiểm tra búp sóng: Micro Cardioid nhạy nhất phía trước và triệt tiêu âm thanh ở góc 180° phía sau đuôi micro.",
            "3. Gain Structure: Đặt gain preamp sao cho giọng hát lớn nhất đạt đỉnh trong khoảng -18 dBFS đến -12 dBFS trên mixer; tránh đẩy gain quá cao để bù fader nhỏ.",
            "4. HPF (Lọc trầm): Luôn bật Low-cut ở 80 - 100 Hz trên toàn bộ micro giọng hát để loại bỏ cộng hưởng cơ học và tiếng gió.",
            "5. Surgical Notch: Nếu xác nhận tần số hú, chỉ dùng bộ lọc cắt cực hẹp (Q >= 6.0) với độ sâu vừa phải (-3 dB đến -4.5 dB). Tuyệt đối không dùng EQ rộng làm mỏng chất giọng ca sĩ!",
        ],
        citations=["Yamaha Sound Reinforcement Handbook", "ChurchMix Master Plan Sec 3.1"],
    ),
    KnowledgeArticle(
        id="ART-002",
        title="Cân Chỉnh Micro Mục Sư Rõ Lời & Khử Om Phòng",
        category="PASTOR_SPEECH",
        keywords=["mục sư", "muc su", "bài giảng", "bai giang", "rõ lời", "ro loi", "giảng luận", "tieng noi"],
        summary_vi="Tối ưu độ rõ tiếng Việt của giọng giảng luận bằng cách lọc đục 250Hz và làm sáng phụ âm tại 2.8kHz.",
        detailed_steps_vi=[
            "1. HPF: Đặt lọc trầm ở 85 Hz (độ dốc 12dB/oct) để loại trừ tiếng dộng bục giảng và rung động sàn gỗ.",
            "2. Low-Mid: Cắt nhẹ -1.8 dB tại 250 Hz (Q = 1.5) để loại trừ độ đục và tiếng vang om phòng đặc trưng của nhà thờ.",
            "3. High-Mid: Tăng nhẹ +1.2 dB tại 2.8 kHz (Q = 1.2) để tăng độ nét của các phụ âm tiếng Việt (t, ch, tr, s, x).",
            "4. High: Kệ High-Shelf nhẹ ở 10 kHz (+1.0 dB) tạo độ thông thoáng không gian.",
            "5. Dynamics: Cài đặt Compressor tỉ lệ 2.5:1, Threshold -18 dBFS, Attack 25ms, Release 120ms giúp kiểm soát khi Mục sư xúc động nói lớn.",
            "6. Silence Hold: Bộ trợ lý ChurchMix sẽ tự động đóng băng fader khi Mục sư dừng nói, không tự kéo ồn nền phòng lên.",
        ],
        citations=["Speech Intelligibility in Worship Spaces", "ChurchMix Master Plan Sec 3.3"],
    ),
    KnowledgeArticle(
        id="ART-003",
        title="Bất Biến Bảo Vệ Cổng DL16 #11 (Talkback Ban Nhạc)",
        category="TALKBACK_PROTECTION",
        keywords=["talkback", "p16", "dl16", "cổng 11", "cong 11", "bảo vệ", "in 11", "channel 11"],
        summary_vi="Cổng vật lý DL16 Input 11 dành riêng cho micro nội bộ ban nhạc, tuyệt đối cách ly khỏi loa FOH hội trường.",
        detailed_steps_vi=[
            "1. Bất biến bất khả xâm phạm: Tín hiệu từ DL16 In 11 CHỈ ĐƯỢC PHÉP dẫn vào Ultranet P16 Slot 11 cho tai nghe In-Ear ban nhạc.",
            "2. Cách ly FOH: Tuyệt đối không cho phép gán cổng này vào Main L/R, Mono Center, hoặc bất kỳ Matrix ra loa hội trường.",
            "3. Cơ chế Safety Gate: Bất kỳ đề xuất hay lệnh OSC nào cố tình mở /ch/11/mix/st hay gán route ra FOH đều bị hệ thống chặn đứng ngay lập tức với lỗi InvariantViolationError.",
            "4. Thao tác kiểm tra: Vào Wizard 1 (Kiểm kê) hoặc bấm nút DL16 #11: P16 ONLY trên thanh điều khiển để xác minh trạng thái an toàn.",
        ],
        citations=["ChurchMix Mandatory Agent Rules (AGENTS.md Rule 5)", "Behringer X32 Routing Guide"],
    ),
    KnowledgeArticle(
        id="ART-004",
        title="Đo Âm Học Hội Trường & Quy Tắc No-Boost-in-Nulls",
        category="ACOUSTIC_MEASUREMENT",
        keywords=["đo âm học", "do am hoc", "osm", "hàm truyền", "transfer function", "coherence", "no boost", "null"],
        summary_vi="Không bao giờ dùng EQ để tăng bù các hố triệt tiêu pha âm học vì sẽ làm quá tải loa và tăng méo tiếng.",
        detailed_steps_vi=[
            "1. Đo hàm truyền H1 hai kênh: Sử dụng tín hiệu tham chiếu (Pink Noise) so sánh với micro đo đặt ở vị trí khán thính giả.",
            "2. Kiểm tra Coherence: Chỉ xem xét đáp tuyến tại các dải tần có Coherence > 0.65; vùng Coherence thấp là do phản xạ phòng hoặc nhiễu không gian.",
            "3. Quy tắc No-Boost-in-Nulls: Các hố sâu triệt tiêu do giao thoa sóng pha ngược (Phase Cancellation) KHÔNG ĐƯỢC PHÉP tăng boost EQ.",
            "4. Xử lý triệt tiêu pha: Khắc phục bằng cách dịch chuyển vị trí loa, căn chỉnh độ trễ Delay (Time Alignment), hoặc bố trí vật liệu tiêu âm thay vì vặn EQ.",
        ],
        citations=["Bob McCarthy - Sound Systems: Design and Optimization", "ChurchMix Rule 4.2"],
    ),
    KnowledgeArticle(
        id="ART-005",
        title="Quy Trình Kiểm Tra Trước Giờ Lễ (Sunday Line Check SOP)",
        category="LINE_CHECK",
        keywords=["line check", "trước giờ lễ", "truoc gio le", "kiem tra", "pin", "stagebox", "aes50"],
        summary_vi="4 bước kiểm tra vật lý bắt buộc hoàn thành 30 phút trước khi buổi lễ bắt đầu.",
        detailed_steps_vi=[
            "1. Kiểm tra pin micro không dây: Đảm bảo điện áp còn tối thiểu 2 vạch hoặc thay pin Alkaline mới cho micro Mục sư và Ca đoàn.",
            "2. Đồng bộ Stagebox DL16: Đèn AES50 A trên X32 và DL16 phải có màu XANH LÁ (Clock 48kHz đồng bộ hoàn hảo).",
            "3. Kiểm tra tai nghe P16: Nhạc công kiểm tra âm thanh trong trẻo trên cả 3 bộ P16-HQ, nghe rõ Talkback từ Kênh 11.",
            "4. Line Check toàn bộ 32 kênh: Mở Wizard 2 trên ChurchMix Console để quét trạng thái fader, mute và routing của từng line.",
        ],
        citations=["ChurchMix Operator SOP W2", "Sunday Service Technical Checklist"],
    ),
    KnowledgeArticle(
        id="ART-006",
        title="Pha Trộn Ban Nhạc Thờ Phượng & Tôn Vinh Giọng Ca Chính",
        category="BAND_MIXING",
        keywords=["ban nhạc", "ban nhac", "guitar", "piano", "bass", "trống", "keys", "mix nhạc"],
        summary_vi="Tạo không gian tần số riêng cho từng nhạc cụ để nhạc đệm hòa quyện mà không lấn át giọng thờ phượng.",
        detailed_steps_vi=[
            "1. Giọng hát chính (Ch 3, 4): Chiếm vị trí trung tâm trong dải 1 kHz - 4 kHz; các nhạc cụ khác cần nhường chỗ ở dải này.",
            "2. Piano (Ch 7, 8): Cắt nhẹ ở 300 Hz để tránh đục và mở pan Stereo nhẹ (L30 / R30) tạo không gian rộng mở.",
            "3. Acoustic Guitar (Ch 6): Bật HPF ở 100 Hz, cắt nhẹ -2.5 dB tại 3.5 kHz để tiếng gảy đàn mộc êm dịu, không bị đanh gắt chát chúa.",
            "4. Bass Guitar (Ch 9) & Trống Kick (Ch 12): Tách dải tần: Kick lấy lực 55-60 Hz, Bass lấy độ dày 80-120 Hz để không triệt tiêu nhau.",
            "5. Ca đoàn (Ch 5): Bật HPF ở 120 Hz, nén nhẹ với Compressor để bè hòa đều, đứng phía sau nâng đỡ người đơn ca.",
        ],
        citations=["Modern Church Audio Engineering", "Mixing for Contemporary Worship"],
    ),
    KnowledgeArticle(
        id="ART-007",
        title="Nút Khẩn Cấp STOP AUTO & Khóa An Toàn Hệ Thống",
        category="SAFETY_CONTROLLER",
        keywords=["stop auto", "khẩn cấp", "khan cap", "dừng", "panic", "an toàn", "read only"],
        summary_vi="Nút STOP AUTO lập tức khóa chặt toàn bộ lệnh tự động và bảo toàn trạng thái hiện tại của bàn trộn.",
        detailed_steps_vi=[
            "1. Chức năng tức thời: Bấm nút STOP AUTO màu đỏ trên góc màn hình sẽ lập tức hủy bỏ mọi giao dịch đang chờ xử lý.",
            "2. Khóa Read-Only: Ép buộc kết nối X32 trở về chế độ READ_ONLY_MODE = True, không một lệnh ghi nào có thể lọt ra mixer.",
            "3. Thời gian đáp ứng: Dưới 50 mili-giây, phản hồi ngay lập tức để người vận hành kiểm soát hoàn toàn bằng tay.",
            "4. Mở lại hệ thống: Bấm nút Resume Auto hoặc gọi API /api/v1/emergency/resume-auto sau khi đã kiểm tra an toàn.",
        ],
        citations=["ChurchMix Safety Architecture", "AGENTS.md Rule 11"],
    ),
]


class ChurchMixCopilot:
    """Intelligent Vietnamese Audio Copilot and RAG Query Engine."""

    def __init__(self, database: Optional[List[KnowledgeArticle]] = None):
        self.articles = database or KNOWLEDGE_DATABASE

    def search_knowledge(self, query: str, top_k: int = 2) -> List[Tuple[KnowledgeArticle, float]]:
        """Search knowledge base using token matching and relevance scoring."""
        clean_q = strip_accents(query)
        q_tokens = set(re.findall(r'\w+', clean_q))

        scores: List[Tuple[KnowledgeArticle, float]] = []

        for art in self.articles:
            score = 0.0
            # Check keywords match
            for kw in art.keywords:
                clean_kw = strip_accents(kw)
                if clean_kw in clean_q:
                    score += 4.0
                else:
                    kw_tokens = set(re.findall(r'\w+', clean_kw))
                    overlap = len(kw_tokens.intersection(q_tokens))
                    if overlap > 0:
                        score += overlap * 1.5

            # Title match
            clean_title = strip_accents(art.title)
            title_tokens = set(re.findall(r'\w+', clean_title))
            title_overlap = len(title_tokens.intersection(q_tokens))
            score += title_overlap * 2.0

            if score > 0:
                scores.append((art, score))

        # Sort descending by score
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def answer_question(self, question: str, live_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Answer an operator query with citation and relevant live telemetry context.
        Strict invariant: A proposal is never a command (Rule 7).
        """
        matches = self.search_knowledge(question, top_k=2)

        context_notes = []
        if live_context:
            if live_context.get("stop_auto"):
                context_notes.append("⚠️ **CẢNH BÁO:** Hệ thống hiện đang ở trạng thái STOP AUTO (Khóa khẩn cấp).")
            if live_context.get("feedback_alerts"):
                fa = live_context["feedback_alerts"]
                if len(fa) > 0:
                    alert_desc = ", ".join([f"Kênh {a.get('channel_id', '?')} ({a.get('freq_hz', 0):.0f}Hz)" for a in fa])
                    context_notes.append(f"🚨 **Cảnh báo hú trực tiếp:** Phát hiện rủi ro tại {alert_desc}. Cần kiểm tra ngay!")
            if live_context.get("talkback_safe") is not None:
                tb_status = "Đang cách ly an toàn 100%" if live_context["talkback_safe"] else "CẢNH BÁO NGUY HIỂM: Rò rỉ FOH!"
                context_notes.append(f"🛡️ **Trạng thái Talkback DL16 #11:** {tb_status}")

        if not matches:
            # Fallback general answer
            answer_text = (
                f"Trợ lý Âm thanh ChurchMix đã tiếp nhận câu hỏi: '{question}'.\n\n"
                "**Khuyến nghị chung:**\n"
                "• Luôn ưu tiên vị trí micro, khoảng cách nguồn âm và kỹ thuật của người nói trước khi can thiệp EQ.\n"
                "• Không tự ý kích tăng âm lượng trên các dải tần bị hố triệt tiêu pha âm học.\n"
                "• Mọi thay đổi thông số đều cần được nghe thử A/B so sánh và có sự đồng ý của kỹ thuật viên trực lễ."
            )
            citations = ["ChurchMix General Sound Guidelines"]
            primary_category = "GENERAL_GUIDANCE"
        else:
            best_art, _ = matches[0]
            primary_category = best_art.category
            citations = best_art.citations

            lines = [f"**{best_art.title}**", f"*{best_art.summary_vi}*\n"]
            lines.extend(best_art.detailed_steps_vi)

            if len(matches) > 1:
                sec_art, _ = matches[1]
                lines.append(f"\n💡 **Tham khảo thêm:** {sec_art.title} ({sec_art.summary_vi})")

            answer_text = "\n".join(lines)

        if context_notes:
            answer_text = "\n\n".join(context_notes) + "\n\n" + answer_text

        return {
            "question": question,
            "answer": answer_text,
            "category": primary_category,
            "citations": citations,
            "is_authoritative": len(matches) > 0,
            "disclaimer": "AI chỉ hướng dẫn kỹ thuật; mọi thay đổi phải được người vận hành phê duyệt (Rule 7).",
        }
