"""Resolve analysis audio once, with explicit origin and clock validity."""
import time
import numpy as np
from packages.signal_analysis.dsp import generate_sine_wave, generate_vocal_note, generate_pink_noise


class AudioSourceError(ValueError):
    def __init__(self, message, status_code=409):
        super().__init__(message)
        self.status_code = status_code


def resolve_analysis_audio(soundcheck, worker, channel_id=None):
    source = {"simulated": True, "sample_rate": 48000, "tap_point": "SIMULATED", "valid": True}
    if soundcheck.is_active:
        block = soundcheck.generate_audio_block(block_size=2048)
        source.update(label="Soundcheck ảo", sample_rate=soundcheck.sample_rate)
    elif worker and worker.is_running:
        frame = worker.get_latest_frame()
        block = frame["samples"]
        if block is None or frame["captured_at"] is None or time.monotonic() - frame["captured_at"] > 0.5:
            raise AudioSourceError("Không có buffer audio mới; kiểm tra capture.", 503)
        if block.ndim == 1:
            block = block.reshape(-1, 1)
        if channel_id is not None and channel_id > block.shape[1]:
            raise AudioSourceError(f"Không có đầu vào audio {channel_id}; không dùng đầu vào khác thay thế.", 503)
        if not frame["is_simulated"]:
            if not frame["clock_verified"] or frame["clock_fault"] or frame["overflow_count"]:
                raise AudioSourceError("Clock hoặc buffer chưa hợp lệ; tạm dừng phân tích.")
            raise AudioSourceError("Chưa xác nhận ánh xạ USB tới kênh/bus X32 và tap point. Xem đầu vào USB ở Giám sát tín hiệu.")
        source.update(label="USB mô phỏng", sample_rate=worker.sample_rate)
    else:
        source["label"] = "Demo • dữ liệu mô phỏng"
        samples = (generate_sine_wave(440,0.1,amplitude=0.18) if channel_id is not None
                   else generate_vocal_note(220,0.5)*0.35 + generate_pink_noise(0.5,amplitude=0.15))
        return samples, source
    if channel_id is not None:
        if not 1 <= channel_id <= block.shape[1]:
            raise AudioSourceError(f"Không có đầu vào audio {channel_id}.",503)
        samples = block[:,channel_id-1]
    else:
        samples = np.mean(block[:,:min(8,block.shape[1])],axis=1)
    if not np.all(np.isfinite(samples)):
        raise AudioSourceError("Mẫu audio không hữu hạn; tạm dừng phân tích.")
    return samples.astype(np.float32,copy=False), source
