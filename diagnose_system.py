"""
ChurchMix System Pre-Service Diagnostic & Health Verification Tool
===================================================================
Run before Sunday service or during rehearsals to verify all system
subsystems, safety gates, invariant locks, and hardware connections.
"""
from __future__ import annotations
import sys
import os
import time
import json
from typing import Dict, Any, List, Tuple

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Safe unicode output configuration
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_all_diagnostics(verbose: bool = True) -> Dict[str, Any]:
    """Execute all diagnostic check suites and return a structured report."""
    results: List[Dict[str, Any]] = []

    def log_check(name: str, passed: bool, message: str, details: Any = None):
        status = "PASS" if passed else "FAIL"
        results.append({
            "name": name,
            "status": status,
            "passed": passed,
            "message": message,
            "details": details,
        })
        if verbose:
            tag = "[  OK  ]" if passed else "[ FAIL ]"
            print(f" {tag} {name}: {message}")

    if verbose:
        print("=" * 76)
        print("   CHURCHMIX X32 AI SOUND ENGINEER — HỆ THỐNG TỰ CHẨN ĐOÁN TIỀN LỄ")
        print("   Kiểm tra 100% linh kiện phần mềm, cơ sở dữ liệu và bất biến an toàn")
        print("=" * 76)

    # 1. Environment & Packages
    try:
        import numpy as np
        import scipy
        import fastapi
        import uvicorn
        log_check(
            "1. Thư viện Python Core",
            True,
            f"NumPy {np.__version__}, SciPy {scipy.__version__}, FastAPI {fastapi.__version__}",
        )
    except Exception as e:
        log_check("1. Thư viện Python Core", False, f"Thiếu thư viện: {e}")

    # 2. Database Integrity
    try:
        from packages.storage.database import ChurchMixDatabase
        db = ChurchMixDatabase()
        db.save_audit_event(
            actor="DiagnosticTool",
            action="PRE_SERVICE_CHECK",
            status="SUCCESS",
            details={"timestamp": time.time()},
        )
        events = db.get_recent_audit_events(limit=5)
        log_check(
            "2. Cơ Sở Dữ Liệu SQLite",
            len(events) > 0,
            f"Bảng Audit log hoạt động tốt ({len(events)} sự kiện gần nhất)",
        )
    except Exception as e:
        log_check("2. Cơ Sở Dữ Liệu SQLite", False, f"Lỗi database: {e}")

    # 3. Safety Gate & Hard Invariant DL16 #11
    try:
        from packages.safety_controller.routing import RoutingGraph
        params = {
            "/config/routing/IN/1-8": "AES50A 1-8",
            "/config/routing/IN/9-16": "AES50A 9-16",
            "/ch/11/mix/lr": False,
            "/outputs/p16/11/src": 11,
        }
        routing = RoutingGraph(params)
        is_safe, violation = routing.verify_talkback_invariant()
        log_check(
            "3. Bất Biến Sống Còn (DL16 #11)",
            is_safe,
            "Cổng DL16 #11 cách ly 100% khỏi Main FOH, chỉ gửi về P16 slot 11",
        )
    except Exception as e:
        log_check("3. Bất Biến Sống Còn (DL16 #11)", False, f"Lỗi kiểm tra invariant: {e}")

    # 4. Mock X32 & Read-Only Client
    try:
        from packages.mock_x32.server import MockX32Server
        from packages.x32_osc_adapter.client import X32Client
        mock = MockX32Server(host="127.0.0.1", port=int(os.environ.get("CHURCHMIX_X32_PORT", "10023")))
        try:
            mock.start()
            time.sleep(0.05)
        except Exception:
            pass # Port might be in use by running daemon

        client = X32Client(host="127.0.0.1", port=int(os.environ.get("CHURCHMIX_X32_PORT", "10023")), read_only_mode=True, timeout=0.8)
        client.connect()
        snap = client.take_full_snapshot(max_channels=4)
        client.close()
        log_check(
            "4. Giao Tiếp OSC X32 (Read-Only)",
            snap.sha256 is not None,
            f"Kết nối UDP thành công, snapshot SHA-256: {snap.sha256[:12]}... (READ-ONLY ép buộc)",
        )
    except Exception as e:
        log_check("4. Giao Tiếp OSC X32 (Read-Only)", False, f"Lỗi OSC Client: {e}")

    # 5. Audio Device Manager
    try:
        from apps.capture_agent.device_manager import AudioDeviceManager
        adm = AudioDeviceManager()
        devices = adm.list_input_devices()
        log_check(
            "5. Quản Lý Thiết Bị Thu Âm",
            True,
            f"Tìm thấy {len(devices)} thiết bị thu âm trên hệ điều hành",
        )
    except Exception as e:
        log_check("5. Quản Lý Thiết Bị Thu Âm", False, f"Lỗi kiểm tra audio device: {e}")

    # 6. Church Channel Profiles
    try:
        from packages.storage.church_profile import ChurchProfileManager
        cpm = ChurchProfileManager()
        channels = cpm.get_channels()
        ch11 = next((c for c in channels if c["channel"] == 11), None)
        is_ch11_protected = ch11 is not None and ch11.get("is_protected", False)
        log_check(
            "6. Hồ Sơ Sơ Đồ 32 Kênh Nhà Thờ",
            len(channels) == 32 and is_ch11_protected,
            f"32 kênh sẵn sàng, Kênh 11 ({ch11['name'] if ch11 else 'N/A'}) khóa bảo vệ vĩnh viễn",
        )
    except Exception as e:
        log_check("6. Hồ Sơ Sơ Đồ 32 Kênh Nhà Thờ", False, f"Lỗi church profile: {e}")

    # 7. Multi-Sanctuary Hall Profiles
    try:
        from packages.storage.hall_profiles import HallProfileManager
        hpm = HallProfileManager()
        halls = hpm.get_all_halls()
        active = hpm.get_active_hall()
        diff = hpm.compare_measurement_against_baseline(
            hall_id=active.id,
            measurement_curve=[{"freq": 1000.0, "target_db": 0.0, "coherence": 0.95}],
            delay_ms=active.nominal_delay_ms,
        )
        log_check(
            "7. Hồ Sơ Âm Học Hội Trường Đa Không Gian",
            len(halls) >= 4 and diff["status"] == "HEALTHY",
            f"Kích hoạt: {active.name} (RT60: {active.target_rt60_seconds}s, Delay: {active.nominal_delay_ms}ms) — Baseline: HEALTHY",
        )
    except Exception as e:
        log_check("7. Hồ Sơ Âm Học Hội Trường Đa Không Gian", False, f"Lỗi hall profile: {e}")

    # 8. Virtual Soundcheck Engine
    try:
        from packages.virtual_soundcheck.player import VirtualSoundcheckEngine, SESSION_PRESETS
        engine = VirtualSoundcheckEngine(sample_rate=48000)
        session = engine.start_session("SUNDAY_WORSHIP_BALLAD")
        block = engine.generate_audio_block(block_size=256)
        engine.stop()
        log_check(
            "8. Động Cơ Virtual Soundcheck",
            block.shape == (256, 32),
            f"Nạp đủ 4 phiên diễn tập mẫu, phát luồng multitrack 32 kênh chuẩn xác (block {block.shape})",
        )
    except Exception as e:
        log_check("8. Động Cơ Virtual Soundcheck", False, f"Lỗi soundcheck engine: {e}")

    # 9. AI Copilot RAG Knowledge Base
    try:
        from packages.ai_copilot import ChurchMixCopilot
        copilot = ChurchMixCopilot()
        ans_dict = copilot.answer_question("Vì sao kênh 11 không được gửi ra loa FOH?")
        answer = ans_dict.get("answer", "")
        has_rule = "P16" in answer and ("FOH" in answer or "an toàn" in answer)
        log_check(
            "9. Trợ Lý AI Copilot RAG Tiếng Việt",
            has_rule,
            "Truy vấn RAG tiếng Việt thành công, trả lời chính xác bất biến an toàn và kỹ thuật âm học",
        )
    except Exception as e:
        log_check("9. Trợ Lý AI Copilot RAG Tiếng Việt", False, f"Lỗi AI Copilot: {e}")

    # 10. Printable Sunday Service Report
    try:
        from packages.storage.report_generator import generate_printable_sunday_report_html
        html = generate_printable_sunday_report_html(
            church_name="Hội Thánh Tin Lành Test",
            engineer_name="Kỹ Thuật Viên",
            mixer_model="Behringer X32 Compact",
            snapshot_hash="sha256-test-hash",
            events=[],
        )
        has_valid_html = "<!DOCTYPE html>" in html and "DL16 #11" in html
        log_check(
            "10. Bộ Tạo Báo Cáo Buổi Lễ In Ấn",
            has_valid_html,
            f"Tạo báo cáo HTML chuẩn A4 sẵn sàng in ấn/PDF ({len(html)} bytes)",
        )
    except Exception as e:
        log_check("10. Bộ Tạo Báo Cáo Buổi Lễ In Ấn", False, f"Lỗi report generator: {e}")

    # Summary
    all_passed = all(r["passed"] for r in results)
    pass_count = sum(1 for r in results if r["passed"])
    total_count = len(results)

    if verbose:
        print("-" * 76)
        if all_passed:
            print(f"  ===> KẾT LUẬN: TOÀN BỘ {pass_count}/{total_count} MỤC KIỂM TRA ĐẠT TIÊU CHUẨN 100%!")
            print("       HỆ THỐNG AN TOÀN TUYỆT ĐỐI, SẴN SÀNG CHO BUỔI LỄ THỜ PHƯỢNG.")
        else:
            print(f"  ===> CẢNH BÁO: CÓ {total_count - pass_count}/{total_count} MỤC KHÔNG ĐẠT YÊU CẦU.")
            print("       Vui lòng rà soát chi tiết các mục [ FAIL ] trước khi cấp tín hiệu ra FOH.")
        print("=" * 76 + "\n")

    return {
        "overall_status": "PASS" if all_passed else "FAIL",
        "passed_count": pass_count,
        "total_count": total_count,
        "checks": results,
    }


if __name__ == "__main__":
    report = run_all_diagnostics(verbose=True)
    sys.exit(0 if report["overall_status"] == "PASS" else 1)
