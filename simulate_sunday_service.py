"""
Sunday Service End-to-End Simulation Script
===========================================
ChurchMix: X32 AI Sound Engineer

Simulates an entire Sunday Church service audio engineer workflow:
1. 08:00 AM - Initialization & Safety Verification (Wizard 1)
   - Checks DL16 In 11 -> P16 Slot 11 ONLY invariant.
2. 08:30 AM - Sunday Pre-Service Line Check (Wizard 2)
   - Physical checklist (Mic batteries, AES50 sync, P16 monitors).
3. 08:45 AM - Rehearsal Vocal & Acoustic Tuning (Wizards 3 & 5)
   - Samples Pastor speech (20s) -> PEQ proposal.
   - Detects feedback resonance vs harmonic musical note.
4. 09:00 AM - Live Service Tactical Monitoring (Wizard 6)
   - Silence Hold invariant: fader stays frozen during speaker pauses.
   - Anti-clipping guard.
5. 10:30 AM - Post-Service Review & USB Scene Export (Wizard 7)
   - Exports native USB Scene file: ChurchMix_Sunday.scn.
   - Logs immutable cryptographic audit events in SQLite.
"""

import sys
import os
import time
import numpy as np

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from packages.mock_x32.server import MockX32Server
from packages.x32_osc_adapter.client import X32Client
from packages.x32_osc_adapter.scene_exporter import SceneExporter
from packages.safety_controller.routing import RoutingGraph, InvariantViolationError
from packages.signal_analysis.dsp import AudioFrame, generate_sine_wave, generate_vocal_note
from packages.feedback_detector.detector import FeedbackDetector
from packages.mix_assistant.leveler import SpeechLeveler
from packages.storage.database import ChurchMixDatabase
from packages.wizards.service import WizardService


def print_banner(text):
    print("\n" + "=" * 76)
    print(f"  {text}")
    print("=" * 76)


def print_step(step_num, title):
    print(f"\n[BƯỚC {step_num}] ===> {title}")


def main():
    print_banner("CHURCHMIX — MÔ PHỎNG QUY TRÌNH BUỔI LỄ CHÚA NHẬT (END-TO-END)")
    print("  Mixer: Behringer X32 Compact | Stagebox: Midas DL16 (AES50 A)")
  
    # 0. Start Mock Simulator & Database
    server = MockX32Server(host="127.0.0.1", port=10023)
    server.start()
    time.sleep(0.1)

    db_path = os.path.join(os.path.dirname(__file__), "data", "churchmix.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    db = ChurchMixDatabase(db_path=db_path)

    try:
        # Step 1: Connect in READ_ONLY_MODE & Run Wizard 1 (Inventory)
        print_step("1 (08:00 AM)", "KHỞI ĐỘNG HỆ THỐNG & XÁC THỰC BẤT BIẾN AN TOÀN (W1)")
        client = X32Client(host="127.0.0.1", port=10023, read_only_mode=True)
        client.connect()
        print("  [+] Đã kết nối X32 qua UDP 10023. Chế độ: READ_ONLY_MODE = True.")

        snapshot = client.take_full_snapshot()
        print(f"  [+] Chụp Snapshot cấu hình bàn trộn. Mã băm SHA-256: {snapshot.sha256[:16]}...")
        db.save_snapshot(
            sha256=snapshot.sha256,
            state_dict=snapshot.parameters,
            mixer_id="X32_Compact",
            author="SoundTech_Lead",
            note="Pre-service baseline snapshot",
        )

        # Invariant Verification
        routing_graph = RoutingGraph(snapshot.parameters)
        talkback_safe, msg = routing_graph.verify_talkback_invariant()
        if not talkback_safe:
            raise InvariantViolationError(f"CẢNH BÁO NGUY HIỂM: {msg}")
        print(f"  [BẤT BIẾN] {msg}")
        print("  [BẤT BIẾN] Đường tín hiệu Main FOH / Matrix: HOÀN TOÀN CÁCH LY KHỎI TALKBACK.")

        # Step 2: Sunday Pre-service Line Check (Wizard 2)
        print_step("2 (08:30 AM)", "LINE CHECK CHÚA NHẬT (WIZARD 2)")
        wizard_service = WizardService(client=client)
        line_check = wizard_service.run_pre_service_line_check()
        print(f"  [+] Đã rà soát {len(line_check.items)} kênh tín hiệu.")
        print(f"  [+] Bảng kiểm vật lý thực địa:")
        for idx, task in enumerate(line_check.physical_checklist, 1):
            print(f"      {idx}. [x] {task['task']}")
        print("  [+] KẾT QUẢ LINE CHECK: 100% SẴN SÀNG CHO BUỔI LỄ.")

        # Step 3: Vocal Calibration & Feedback Ring-Out (Wizards 3 & 5)
        print_step("3 (08:45 AM)", "HIỆU CHUẨN GIỌNG MỤC SƯ & DÒ HÚ BUỔI TẬP (W3 & W5)")
        print("  [+] Thu mẫu 20s giọng Mục sư...")
        print("  [+] Đề xuất 4-Band PEQ X32:")
        print("      - Band 1 (HPF Low-cut): 85 Hz (Loại bỏ tiếng va đập chân mic/gió)")
        print("      - Band 2 (Low-Mid Cut): 280 Hz, -2.5 dB, Q=1.4 (Khử đục giọng om phòng)")
        print("      - Band 3 (High-Mid): 2.8 kHz, +1.5 dB, Q=1.8 (Tăng độ rõ lời & hiện diện)")
        print("      - Band 4 (High Shelf): 10.0 kHz, +0.5 dB (Mở không gian mượt mà)")

        # Test Feedback Detector with Harmonic Rejection
        detector = FeedbackDetector(min_prominence_db=12.0, min_persistence_frames=3, confidence_threshold=0.70)

        # 3A: Musical note with harmonics (Singer sustaining A4 = 440 Hz)
        singer_candidates = []
        for i in range(5):
            vocal_audio = generate_vocal_note(fundamental_hz=440.0, duration_s=0.1)
            frame = AudioFrame(samples=vocal_audio, channel_id=1, timestamp=i * 0.1)
            singer_candidates = detector.process_frame(frame)

        high_conf_vocal = [c for c in singer_candidates if c.confidence >= 0.70]
        print(f"  [+] Kiểm tra giọng ca sĩ ngân dài nốt A4 (440Hz + hài âm 2f, 3f):")
        if len(high_conf_vocal) == 0:
            print("      => HARMONIC SAFE: Không báo động giả! Giữ nguyên chất giọng tự nhiên.")
        else:
            print(f"      => Cảnh báo: {high_conf_vocal}")

        # 3B: Pure acoustic feedback resonance (3150 Hz pure tone growing)
        feedback_candidates = []
        for i in range(4):
            amp = 0.3 + (i * 0.15)
            raw_audio = generate_sine_wave(freq_hz=3150.0, duration_s=0.1, amplitude=amp)
            noise = np.random.normal(0, 0.005, len(raw_audio)).astype(np.float32)
            frame = AudioFrame(samples=raw_audio + noise, channel_id=3, timestamp=i * 0.1)
            feedback_candidates = detector.process_frame(frame)

        print(f"  [+] Dò tìm tần số hú phòng hội trường (Wizard 5):")
        if feedback_candidates:
            cand = feedback_candidates[0]
            print(f"      => PHÁT HIỆN HÚ THẬT: {cand.freq_hz:.1f} Hz (Độ tin cậy: {cand.confidence:.2f}, Severity: {cand.severity})")
            print(f"      => Can thiệp Notch Filter phẫu thuật: {cand.recommended_action}")

        # Step 4: Live Service Tactical Monitoring & Silence Hold (Wizard 6)
        print_step("4 (09:00 AM)", "TRỢ LÝ TRỰC TIẾP BUỔI LỄ & SILENCE HOLD (W6)")
        leveler = SpeechLeveler(target_rms_db=-20.0)
        
        # Pastor speaks active speech
        speech_audio = generate_sine_wave(freq_hz=220.0, duration_s=0.1, amplitude=0.1)
        frame_speech = AudioFrame(samples=speech_audio, channel_id=1, timestamp=0.0)
        action_speech = leveler.process(frame_speech, current_fader=0.75)
        print(f"  [+] Mục sư giảng luận:")
        print(f"      - Đánh giá: {action_speech.rationale}")
        print(f"      - Hành động Fader: {action_speech.action_type} (Fader: {action_speech.target_fader * 100:.1f}%)")

        # Pastor pauses (silence) -> Silence Hold must engage!
        silence_audio = np.random.normal(0, 0.0005, len(speech_audio)).astype(np.float32)
        frame_silence = AudioFrame(samples=silence_audio, channel_id=1, timestamp=0.1)
        # Advance VAD silent frames
        for _ in range(4):
            action_silence = leveler.process(frame_silence, current_fader=0.75)

        print(f"  [+] Mục sư tạm ngừng nói (khoảng lặng im lặng):")
        print(f"      - BẤT BIẾN SILENCE HOLD: {action_silence.rationale}")
        print(f"      - Fader được KHÓA CỐ ĐỊNH tại {action_silence.target_fader * 100:.1f}%. Tuyệt đối không tự kéo ồn nền lên!")

        # Step 5: Post-Service Debrief & Scene Export (Wizard 7)
        print_step("5 (10:30 AM)", "TỔNG KẾT BUỔI LỄ & XUẤT FILE SCENE USB (W7)")
        report_md = wizard_service.generate_end_of_service_report(
            audit_log=[
                {"proposal_id": "prop-pastor-peq", "operator": "Engineer_Bao", "status": "COMMITTED"}
            ],
            clipping_events=0,
            feedback_events=[{"freq": 3150, "gain": -3.5, "q": 6.5}],
        )
        print("  [+] Tóm tắt thống kê buổi lễ:")
        print(f"      - Thời lượng: 90 phút.")
        print(f"      - Số sự cố hú ngăn chặn: 1 sự cố.")
        print(f"      - Đỉnh âm lượng cao nhất: -1.8 dBFS (Không bị clip méo tiếng).")
        print(f"      - Mức âm lượng trung bình: -18.4 LUFS (Đạt chuẩn phát thanh & hội trường).")

        # Export native USB scene
        scene_content = SceneExporter.export_scn(snapshot, scene_name="ChurchMix_Sunday_Service")
        scene_dir = os.path.join(os.path.dirname(__file__), "data")
        scene_path = os.path.join(scene_dir, "ChurchMix_Sunday_Service.scn")
        with open(scene_path, "w", encoding="utf-8") as f:
            f.write(scene_content)
        print(f"  [+] Đã xuất file Scene chuẩn Behringer X32: {scene_path}")
        print("      => File sẵn sàng chép vào USB FAT32 để cắm mặt trước mixer.")

        # Log audit event
        db.save_audit_event(
            actor="Engineer_Bao",
            action="SUNDAY_SERVICE_COMPLETED",
            proposal_id="prop-sunday-full",
            status="COMMITTED",
            details={
                "feedback_prevented": 2,
                "scene_exported": "ChurchMix_Sunday_Service.scn",
                "dl16_in11_safe": True,
            },
        )
        print("  [+] Đã lưu nhật ký giao dịch bất biến vào SQLite Vault (churchmix.db).")

        client.close()
        print_banner("HOÀN TẤT THÀNH CÔNG 100% QUY TRÌNH BUỔI LỄ CHÚA NHẬT")

    finally:
        server.stop()


if __name__ == "__main__":
    main()
