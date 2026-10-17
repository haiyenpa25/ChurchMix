"""
Audio Stream Worker for Real-Time Multi-Channel Ingestion & Level Monitoring
"""
from typing import Optional, Callable, Dict, Any, List
import numpy as np
import threading
import time
import logging

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False

logger = logging.getLogger("CaptureAgent.StreamWorker")


class AudioStreamWorker:
    """Worker handling live audio streaming or simulated multichannel signals."""

    def __init__(
        self,
        device_id: int = -1,
        channels: int = 2,
        sample_rate: int = 48000,
        block_size: int = 1024,
        on_block_callback: Optional[Callable[[np.ndarray], None]] = None,
    ):
        self.device_id = device_id
        self.channels = channels
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.on_block_callback = on_block_callback

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stream = None
        self._lock = threading.Lock()
        self._data_lock = threading.Lock()
        self.is_simulated = device_id < 0 or not SOUNDDEVICE_AVAILABLE
        self.clock_verified = self.is_simulated
        self.clock_fault = False
        self._clock_good_blocks = 0
        self._last_adc_time = None
        self.last_block_monotonic = None
        self.capture_error = None
        self.tap_point = "UNKNOWN"

        # Telemetry metrics
        self.latest_peak_dbfs: List[float] = [-90.0] * channels
        self.latest_rms_dbfs: List[float] = [-90.0] * channels
        self.overflow_count: int = 0
        self.blocks_processed: int = 0
        self.latest_buffer: Optional[np.ndarray] = None

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self):
        """Start the audio stream worker."""
        with self._lock:
            if self._running:
                return
            self._running = True

            if self.device_id >= 0 and SOUNDDEVICE_AVAILABLE:
                self._start_physical_stream()
            else:
                self._start_simulated_stream()

    def stop(self):
        """Stop the audio stream worker."""
        with self._lock:
            if not self._running:
                return
            self._running = False

            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception as e:
                    logger.warning(f"Error closing stream: {e}")
                self._stream = None

            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout=1.0)
                self._thread = None

    def _start_physical_stream(self):
        """Start physical sounddevice InputStream with callback."""
        def callback(indata, frames, time_info, status):
            if status:
                self.overflow_count += 1
                logger.warning(f"Audio stream status: {status}")
            adc_time = getattr(time_info, "inputBufferAdcTime", 0.0)
            if adc_time > 0 and self._last_adc_time is not None:
                expected = frames / self.sample_rate
                interval = adc_time - self._last_adc_time
                if abs(interval - expected) > expected * 0.05:
                    self.clock_fault = True
                    self.clock_verified = False
                elif not self.clock_fault:
                    self._clock_good_blocks += 1
                    self.clock_verified = self._clock_good_blocks >= 5
            elif adc_time <= 0 or not np.isfinite(adc_time):
                self.clock_verified = False
                self.clock_fault = True
            self._last_adc_time = adc_time if adc_time > 0 else None
            self._process_audio_block(indata.copy())

        try:
            self._stream = sd.InputStream(
                device=self.device_id,
                channels=self.channels,
                samplerate=self.sample_rate,
                blocksize=self.block_size,
                dtype="float32",
                callback=callback,
            )
            self._stream.start()
            self.is_simulated = False
            logger.info(f"Physical audio stream started on device {self.device_id} ({self.channels}ch @ {self.sample_rate}Hz)")
        except Exception as e:
            logger.error(f"Failed to start physical stream: {e}. Falling back to simulation.")
            self.capture_error = str(e)
            if self._stream is not None:
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            self._start_simulated_stream()

    def _start_simulated_stream(self):
        """Run simulated audio generator loop in a background thread."""
        self.is_simulated = True
        self.clock_verified = True
        self.tap_point = "SIMULATED"
        self._thread = threading.Thread(target=self._simulated_loop, daemon=True)
        self._thread.start()
        logger.info(f"Simulated audio stream started ({self.channels}ch @ {self.sample_rate}Hz)")

    def _simulated_loop(self):
        """Generates realistic live church audio signal blocks."""
        dt = self.block_size / self.sample_rate
        t_accum = 0.0

        while self._running:
            t = np.linspace(t_accum, t_accum + dt, self.block_size, endpoint=False)
            buffer = np.zeros((self.block_size, self.channels), dtype=np.float32)

            for ch in range(self.channels):
                if ch == 0:
                    # Pastor speech tone (speech fundamental 180Hz + harmonics)
                    speech = 0.25 * np.sin(2 * np.pi * 180 * t) + 0.15 * np.sin(2 * np.pi * 360 * t)
                    mod = 0.5 + 0.5 * np.sin(2 * np.pi * 0.2 * t_accum)
                    buffer[:, ch] = (speech * mod).astype(np.float32)
                elif ch == 1:
                    # Lead vocal (440Hz A4)
                    voc = 0.3 * np.sin(2 * np.pi * 440 * t) + 0.15 * np.sin(2 * np.pi * 880 * t)
                    buffer[:, ch] = voc.astype(np.float32)
                else:
                    noise = np.random.normal(0, 0.005, self.block_size).astype(np.float32)
                    buffer[:, ch] = noise

            self._process_audio_block(buffer)
            t_accum += dt
            time.sleep(dt * 0.95)

    def _process_audio_block(self, block: np.ndarray):
        """Compute metrics and dispatch block."""
        columns = block.reshape(-1, 1) if block.ndim == 1 else block[:, :self.channels]
        peaks = np.max(np.abs(columns), axis=0)
        rms = np.sqrt(np.mean(columns ** 2, axis=0))
        peak_levels = [round(float(v), 1) for v in 20 * np.log10(np.maximum(peaks, 1e-7))]
        rms_levels = [round(float(v), 1) for v in 20 * np.log10(np.maximum(rms, 1e-7))]
        with self._data_lock:
            self.blocks_processed += 1
            self.latest_buffer = block
            self.latest_peak_dbfs = peak_levels
            self.latest_rms_dbfs = rms_levels
            self.last_block_monotonic = time.monotonic()

        if self.on_block_callback:
            try:
                self.on_block_callback(block)
            except Exception as e:
                logger.error(f"Callback error in audio stream: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Return real-time stream status."""
        return {
            "is_running": self._running,
            "device_id": self.device_id,
            "channels": self.channels,
            "sample_rate": self.sample_rate,
            "block_size": self.block_size,
            "blocks_processed": self.blocks_processed,
            "overflow_count": self.overflow_count,
            "peak_dbfs": self.latest_peak_dbfs,
            "rms_dbfs": self.latest_rms_dbfs,
            "is_simulated": self.is_simulated,
            "clock_verified": self.clock_verified,
            "clock_fault": self.clock_fault,
            "tap_point": self.tap_point,
            "capture_error": self.capture_error,
        }

    def get_latest_frame(self):
        """Read samples and their meters from the same published block."""
        with self._data_lock:
            return {"samples": self.latest_buffer, "peaks": list(self.latest_peak_dbfs),
                "rms": list(self.latest_rms_dbfs), "captured_at": self.last_block_monotonic,
                "sequence": self.blocks_processed, "overflow_count": self.overflow_count,
                "clock_verified": self.clock_verified, "clock_fault": self.clock_fault,
                "is_simulated": self.is_simulated, "capture_error": self.capture_error}
