"""
Audio Device Manager for Native Soundcard / USB Audio Interface Discovery
Supports Behringer X-USB, DN32-USB, ASIO, WASAPI, MME and Simulated Test Streams.
"""
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger("CaptureAgent.DeviceManager")

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False
    logger.warning("sounddevice not available; operating in simulation mode only.")


class AudioDeviceInfo:
    def __init__(self, device_id: int, name: str, hostapi: str, max_inputs: int, max_outputs: int, default_sr: float):
        self.device_id = device_id
        self.name = name
        self.hostapi = hostapi
        self.max_inputs = max_inputs
        self.max_outputs = max_outputs
        self.default_sr = default_sr

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "hostapi": self.hostapi,
            "max_inputs": self.max_inputs,
            "max_outputs": self.max_outputs,
            "default_samplerate": self.default_sr,
            "is_x32_compatible": any(k in self.name.lower() for k in ["x-usb", "x32", "dn32", "behringer", "usb audio"]),
        }


class AudioDeviceManager:
    """Manages audio device enumeration and hardware selection."""

    def __init__(self):
        self._selected_device_id: Optional[int] = None
        self._simulation_mode: bool = not SOUNDDEVICE_AVAILABLE

    @property
    def is_simulation_mode(self) -> bool:
        return self._simulation_mode

    def list_input_devices(self) -> List[Dict[str, Any]]:
        """List all available physical audio input devices."""
        devices = []
        if not SOUNDDEVICE_AVAILABLE:
            return [
                {
                    "device_id": -1,
                    "name": "Simulated X-USB Card (32 Ch In, 48kHz)",
                    "hostapi": "Virtual Simulation",
                    "max_inputs": 32,
                    "max_outputs": 32,
                    "default_samplerate": 48000.0,
                    "is_x32_compatible": True,
                }
            ]

        try:
            raw_devices = sd.query_devices()
            hostapis = sd.query_hostapis()

            for idx, dev in enumerate(raw_devices):
                if dev.get("max_input_channels", 0) > 0:
                    api_idx = dev.get("hostapi", 0)
                    api_name = hostapis[api_idx].get("name", "Unknown") if api_idx < len(hostapis) else "Unknown"
                    info = AudioDeviceInfo(
                        device_id=idx,
                        name=dev.get("name", f"Device {idx}"),
                        hostapi=api_name,
                        max_inputs=dev.get("max_input_channels", 0),
                        max_outputs=dev.get("max_output_channels", 0),
                        default_sr=dev.get("default_samplerate", 48000.0),
                    )
                    devices.append(info.to_dict())
        except Exception as e:
            logger.error(f"Error querying audio devices: {e}")

        # Always append simulator option
        devices.append({
            "device_id": -1,
            "name": "Simulated X-USB Card (32 Ch In, 48kHz)",
            "hostapi": "Virtual Simulation",
            "max_inputs": 32,
            "max_outputs": 32,
            "default_samplerate": 48000.0,
            "is_x32_compatible": True,
        })
        return devices

    def find_x32_usb_device(self) -> Optional[Dict[str, Any]]:
        """Automatically find connected X32 USB expansion card (X-USB / DN32-USB)."""
        devices = self.list_input_devices()
        candidates = [d for d in devices if d["device_id"] >= 0 and d["is_x32_compatible"]]
        if candidates:
            candidates.sort(key=lambda d: d["max_inputs"], reverse=True)
            return candidates[0]
        return None

    def validate_device(self, device_id: int, sample_rate: int = 48000) -> bool:
        """Verify device exists and supports target sample rate (default 48kHz)."""
        if device_id == -1:
            return True
        if not SOUNDDEVICE_AVAILABLE:
            return False

        try:
            sd.check_input_settings(device=device_id, samplerate=sample_rate)
            return True
        except Exception as e:
            logger.warning(f"Device {device_id} incompatible with {sample_rate}Hz: {e}")
            return False
