"""
ChurchMix Native Behringer X32 Scene (.scn) Importer & Safety Validator.
========================================================================
1. Parses standard Behringer X32 / M32 ASCII .scn scene files (firmware v4.xx).
2. Performs pre-load Safety Audit:
   - Hard Invariant DL16 In 11 (Band Talkback) isolation check from Main FOH and Livestream buses.
   - Excessive gain warning (fader > +5 dB).
   - Missing vocal HPF check on channels 1-4.
   - Aggressive narrow-band EQ boost feedback hazard detection.
3. Automated Sanitization & Invariant Enforcement:
   - Patches Talkback routing (/ch/11/mix/lr OFF, /outputs/p16/11/src 11).
4. Direct persistence into Scene Vault with SHA-256 fingerprinting.
"""
from __future__ import annotations
import re
import time
import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple

from packages.eq_optimizer.recommender import (
    freq_to_x32,
    gain_to_x32,
    q_to_x32,
    x32_to_freq,
    x32_to_gain,
    x32_to_q,
)
from packages.safety_controller.routing import RoutingGraph
from packages.storage.scene_vault import SceneVaultManager


@dataclass
class SceneAuditReport:
    scene_name: str
    is_safe: bool
    invariant_passed: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    patches_applied: List[str] = field(default_factory=list)
    channel_count: int = 32
    sha256: str = ""
    summary_vi: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SceneImporter:
    """Parses, validates, sanitizes, and vaults Behringer X32 .scn scene files."""

    @staticmethod
    def parse_scn_text(scn_content: str) -> Tuple[str, Dict[str, Any]]:
        """
        Parse raw ASCII .scn content into scene name and normalized X32 parameter dict.
        """
        lines = [line.strip() for line in scn_content.splitlines() if line.strip()]
        scene_name = "Imported_USB_Scene"
        params: Dict[str, Any] = {}

        # Default all 32 channels with standard baseline
        for ch in range(1, 33):
            ch_str = f"/ch/{ch:02d}"
            params[f"{ch_str}/config/name"] = f"Ch {ch:02d}"
            params[f"{ch_str}/config/color"] = 1
            params[f"{ch_str}/config/source"] = ch - 1
            params[f"{ch_str}/mix/fader"] = 0.75 # 0 dB nominal
            params[f"{ch_str}/mix/on"] = 1
            params[f"{ch_str}/mix/lr"] = 0 if ch == 11 else 1
            params[f"{ch_str}/mix/st"] = 0 if ch == 11 else 1
            params[f"{ch_str}/preamp/hpon"] = 1 if ch <= 4 else 0
            params[f"{ch_str}/preamp/hpf"] = freq_to_x32(100.0) if ch <= 4 else freq_to_x32(40.0)
            params[f"{ch_str}/eq/on"] = 1
            for b in range(1, 5):
                params[f"{ch_str}/eq/{b}/f"] = 0.5
                params[f"{ch_str}/eq/{b}/g"] = 0.5
                params[f"{ch_str}/eq/{b}/q"] = 0.5

        for line in lines:
            # Header check: #2.1# "SceneName" "Comment" %flags int
            if line.startswith("#2.1#"):
                match = re.search(r'#2.1#\s+"([^"]*)"', line)
                if match:
                    scene_name = match.group(1).strip() or "Imported_Scene"
                continue

            # Ignore comments
            if line.startswith("#"):
                continue

            parts = line.split()
            if not parts:
                continue

            cmd = parts[0]

            # 1. Channel Config: /ch/01/config "Vocal" 1 YE 0
            config_match = re.match(r"^/ch/(\d{2})/config$", cmd)
            if config_match:
                ch = int(config_match.group(1))
                ch_str = f"/ch/{ch:02d}"
                # Extract quoted name
                name_match = re.search(r'"([^"]*)"', line)
                if name_match:
                    params[f"{ch_str}/config/name"] = name_match.group(1)
                # Remainder tokens
                rem = line[line.rfind('"') + 1:].split() if '"' in line else parts[1:]
                if len(rem) >= 1 and rem[0].isdigit():
                    params[f"{ch_str}/config/color"] = int(rem[0])
                if len(rem) >= 3 and rem[2].isdigit():
                    params[f"{ch_str}/config/source"] = int(rem[2])
                continue

            # 2. Preamp & HPF: /ch/01/preamp +0.0 OFF ON 100.0
            preamp_match = re.match(r"^/ch/(\d{2})/preamp$", cmd)
            if preamp_match and len(parts) >= 5:
                ch = int(preamp_match.group(1))
                ch_str = f"/ch/{ch:02d}"
                hpon_str = parts[3].upper()
                params[f"{ch_str}/preamp/hpon"] = 1 if hpon_str == "ON" else 0
                try:
                    hpf_hz = float(parts[4])
                    params[f"{ch_str}/preamp/hpf"] = freq_to_x32(hpf_hz)
                except ValueError:
                    pass
                continue

            # 3. Fader: /ch/01/mix/fader 0.7500
            fader_match = re.match(r"^/ch/(\d{2})/mix/fader$", cmd)
            if fader_match and len(parts) >= 2:
                ch = int(fader_match.group(1))
                try:
                    params[f"/ch/{ch:02d}/mix/fader"] = round(float(parts[1]), 4)
                except ValueError:
                    pass
                continue

            # 4. Mute on/off: /ch/01/mix/on ON / OFF
            on_match = re.match(r"^/ch/(\d{2})/mix/on$", cmd)
            if on_match and len(parts) >= 2:
                ch = int(on_match.group(1))
                params[f"/ch/{ch:02d}/mix/on"] = 1 if parts[1].upper() == "ON" else 0
                continue

            # 5. Main LR send: /ch/01/mix/lr ON / OFF
            lr_match = re.match(r"^/ch/(\d{2})/mix/lr$", cmd)
            if lr_match and len(parts) >= 2:
                ch = int(lr_match.group(1))
                is_on = 1 if parts[1].upper() == "ON" else 0
                params[f"/ch/{ch:02d}/mix/lr"] = is_on
                params[f"/ch/{ch:02d}/mix/st"] = is_on
                continue

            # 6. EQ On/Off: /ch/01/eq ON / OFF
            eq_match = re.match(r"^/ch/(\d{2})/eq$", cmd)
            if eq_match and len(parts) >= 2:
                ch = int(eq_match.group(1))
                params[f"/ch/{ch:02d}/eq/on"] = 1 if parts[1].upper() == "ON" else 0
                continue

            # 7. EQ Band: /ch/01/eq/1 PEQ 80.0 +0.0 2.0
            eq_band_match = re.match(r"^/ch/(\d{2})/eq/([1-4])$", cmd)
            if eq_band_match and len(parts) >= 5:
                ch = int(eq_band_match.group(1))
                band = int(eq_band_match.group(2))
                ch_str = f"/ch/{ch:02d}"
                try:
                    f_hz = float(parts[2])
                    g_db = float(parts[3])
                    q_val = float(parts[4])
                    params[f"{ch_str}/eq/{band}/f"] = freq_to_x32(f_hz)
                    params[f"{ch_str}/eq/{band}/g"] = gain_to_x32(g_db)
                    params[f"{ch_str}/eq/{band}/q"] = q_to_x32(q_val)
                except ValueError:
                    pass
                continue

            # 8. Ultranet P16 Slot Source: /outputs/p16/11/src 11
            p16_src_match = re.match(r"^/outputs/p16/(\d{1,2})/src$", cmd)
            if p16_src_match and len(parts) >= 2:
                slot = int(p16_src_match.group(1))
                try:
                    params[f"/outputs/p16/{slot:02d}/src"] = int(parts[1])
                except ValueError:
                    pass
                continue

        return scene_name, params

    @classmethod
    def audit_scene(cls, state_dict: Dict[str, Any], scene_name: str = "USB_Scene") -> SceneAuditReport:
        """
        Examine scene parameters against church audio invariants and safety rules.
        """
        violations: List[str] = []
        warnings: List[str] = []

        # 1. HARD INVARIANT: DL16 In 11 (Band Talkback) Isolation
        ch11_lr = int(state_dict.get("/ch/11/mix/lr", 0))
        ch11_st = int(state_dict.get("/ch/11/mix/st", 0))
        if ch11_lr == 1 or ch11_st == 1:
            violations.append(
                "VI PHẠM BẤT BIẾN AN TOÀN SỐNG CÒN: Kênh 11 (Band Talkback) đang BẬT gửi tín hiệu ra Main FOH (L/R)!"
            )

        # Check send to livestream buses (Bus 5..8)
        for bus in range(1, 9):
            if int(state_dict.get(f"/ch/11/mix/{bus:02d}/on", 0)) == 1:
                violations.append(
                    f"VI PHẠM BẤT BIẾN AN TOÀN: Kênh 11 (Band Talkback) đang gửi tín hiệu vào MixBus {bus:02d}!"
                )

        p16_11_src = state_dict.get("/outputs/p16/11/src")
        if p16_11_src is not None and int(p16_11_src) != 11:
            warnings.append(
                f"CẢNH BÁO ĐỊNH TUYẾN ULTRANET: Slot P16 số 11 không được nối với DL16 In 11 (hiện nối nguồn {p16_11_src})."
            )

        # 2. EXCESSIVE GAIN / FADER CHECKS
        for ch in range(1, 33):
            fader = float(state_dict.get(f"/ch/{ch:02d}/mix/fader", 0.75))
            ch_name = state_dict.get(f"/ch/{ch:02d}/config/name", f"Ch {ch:02d}")
            if fader > 0.85: # Over ~+5 dB
                warnings.append(
                    f"CẢNH BÁO FADER LỚN: Kênh {ch:02d} ({ch_name}) có fader đẩy quá cao ({fader:.2f} > 0.85, nguy cơ vỡ tiếng)."
                )

        # 3. MISSING HPF ON VOCAL CHANNELS (Ch 1 - 4)
        for ch in range(1, 5):
            ch_name = state_dict.get(f"/ch/{ch:02d}/config/name", f"Ch {ch:02d}")
            hpon = int(state_dict.get(f"/ch/{ch:02d}/preamp/hpon", 0))
            hpf_norm = float(state_dict.get(f"/ch/{ch:02d}/preamp/hpf", 0.0))
            hpf_hz = x32_to_freq(hpf_norm)
            if hpon == 0 or hpf_hz < 70.0:
                warnings.append(
                    f"CẢNH BÁO LỌC GIÓ/RUMBLE: Kênh micro {ch:02d} ({ch_name}) chưa bật HPF đúng chuẩn (hiện {hpf_hz:.0f} Hz < 80 Hz)."
                )

        # 4. AGGRESSIVE PEQ FEEDBACK HAZARD
        for ch in range(1, 33):
            ch_name = state_dict.get(f"/ch/{ch:02d}/config/name", f"Ch {ch:02d}")
            for b in range(1, 5):
                g_norm = float(state_dict.get(f"/ch/{ch:02d}/eq/{b}/g", 0.5))
                q_norm = float(state_dict.get(f"/ch/{ch:02d}/eq/{b}/q", 0.5))
                gain_db = x32_to_gain(g_norm)
                q_val = x32_to_q(q_norm)
                if gain_db > 8.0 and q_val > 2.5:
                    f_hz = x32_to_freq(float(state_dict.get(f"/ch/{ch:02d}/eq/{b}/f", 0.5)))
                    warnings.append(
                        f"NGUY CƠ HÚ ÂM: Kênh {ch:02d} ({ch_name}) Band {b} đang boost nhọn nguy hiểm (+{gain_db:.1f} dB tại {f_hz:.0f} Hz, Q={q_val:.1f})."
                    )

        sorted_state = json.dumps(state_dict, sort_keys=True)
        sha256 = hashlib.sha256(sorted_state.encode("utf-8")).hexdigest()

        inv_passed = len(violations) == 0
        is_safe = inv_passed and len(warnings) == 0

        if inv_passed and len(warnings) == 0:
            summary = "AN TOÀN TUYỆT ĐỐI: Scene đạt 100% tiêu chuẩn an toàn nhà thờ, sẵn sàng nạp vào bàn mixer."
        elif inv_passed:
            summary = f"ĐẠT BẤT BIẾN AN TOÀN (Có {len(warnings)} khuyến nghị âm học cần lưu ý)."
        else:
            summary = f"NGUY HIỂM: Phát hiện {len(violations)} vi phạm bất biến an toàn sống còn! Cần kích hoạt tự động sửa lỗi (Sanitize) trước khi nạp."

        return SceneAuditReport(
            scene_name=scene_name,
            is_safe=is_safe,
            invariant_passed=inv_passed,
            violations=violations,
            warnings=warnings,
            patches_applied=[],
            channel_count=32,
            sha256=sha256,
            summary_vi=summary,
        )

    @classmethod
    def sanitize_scene(cls, state_dict: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """
        Automatically patch safety invariants and enforce conservative limits.
        """
        sanitized = dict(state_dict)
        patches: List[str] = []

        # 1. Enforce DL16 In 11 Isolation from Main FOH
        if int(sanitized.get("/ch/11/mix/lr", 0)) == 1:
            sanitized["/ch/11/mix/lr"] = 0
            patches.append("Khóa cứng đường ra Main FOH của Kênh 11 Talkback: /ch/11/mix/lr = OFF")

        if int(sanitized.get("/ch/11/mix/st", 0)) == 1:
            sanitized["/ch/11/mix/st"] = 0
            patches.append("Khóa cứng đường ra Stereo Bus của Kênh 11 Talkback: /ch/11/mix/st = OFF")

        # 2. Enforce DL16 In 11 Isolation from All Livestream MixBuses (Bus 1..16)
        for bus in range(1, 17):
            bus_key = f"/ch/11/mix/{bus:02d}/on"
            if int(sanitized.get(bus_key, 0)) == 1:
                sanitized[bus_key] = 0
                patches.append(f"Ngắt rò rỉ tín hiệu Talkback vào MixBus {bus:02d}: {bus_key} = OFF")

        # 3. Enforce Ultranet P16 Slot 11 routing
        if sanitized.get("/outputs/p16/11/src") != 11:
            sanitized["/outputs/p16/11/src"] = 11
            patches.append("Định tuyến chuẩn Ultranet P16 Slot 11 kết nối trực tiếp DL16 In 11: /outputs/p16/11/src = 11")

        # 4. Enforce High-Pass Filter on vocal channels 1-4
        for ch in range(1, 5):
            hpon = int(sanitized.get(f"/ch/{ch:02d}/preamp/hpon", 0))
            hpf_norm = float(sanitized.get(f"/ch/{ch:02d}/preamp/hpf", 0.0))
            if hpon == 0 or x32_to_freq(hpf_norm) < 80.0:
                sanitized[f"/ch/{ch:02d}/preamp/hpon"] = 1
                sanitized[f"/ch/{ch:02d}/preamp/hpf"] = freq_to_x32(95.0)
                patches.append(f"Kích hoạt HPF an toàn Kênh {ch:02d} ở mức 95 Hz để chống ù gió sân khấu.")

        # 5. Clamp dangerous excessive faders (> +5 dB)
        for ch in range(1, 33):
            fader = float(sanitized.get(f"/ch/{ch:02d}/mix/fader", 0.75))
            if fader > 0.85:
                sanitized[f"/ch/{ch:02d}/mix/fader"] = 0.75 # 0 dB nominal
                ch_name = sanitized.get(f"/ch/{ch:02d}/config/name", f"Ch {ch:02d}")
                patches.append(f"Hạ fader Kênh {ch:02d} ({ch_name}) từ {fader:.2f} về mức danh định an toàn 0 dB (0.75).")

        return sanitized, patches

    @classmethod
    def import_and_vault(
        cls,
        scn_content: str,
        vault_mgr: Optional[SceneVaultManager] = None,
        author: str = "USB_Import",
        note: str = "",
        auto_sanitize: bool = True,
    ) -> Dict[str, Any]:
        """
        Complete pipeline: Parse .scn -> Audit -> (Optional Auto-Sanitize) -> Save to Vault.
        """
        vault = vault_mgr or SceneVaultManager()
        scene_name, raw_state = cls.parse_scn_text(scn_content)

        audit_report = cls.audit_scene(raw_state, scene_name=scene_name)

        final_state = raw_state
        patches = []
        if auto_sanitize:
            final_state, patches = cls.sanitize_scene(raw_state)
            audit_report = cls.audit_scene(final_state, scene_name=scene_name)
            audit_report.patches_applied = patches

        # Save into Scene Vault
        vault_res = vault.create_backup(
            name=f"[USB] {scene_name}",
            author=author,
            note=note or f"Nạp từ file USB .scn (Đã áp dụng {len(patches)} bản vá an toàn).",
            state_dict=final_state,
        )

        return {
            "vault_backup": vault_res,
            "audit_report": audit_report.to_dict(),
            "patches_applied": patches,
            "sanitized": len(patches) > 0,
        }
