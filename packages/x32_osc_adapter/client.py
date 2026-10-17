"""
Type-safe X32 OSC Client with:
- Enforced READ_ONLY_MODE by default
- Heartbeat (/xremote) maintenance
- Channel and routing query
- Snapshot generator with SHA-256 cryptographic hashing
- Diff utility for audit and rollback verification
"""

from __future__ import annotations
import socket
import select
import time
import json
import hashlib
import threading
from contextlib import nullcontext
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Tuple

from .osc_codec import OSCMessage, encode_osc, decode_osc


class ReadOnlyViolationError(PermissionError):
    """Raised when any write operation is attempted while client is in READ_ONLY_MODE."""
    pass


class X32ConnectionError(ConnectionError):
    """Raised when connection or query to X32 fails or times out."""
    pass


@dataclass
class Snapshot:
    timestamp: float
    iso_time: str
    mixer_info: Dict[str, Any]
    sha256: str
    channel_count: int
    parameters: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save_to_file(self, filepath: str):
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load_from_file(cls, filepath: str) -> "Snapshot":
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls(**data)


class X32Client:
    def __init__(self, host: str = "127.0.0.1", port: int = 10023, read_only_mode: bool = True, timeout: float = 1.0):
        self.host = host
        self.port = port
        self.read_only_mode = read_only_mode
        self.default_timeout = timeout
        
        self.sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_active = False
        self.write_authorizer = None

        # In-memory State Mirror cache: address -> (value, last_updated)
        self.state_mirror: Dict[str, Tuple[Any, float]] = {}

    def connect(self) -> Dict[str, Any]:
        """Open UDP socket and verify communication with mixer."""
        with self._lock:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(self.default_timeout)

        # Query /info to verify connectivity
        info_resp = self.query("/info")
        if not info_resp:
            raise X32ConnectionError(f"No response from X32 at {self.host}:{self.port} on /info")

        # Start background heartbeat (/xremote)
        self._heartbeat_active = True
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True, name="X32Heartbeat")
        self._heartbeat_thread.start()

        return {
            "connected": True,
            "read_only_mode": self.read_only_mode,
            "info": info_resp,
            "host": self.host,
            "port": self.port,
        }

    def close(self):
        """Stop heartbeat and close socket."""
        self._heartbeat_active = False
        with self._lock:
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None

    def _heartbeat_loop(self):
        """Send /xremote periodically every 7 seconds to keep subscription active."""
        while self._heartbeat_active:
            try:
                msg = OSCMessage("/xremote")
                raw = encode_osc(msg)
                with self._lock:
                    if self.sock:
                        self.sock.sendto(raw, (self.host, self.port))
            except Exception:
                pass
            time.sleep(7.0)

    def query(self, address: str, timeout: Optional[float] = None) -> List[Any]:
        """Send a read-only query (message with no arguments) and await response."""
        tout = timeout or self.default_timeout
        msg = OSCMessage(address)
        raw = encode_osc(msg)

        with self._lock:
            if not self.sock:
                raise X32ConnectionError("Socket is not connected. Call connect() first.")
            self.sock.sendto(raw, (self.host, self.port))

            start_t = time.time()
            while time.time() - start_t < tout:
                r, _, _ = select.select([self.sock], [], [], max(0.01, tout - (time.time() - start_t)))
                if not r:
                    continue
                data, _ = self.sock.recvfrom(4096)
                resp = decode_osc(data)
                if resp.address == address:
                    # Update State Mirror
                    val = resp.args[0] if len(resp.args) == 1 else resp.args
                    self.state_mirror[address] = (val, time.time())
                    return resp.args

        raise X32ConnectionError(f"Timeout waiting for response from {address} after {tout}s")

    def send_write(self, address: str, args: List[Any], timeout: Optional[float] = None) -> List[Any]:
        """
        Send a parameter mutation command to X32.
        STRICT SAFETY GATE: Blocks write if read_only_mode == True!
        """
        if self.read_only_mode:
            raise ReadOnlyViolationError(
                f"SAFETY GATE BLOCKED WRITE: Cannot write to '{address}' with values {args}. "
                f"Client is strictly operating in READ_ONLY_MODE = True."
            )

        tout = timeout or self.default_timeout
        msg = OSCMessage(address, args)
        raw = encode_osc(msg)

        with self._lock:
            if not self.sock:
                raise X32ConnectionError("Socket is not connected.")
            permit = self.write_authorizer(address, args) if self.write_authorizer else nullcontext()
            with permit:
                if self.read_only_mode:
                    raise ReadOnlyViolationError("OSC write revoked before packet dispatch.")
                self.sock.sendto(raw, (self.host, self.port))

            start_t = time.time()
            while time.time() - start_t < tout:
                r, _, _ = select.select([self.sock], [], [], max(0.01, tout - (time.time() - start_t)))
                if not r:
                    continue
                data, _ = self.sock.recvfrom(4096)
                resp = decode_osc(data)
                if resp.address == address:
                    val = resp.args[0] if len(resp.args) == 1 else resp.args
                    self.state_mirror[address] = (val, time.time())
                    return resp.args

        raise X32ConnectionError(f"Timeout waiting for write echo from {address}")

    def get_channel_summary(self, ch_num: int, snapshot: Optional[Snapshot] = None) -> Dict[str, Any]:
        """Read core parameters, or derive them from the supplied fresh snapshot.

        Snapshot reads never fall back to network queries or the state mirror:
        missing parameters indicate an incomplete snapshot and raise KeyError.
        """
        ch_str = f"/ch/{ch_num:02d}"

        def read(path: str) -> Any:
            if snapshot is not None:
                return snapshot.parameters[path]
            return self.query(path)[0]
        
        name = read(f"{ch_str}/config/name")
        color = read(f"{ch_str}/config/color")
        fader = read(f"{ch_str}/mix/fader")
        is_on = read(f"{ch_str}/mix/on")
        mix_st = read(f"{ch_str}/mix/st") # Main Stereo assign
        hpon = read(f"{ch_str}/preamp/hpon")
        hpf = read(f"{ch_str}/preamp/hpf")

        eq_on = read(f"{ch_str}/eq/on")
        eq_bands = []
        for b in range(1, 5):
            f = read(f"{ch_str}/eq/{b}/f")
            g = read(f"{ch_str}/eq/{b}/g")
            q = read(f"{ch_str}/eq/{b}/q")
            eq_bands.append({"band": b, "f": f, "gain": g, "q": q})

        return {
            "channel": ch_num,
            "name": name,
            "color": color,
            "fader": fader,
            "on": is_on,
            "mix_st": mix_st, # 0 = NOT going to FOH Main, 1 = routes to Main
            "hpon": hpon,
            "hpf": hpf,
            "eq_on": eq_on,
            "eq_bands": eq_bands,
        }

    def take_full_snapshot(self, max_channels: int = 32) -> Snapshot:
        """
        Take complete snapshot of the mixer configuration.
        Calculates SHA-256 digest of canonical state JSON.
        """
        params: Dict[str, Any] = {}

        # 1. Mixer info
        info = self.query("/info")
        status = self.query("/status")
        params["/info"] = info
        params["/status"] = status

        # 2. Main FOH
        params["/main/st/config/name"] = self.query("/main/st/config/name")[0]
        params["/main/st/mix/fader"] = self.query("/main/st/mix/fader")[0]
        params["/main/st/mix/on"] = self.query("/main/st/mix/on")[0]

        # 3. Channels 1..max_channels
        for ch in range(1, max_channels + 1):
            ch_str = f"/ch/{ch:02d}"
            params[f"{ch_str}/config/name"] = self.query(f"{ch_str}/config/name")[0]
            params[f"{ch_str}/config/color"] = self.query(f"{ch_str}/config/color")[0]
            params[f"{ch_str}/mix/fader"] = self.query(f"{ch_str}/mix/fader")[0]
            params[f"{ch_str}/mix/on"] = self.query(f"{ch_str}/mix/on")[0]
            params[f"{ch_str}/mix/st"] = self.query(f"{ch_str}/mix/st")[0]
            params[f"{ch_str}/preamp/hpon"] = self.query(f"{ch_str}/preamp/hpon")[0]
            params[f"{ch_str}/preamp/hpf"] = self.query(f"{ch_str}/preamp/hpf")[0]
            params[f"{ch_str}/eq/on"] = self.query(f"{ch_str}/eq/on")[0]

            for b in range(1, 5):
                params[f"{ch_str}/eq/{b}/f"] = self.query(f"{ch_str}/eq/{b}/f")[0]
                params[f"{ch_str}/eq/{b}/g"] = self.query(f"{ch_str}/eq/{b}/g")[0]
                params[f"{ch_str}/eq/{b}/q"] = self.query(f"{ch_str}/eq/{b}/q")[0]

        # 4. Routing & Ultranet P16 checks
        params["/config/routing/IN"] = self.query("/config/routing/IN")[0]
        params["/config/routing/AES50A"] = self.query("/config/routing/AES50A")[0]
        params["/outputs/p16/11/tap"] = self.query("/outputs/p16/11/tap")[0]

        # 5. Every path the talkback invariant needs (sends, bus -> Main/Mono/Matrix, P16 slots).
        # Without these the invariant checker would only see defaults and could not detect a leak.
        # Imported lazily: safety_controller imports this module.
        from packages.safety_controller.routing import get_talkback_channel, talkback_routing_paths
        tb_ch = get_talkback_channel()
        params[f"/ch/{tb_ch:02d}/config/name"] = self.query(f"/ch/{tb_ch:02d}/config/name")[0]
        for path in talkback_routing_paths(tb_ch):
            params[path] = self.query(path)[0]

        # Compute SHA-256 of sorted canonical JSON
        canonical_str = json.dumps(params, sort_keys=True)
        sha256 = hashlib.sha256(canonical_str.encode('utf-8')).hexdigest()

        now = time.time()
        return Snapshot(
            timestamp=now,
            iso_time=time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(now)),
            mixer_info={"info": info, "status": status},
            sha256=sha256,
            channel_count=max_channels,
            parameters=params,
        )

    @staticmethod
    def diff_snapshots(snap_before: Snapshot, snap_after: Snapshot) -> Dict[str, Any]:
        """Compute delta between two snapshots for audit and rollback."""
        p_before = snap_before.parameters
        p_after = snap_after.parameters

        added = {}
        removed = {}
        changed = {}

        for k, v in p_after.items():
            if k not in p_before:
                added[k] = v
            elif p_before[k] != v:
                changed[k] = {"before": p_before[k], "after": v}

        for k, v in p_before.items():
            if k not in p_after:
                removed[k] = v

        return {
            "has_changes": bool(added or removed or changed),
            "added": added,
            "removed": removed,
            "changed": changed,
            "before_sha256": snap_before.sha256,
            "after_sha256": snap_after.sha256,
        }

    @classmethod
    def discover_consoles(
        cls,
        target_hosts: Optional[List[str]] = None,
        port: int = 10023,
        timeout: float = 0.6,
    ) -> List[Dict[str, Any]]:
        """
        Scan and discover active Behringer X32 / M32 consoles or simulators.
        Probes target hosts and local broadcast to find active devices.
        """
        discovered = []
        seen_addrs = set()

        hosts = target_hosts or ["127.0.0.1", "255.255.255.255"]
        msg = OSCMessage("/info")
        raw = encode_osc(msg)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except Exception:
            pass

        for h in hosts:
            try:
                sock.sendto(raw, (h, port))
            except Exception:
                pass

        start_t = time.time()
        while time.time() - start_t < timeout:
            r, _, _ = select.select([sock], [], [], max(0.01, timeout - (time.time() - start_t)))
            if not r:
                break
            try:
                data, addr = sock.recvfrom(4096)
                if addr in seen_addrs:
                    continue
                seen_addrs.add(addr)

                resp = decode_osc(data)
                if resp.address == "/info":
                    model = str(resp.args[2]) if len(resp.args) > 2 else "X32 Console"
                    firmware = str(resp.args[0]) if len(resp.args) > 0 else "Unknown"
                    name = str(resp.args[1]) if len(resp.args) > 1 else "Mixer"
                    discovered.append({
                        "ip": addr[0],
                        "port": addr[1],
                        "model": model,
                        "firmware": firmware,
                        "name": name,
                    })
            except Exception:
                break

        sock.close()
        return discovered

