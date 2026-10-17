"""Read-only X32 meter streaming over OSC.

The X32 pushes level meters after a ``/meters`` request. A request is a
subscription, not a parameter mutation, so it is allowed in READ_ONLY mode
(AGENTS.md rules 1-2): this module never sends anything else to the mixer.

Protocol reference / assumptions (Patrick-Gilles Maillot, "Unofficial X32/M32
OSC Remote Protocol", section "Meter requests"):

* Request: ``/meters ,si "/meters/1" <time_factor>``. Some revisions of the
  document show ``,siii "/meters/1" 0 0 <time_factor>`` instead (the two extra
  ints are only meaningful for banks such as /meters/6). The exact argument
  form is kept in :func:`build_meter_request` so it can be corrected after a
  test on real hardware.
* A subscription expires after ~10 s; we renew every ~8 s.
* Reply: address ``/meters/1`` with a single OSC blob. The blob holds a
  little-endian int32 value count followed by that many little-endian
  float32 values (linear, 1.0 = 0 dBFS). For bank 1 the first 32 values are
  the 32 input channel meters (post-preamp, pre-fader, pre-mute); the rest
  are gate/dynamics gain-reduction meters which we ignore.

The reader owns its own UDP socket and thread. It never shares the
X32Client socket: the client's synchronous ``query()`` would otherwise
consume (and discard) asynchronous meter packets.
"""
from __future__ import annotations

import math
import select
import socket
import struct
import threading
import time
from typing import Any, Dict, List, Optional

from .osc_codec import OSCMessage, encode_osc, decode_osc

INPUT_CHANNELS = 32
SILENCE_FLOOR_DBFS = -90.0
SILENCE_LINEAR = 1e-6
MAX_METER_VALUES = 512
RENEW_INTERVAL_S = 8.0
RETRY_INTERVAL_S = 1.0


def build_meter_request(bank: str = "/meters/1", time_factor: int = 1) -> bytes:
    """Encode the read-only ``/meters`` subscription request (see module docstring)."""
    return encode_osc(OSCMessage("/meters", [str(bank), int(time_factor)]))


def parse_meter_blob(blob: bytes) -> Optional[List[float]]:
    """Return the float values of an X32 meter blob, or None if malformed."""
    if not isinstance(blob, (bytes, bytearray)) or len(blob) < 4:
        return None
    count = struct.unpack_from("<i", blob, 0)[0]
    if count <= 0 or count > MAX_METER_VALUES or len(blob) < 4 + 4 * count:
        return None
    return list(struct.unpack_from(f"<{count}f", blob, 4))


def parse_meter_packet(data: bytes, bank: str = "/meters/1") -> Optional[List[float]]:
    """Decode a raw UDP datagram; None unless it is a well-formed reply for ``bank``."""
    try:
        msg = decode_osc(data)
    except Exception:
        return None
    if msg.address != bank or not msg.args or not isinstance(msg.args[0], (bytes, bytearray)):
        return None
    return parse_meter_blob(msg.args[0])


def linear_to_dbfs(value: Any) -> Optional[float]:
    """Linear meter (1.0 = 0 dBFS) to dBFS. True silence -> -90.0; garbage -> None."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    if value <= SILENCE_LINEAR:
        return SILENCE_FLOOR_DBFS
    return round(max(SILENCE_FLOOR_DBFS, 20.0 * math.log10(value)), 1)


class X32MeterReader:
    """Background subscriber for one X32 meter bank (default: input channels)."""

    def __init__(self, host: str, port: int, bank: str = "/meters/1", time_factor: int = 1,
                 simulated: bool = False):
        self.host = host
        self.port = int(port)
        self.bank = bank
        self.time_factor = int(time_factor)
        # True only when the target is the internal mock mixer (set by the caller).
        self.simulated = bool(simulated)
        self._lock = threading.Lock()
        self._latest: Optional[Dict[str, Any]] = None
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._peer_ip = host
        self.packets_received = 0
        self.packets_rejected = 0
        self.last_error: Optional[str] = None

    @property
    def is_running(self) -> bool:
        return self._running and bool(self._thread and self._thread.is_alive())

    def start(self) -> "X32MeterReader":
        if self.is_running:
            return self
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if hasattr(socket, "SIO_UDP_CONNRESET"):  # Windows: ignore ICMP port-unreachable resets
            try:
                sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            except Exception:
                pass
        sock.bind(("", 0))
        try:
            self._peer_ip = socket.gethostbyname(self.host)
        except Exception:
            self._peer_ip = self.host
        self._sock = sock
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="X32MeterReader")
        self._thread.start()
        return self

    def stop(self) -> None:
        self._running = False
        thread, self._thread = self._thread, None
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        sock, self._sock = self._sock, None
        if sock:
            try:
                sock.close()
            except Exception:
                pass

    def latest(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if self._latest is None:
                return None
            return {"received_at": self._latest["received_at"], "count": self._latest["count"],
                    "channels": [dict(c) for c in self._latest["channels"]]}

    def age_s(self, now: Optional[float] = None) -> Optional[float]:
        with self._lock:
            if self._latest is None:
                return None
            return max(0.0, (time.monotonic() if now is None else now) - self._latest["received_at"])

    def is_fresh(self, max_age_s: float = 0.5, now: Optional[float] = None) -> bool:
        age = self.age_s(now)
        return age is not None and age <= max_age_s

    def status(self) -> Dict[str, Any]:
        age = self.age_s()
        return {"running": self.is_running, "fresh": age is not None and age <= 0.5,
                "age_s": None if age is None else round(age, 2), "bank": self.bank,
                "target": f"{self.host}:{self.port}", "simulated": self.simulated,
                "packets": self.packets_received, "rejected": self.packets_rejected}

    # -- internals -------------------------------------------------------
    def _ingest(self, data: bytes, now: float) -> bool:
        values = parse_meter_packet(data, self.bank)
        if values is None:
            self.packets_rejected += 1
            return False
        channels = [{"channel": ch, "level_dbfs": linear_to_dbfs(values[ch - 1]) if ch <= len(values) else None}
                    for ch in range(1, INPUT_CHANNELS + 1)]
        with self._lock:
            self._latest = {"received_at": now, "count": len(values), "channels": channels}
        self.packets_received += 1
        return True

    def _subscribe(self) -> None:
        sock = self._sock
        if sock:
            sock.sendto(build_meter_request(self.bank, self.time_factor), (self.host, self.port))

    def _loop(self) -> None:
        last_request = -math.inf
        while self._running:
            try:
                now = time.monotonic()
                # Renew before the ~10 s expiry; retry faster while nothing arrives.
                interval = RENEW_INTERVAL_S if self.is_fresh(1.0, now) else RETRY_INTERVAL_S
                if now - last_request >= interval:
                    last_request = now
                    self._subscribe()
                sock = self._sock
                if sock is None:
                    break
                readable, _, _ = select.select([sock], [], [], 0.1)
                if readable:
                    data, addr = sock.recvfrom(8192)
                    if addr[0] == self._peer_ip:  # only the mixer we subscribed to
                        self._ingest(data, time.monotonic())
            except Exception as exc:  # never let the thread die on a bad packet/socket hiccup
                if not self._running:
                    break
                self.last_error = str(exc)
                time.sleep(0.1)


def restart_meter_reader(old: Optional[X32MeterReader], host: str, port: int,
                         simulated: bool = False) -> Optional[X32MeterReader]:
    """Stop ``old`` and start a fresh reader for host:port. Never raises."""
    if old:
        try:
            old.stop()
        except Exception:
            pass
    try:
        return X32MeterReader(host, port, simulated=simulated).start()
    except Exception:
        return None
