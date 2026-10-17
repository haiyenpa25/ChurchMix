"""
ChurchMix Scene Vault & Snapshot Archive Manager.
================================================
Provides persistent snapshot versioning, automated Talkback invariant checks,
native Behringer X32 (.scn) USB file generation, and visual side-by-side delta diffing.
"""
from __future__ import annotations
import os
import time
import json
import hashlib
from typing import Dict, Any, List, Optional, Tuple

from packages.storage.database import ChurchMixDatabase
from packages.x32_osc_adapter.client import Snapshot
from packages.x32_osc_adapter.scene_exporter import SceneExporter
from packages.safety_controller.routing import RoutingGraph
from packages.eq_optimizer.recommender import x32_to_freq, x32_to_gain, x32_to_q


class SceneVaultManager:
    """Manages scene backups, USB .scn exports, and snapshot delta diffing."""

    def __init__(self, db: Optional[ChurchMixDatabase] = None):
        self.db = db or ChurchMixDatabase()

    def create_backup(
        self,
        name: str,
        author: str = "Operator",
        note: str = "",
        state_dict: Optional[Dict[str, Any]] = None,
        mixer_id: str = "X32_Compact",
    ) -> Dict[str, Any]:
        """Save a new versioned snapshot into the vault with SHA-256 integrity check."""
        if not state_dict:
            raise ValueError("State parameters dictionary cannot be empty.")

        # Compute deterministic SHA-256
        clean_name = name.strip() or "Untitled_Backup"
        sorted_state = json.dumps(state_dict, sort_keys=True)
        sha256 = hashlib.sha256(sorted_state.encode("utf-8")).hexdigest()

        # Verify Talkback Invariant
        routing = RoutingGraph(state_dict)
        tb_safe, tb_msg = routing.verify_talkback_invariant()

        backup_id = self.db.save_snapshot(
            sha256=sha256,
            state_dict=state_dict,
            mixer_id=mixer_id,
            author=author,
            note=f"[{clean_name}] {note}".strip(),
        )

        # Log audit event
        self.db.save_audit_event(
            actor=author,
            action="VAULT_BACKUP_CREATED",
            status="COMMITTED",
            details={
                "backup_id": backup_id,
                "name": clean_name,
                "sha256": sha256,
                "talkback_invariant": tb_safe,
            },
        )

        return {
            "id": backup_id,
            "name": clean_name,
            "sha256": sha256,
            "author": author,
            "note": note,
            "talkback_safe": tb_safe,
            "talkback_message": tb_msg,
            "captured_at": time.time(),
        }

    def list_backups(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List all archived snapshots with metadata and parsed title."""
        rows = self.db.get_snapshots(limit=limit)
        results = []
        for r in rows:
            raw_note = r.get("note") or ""
            # Extract name if formatted as [Name] Note
            name = "Snapshot"
            note = raw_note
            if raw_note.startswith("[") and "]" in raw_note:
                parts = raw_note[1:].split("]", 1)
                name = parts[0]
                note = parts[1].strip() if len(parts) > 1 else ""

            results.append({
                "id": r["id"],
                "name": name,
                "mixer_id": r["mixer_id"],
                "sha256": r["sha256"],
                "captured_at": r["captured_at"],
                "iso_time": r["iso_time"],
                "author": r["author"],
                "note": note,
            })
        return results

    def get_backup(self, backup_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve full backup including state parameters."""
        return self.db.get_snapshot_by_id(backup_id)

    def delete_backup(self, backup_id: int, actor: str = "Operator") -> bool:
        """Remove a snapshot from the vault and audit the deletion."""
        success = self.db.delete_snapshot(backup_id)
        if success:
            self.db.save_audit_event(
                actor=actor,
                action="VAULT_BACKUP_DELETED",
                status="COMMITTED",
                details={"backup_id": backup_id},
            )
        return success

    def export_backup_scn(self, backup_id: int) -> Dict[str, Any]:
        """Export snapshot as native Behringer X32 ASCII Scene (.scn) file."""
        backup = self.get_backup(backup_id)
        if not backup:
            raise ValueError(f"Backup ID {backup_id} not found.")

        state = backup["state"]
        raw_note = backup.get("note") or "ChurchMix_Scene"
        scene_name = "ChurchMix"
        if raw_note.startswith("[") and "]" in raw_note:
            scene_name = raw_note[1:].split("]", 1)[0]

        snapshot = Snapshot(
            parameters=state,
            sha256=backup["sha256"],
            timestamp=backup.get("captured_at", time.time()),
            iso_time=backup.get("iso_time", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            mixer_info={"model": backup.get("mixer_id", "X32_Compact"), "firmware": "4.06"},
            channel_count=32,
        )
        scn_content = SceneExporter.export_scn(snapshot, scene_name=scene_name)

        filename = f"{scene_name.replace(' ', '_')[:16]}_{time.strftime('%Y%m%d')}.scn"
        return {
            "filename": filename,
            "scene_name": scene_name,
            "content": scn_content,
            "sha256": backup["sha256"],
        }

    def diff_backups(self, backup_id_a: int, backup_id_b: int) -> Dict[str, Any]:
        """Compare two stored snapshots and generate a detailed delta."""
        b_a = self.get_backup(backup_id_a)
        b_b = self.get_backup(backup_id_b)
        if not b_a:
            raise ValueError(f"Backup A (ID {backup_id_a}) not found.")
        if not b_b:
            raise ValueError(f"Backup B (ID {backup_id_b}) not found.")

        name_a = b_a.get("note", "Backup A")
        name_b = b_b.get("note", "Backup B")

        return self.diff_states(
            state_a=b_a["state"],
            state_b=b_b["state"],
            label_a=f"ID {backup_id_a}: {name_a}",
            label_b=f"ID {backup_id_b}: {name_b}",
        )

    def diff_states(
        self,
        state_a: Dict[str, Any],
        state_b: Dict[str, Any],
        label_a: str = "State A",
        label_b: str = "State B",
    ) -> Dict[str, Any]:
        """Perform granular channel-by-channel and routing comparison."""
        routing_a = RoutingGraph(state_a)
        routing_b = RoutingGraph(state_b)

        tb_a_safe, tb_a_msg = routing_a.verify_talkback_invariant()
        tb_b_safe, tb_b_msg = routing_b.verify_talkback_invariant()

        channel_diffs = []

        for ch in range(1, 33):
            prefix = f"/ch/{ch:02d}"
            diffs_for_ch = []

            # 1. Name
            name_a = state_a.get(f"{prefix}/config/name", f"Ch {ch}")
            name_b = state_b.get(f"{prefix}/config/name", f"Ch {ch}")
            if name_a != name_b:
                diffs_for_ch.append(f"Tên: '{name_a}' -> '{name_b}'")

            # 2. Fader
            fader_a = float(state_a.get(f"{prefix}/mix/fader", 0.75))
            fader_b = float(state_b.get(f"{prefix}/mix/fader", 0.75))
            if abs(fader_a - fader_b) >= 0.01:
                pct_a = round(fader_a * 100)
                pct_b = round(fader_b * 100)
                diffs_for_ch.append(f"Fader: {pct_a}% -> {pct_b}% (Δ {pct_b - pct_a:+d}%)")

            # 3. Mute / On
            on_a = int(state_a.get(f"{prefix}/mix/on", 1))
            on_b = int(state_b.get(f"{prefix}/mix/on", 1))
            if on_a != on_b:
                state_txt_a = "ON" if on_a else "MUTE"
                state_txt_b = "ON" if on_b else "MUTE"
                diffs_for_ch.append(f"Trạng thái: {state_txt_a} -> {state_txt_b}")

            # 4. HPF
            hpon_a = int(state_a.get(f"{prefix}/preamp/hpon", 0))
            hpon_b = int(state_b.get(f"{prefix}/preamp/hpon", 0))
            if hpon_a != hpon_b:
                diffs_for_ch.append(f"HPF: {'Bật' if hpon_a else 'Tắt'} -> {'Bật' if hpon_b else 'Tắt'}")

            # 5. PEQ Bands
            eq_on_a = int(state_a.get(f"{prefix}/eq/on", 1))
            eq_on_b = int(state_b.get(f"{prefix}/eq/on", 1))
            if eq_on_a != eq_on_b:
                diffs_for_ch.append(f"EQ: {'Bật' if eq_on_a else 'Bypass'} -> {'Bật' if eq_on_b else 'Bypass'}")

            for b in range(1, 5):
                g_a = float(state_a.get(f"{prefix}/eq/{b}/g", 0.5))
                g_b = float(state_b.get(f"{prefix}/eq/{b}/g", 0.5))
                if abs(g_a - g_b) >= 0.02:
                    gain_db_a = x32_to_gain(g_a)
                    gain_db_b = x32_to_gain(g_b)
                    diffs_for_ch.append(f"PEQ Band {b} Gain: {gain_db_a:+.1f}dB -> {gain_db_b:+.1f}dB")

            if diffs_for_ch:
                channel_diffs.append({
                    "channel": ch,
                    "name_a": name_a,
                    "name_b": name_b,
                    "is_talkback": ch == 11,
                    "changes": diffs_for_ch,
                })

        # Summary text
        summary_vi = (
            f"So sánh giữa [{label_a}] và [{label_b}]: "
            f"Phát hiện {len(channel_diffs)} kênh có sự thay đổi tham số. "
            f"Bất biến Talkback DL16 #11: {'An toàn trên cả 2 bản' if (tb_a_safe and tb_b_safe) else 'CẢNH BÁO VI PHẠM!'}"
        )

        return {
            "label_a": label_a,
            "label_b": label_b,
            "total_channels_changed": len(channel_diffs),
            "talkback_status_a": {"safe": tb_a_safe, "message": tb_a_msg},
            "talkback_status_b": {"safe": tb_b_safe, "message": tb_b_msg},
            "summary_vi": summary_vi,
            "channel_diffs": channel_diffs,
        }
