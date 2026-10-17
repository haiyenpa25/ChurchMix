"""Select and label the actual level/audio source without assuming mixer routing.

Priority: virtual soundcheck (explicit simulation) > fresh X32 meters > USB capture > demo.
"""
import math
import time
import numpy as np

METER_MAX_AGE_S = 0.5


def demo_block(elapsed):
    t = elapsed + np.arange(1024, dtype=np.float32) / 48000
    block = np.zeros((1024, 32), dtype=np.float32)
    for ch in (1, 3, 6, 7, 9, 10, 11):
        level = (-36 if ch == 11 else -14 if ch == 3 else -20) + (2 if ch == 11 else 12 if ch == 3 else 8) * math.sin(elapsed * 1.3 + ch)
        phase = 2 * np.pi * (170 + ch * 70) * t
        tone = (np.sin(phase) + 0.3 * np.sin(3 * phase) + 0.15 * np.sin(5 * phase)) / 1.45
        block[:, ch - 1] = 10 ** (level / 20) * tone
    return block


def collect_signal(soundcheck, worker, elapsed, profiles, meter_reader=None):
    """Return (meters, samples, source). ``meter_reader`` is an optional X32MeterReader."""
    if not soundcheck.is_active and meter_reader is not None:
        snapshot = meter_reader.latest() if meter_reader.is_fresh(METER_MAX_AGE_S) else None
        if snapshot is not None:
            return _collect_x32_meters(snapshot, worker, elapsed, profiles, bool(getattr(meter_reader, "simulated", False)))
        meters, samples, source = _collect_audio(soundcheck, worker, elapsed, profiles)
        source["reasons"].insert(0, "Chưa nhận được meter từ X32; đang dùng nguồn dự phòng" if meter_reader.latest() is None
                                 else f"Meter X32 đã cũ quá {METER_MAX_AGE_S:g} giây; đang dùng nguồn dự phòng")
        return meters, samples, source
    return _collect_audio(soundcheck, worker, elapsed, profiles)


def _fresh_physical_frame(worker, now):
    """A real (non-simulated) USB frame that passes buffer/clock checks, else None."""
    if not worker or not worker.is_running:
        return None
    frame = worker.get_latest_frame()
    if (frame["is_simulated"] or frame["samples"] is None or frame["captured_at"] is None
            or now - frame["captured_at"] > 0.5 or not frame["clock_verified"]
            or frame["overflow_count"] or frame["clock_fault"]):
        return None
    return frame


def _collect_x32_meters(snapshot, worker, elapsed, profiles, simulated):
    """Levels from X32 input meters; audio (RTA/feedback DSP) only from a separate valid buffer.

    X32 meters are peak-style input meters (post-preamp, pre-fader, pre-mute). They carry
    no RMS and no audio, so rms_dbfs stays None and DSP needs another buffer:
    * a valid physical USB capture: its input 1 feeds RTA/feedback, dsp_valid follows its
      tap point; it is labelled separately because USB-to-X32 mapping is still unverified;
    * otherwise, only for the internal mock mixer, the demo block (everything simulated);
    * otherwise no audio: dsp_valid False, rta_available False.
    """
    now = time.monotonic()
    source = {"id": "x32-meters", "valid": True, "simulated": simulated, "reasons": [],
              "label": "Mixer giả lập • meter X32" if simulated else "X32 • meter kênh (sau preamp)",
              "mapping_verified": True, "tap_point": "X32_INPUT_METER", "sample_rate": 48000,
              "clock_verified": None, "meter_age_s": round(max(0.0, now - snapshot["received_at"]), 3),
              "meter_count": snapshot["count"], "rta_available": False, "audio": None}
    levels = {c["channel"]: c["level_dbfs"] for c in snapshot["channels"]}
    meters = [{"channel": ch, "name": profiles.get(ch, {}).get("name", f"Kênh {ch:02d}"),
               "meter_dbfs": levels.get(ch), "rms_dbfs": None} for ch in range(1, 33)]
    frame = _fresh_physical_frame(worker, now)
    if frame is not None:
        block = frame["samples"]
        if block.ndim == 1:
            block = block.reshape(-1, 1)
        source.update(sample_rate=worker.sample_rate, clock_verified=True, rta_available=True,
                      audio={"id": f"capture:{id(worker)}", "label": f"USB Audio • thiết bị {worker.device_id}",
                             "tap_point": worker.tap_point, "input": 1, "mapping_verified": False})
        source["dsp_valid"] = worker.tap_point in ("PRE_EQ", "POST_EQ") and bool(np.all(np.isfinite(block)))
        source["reasons"].append("RTA/feedback lấy từ USB Input 01 (chưa xác nhận tương ứng kênh X32 nào); mức kênh lấy từ meter X32")
        if not source["dsp_valid"]:
            source["reasons"].append("Tap point USB chưa xác nhận; tạm ngừng suy luận DSP/feedback")
        samples = block[:, 0] if block.shape[1] else np.zeros(1024, dtype=np.float32)
        source["spectrum_input"] = 1
    elif simulated:
        block = demo_block(elapsed)
        source.update(clock_verified=True, rta_available=True, dsp_valid=True,
                      audio={"id": "demo", "label": "Demo • dữ liệu mô phỏng", "input": 3, "mapping_verified": False})
        source["reasons"].append("RTA dùng tín hiệu demo; mixer giả lập không có audio")
        samples = block[:, 2]
        source["spectrum_input"] = 3
    else:
        samples = np.zeros(1024, dtype=np.float32)
        source["dsp_valid"] = False
        source["spectrum_input"] = None
        source["reasons"].append("Không có buffer audio hợp lệ đi kèm; RTA/feedback tạm ngừng, chỉ có mức meter")
    return meters, samples, source


def _collect_audio(soundcheck, worker, elapsed, profiles):
    now = time.monotonic()
    source = {"valid": True, "reasons": [], "sample_rate": 48000,
              "mapping_verified": False, "tap_point": "SIMULATED", "clock_verified": True}
    if soundcheck.is_active:
        block = soundcheck.generate_audio_block(block_size=1024)
        source.update(id=f"soundcheck:{soundcheck.current_session.id}", label="Soundcheck ảo", simulated=True,
                      sample_rate=soundcheck.sample_rate)
        peaks = 20 * np.log10(np.maximum(np.max(np.abs(block), axis=0), 1e-7))
        rms = 20 * np.log10(np.maximum(np.sqrt(np.mean(block ** 2, axis=0)), 1e-7))
    elif worker and worker.is_running:
        frame = worker.get_latest_frame()
        block = frame["samples"]
        simulated = frame["is_simulated"]
        source.update(id=f"capture:{id(worker)}", label="USB mô phỏng" if simulated else f"USB Audio • thiết bị {worker.device_id}",
                      simulated=simulated, sample_rate=worker.sample_rate,
                      tap_point="SIMULATED" if simulated else worker.tap_point,
                      clock_verified=frame["clock_verified"], overflow_count=frame["overflow_count"],
                      clock_fault=frame["clock_fault"], capture_error=frame["capture_error"])
        if frame["capture_error"]:
            source["reasons"].append("Không mở được thiết bị thật; đang phát dữ liệu mô phỏng")
        if block is None or frame["captured_at"] is None or now - frame["captured_at"] > 0.5:
            source["valid"] = False
            source["reasons"].append("Buffer chưa có hoặc đã cũ quá 0,5 giây")
        if not simulated and (not frame["clock_verified"] or frame["overflow_count"] or frame["clock_fault"]):
            source["valid"] = False
            source["reasons"].append("Clock chưa xác minh hoặc có lỗi buffer/clock; khởi động lại capture sau khi kiểm tra")
        peaks, rms = frame["peaks"], frame["rms"]
        if block is None:
            block = np.zeros((1024, 0), dtype=np.float32)
    else:
        source.update(id="demo", label="Demo • dữ liệu mô phỏng", simulated=True)
        block = demo_block(elapsed)
        peaks = 20 * np.log10(np.maximum(np.max(np.abs(block), axis=0), 1e-7))
        rms = 20 * np.log10(np.maximum(np.sqrt(np.mean(block ** 2, axis=0)), 1e-7))
    if block.ndim == 1:
        block = block.reshape(-1, 1)
    if not np.all(np.isfinite(block)):
        source["valid"] = False
        source["reasons"].append("Buffer chứa giá trị không hữu hạn")
    source["dsp_valid"] = source["valid"] and (source["simulated"] or source["tap_point"] in ("PRE_EQ", "POST_EQ"))
    if not source["simulated"]:
        source["reasons"].append("Chưa xác nhận USB Input tương ứng với kênh X32/nguồn vật lý nào")
        if not source["dsp_valid"]:
            source["reasons"].append("Tap point chưa xác nhận; tạm ngừng suy luận DSP/feedback")
    meters = []
    for ch in range(1, 33):
        measured = source["valid"] and ch <= block.shape[1] and ch <= len(peaks)
        name = (profiles.get(ch, {}).get("name", f"Kênh {ch:02d}") if source["simulated"]
                else f"USB Input {ch:02d} • chưa ánh xạ")
        meters.append({"channel": ch, "name": name,
            "meter_dbfs": round(float(peaks[ch - 1]), 1) if measured else None,
            "rms_dbfs": round(float(rms[ch - 1]), 1) if measured else None})
    # Analyze one explicitly identified input, never a sum mislabeled as channel 3.
    index = 2 if block.shape[1] >= 3 and source["simulated"] else 0
    samples = block[:, index] if block.shape[1] else np.zeros(1024, dtype=np.float32)
    source["spectrum_input"] = index + 1
    return meters, samples, source
