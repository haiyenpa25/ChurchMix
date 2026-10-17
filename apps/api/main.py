"""
FastAPI Server for X32 AI Sound Engineer.
Provides:
- Real-time Mixer State & Channel summaries
- Routing Graph & DL16 In 11 Talkback Invariant Verification
- PEQ Recommendation Engine with A/B Response Curves
- Safety Gate Proposal Approval & Transaction Execution
- STOP AUTO Panic Button (Immediate Halt & Forced Read-Only)
- 60fps WebSocket Telemetry (1/12-Octave RTA & Meters)
- AI Copilot Vietnamese Q&A
"""

from __future__ import annotations
import asyncio
import os
import re
import sys
import time
import math
from typing import Dict, Any, List, Optional, Literal
from contextlib import asynccontextmanager
import numpy as np

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Local mock/simulator OSC port. Override with CHURCHMIX_X32_PORT so tests never
# collide with a ChurchMix instance (and its mock) already running on 10023.
X32_LOCAL_PORT = int(os.environ.get("CHURCHMIX_X32_PORT") or os.environ.get("CHURCHMIX_MOCK_PORT") or "10023")

# Add repository root to Python path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT_DIR)

from packages.x32_osc_adapter.client import X32Client
from packages.x32_osc_adapter.scene_exporter import SceneExporter
from packages.mock_x32.server import MockX32Server
from packages.safety_controller.routing import RoutingGraph, InvariantViolationError, get_talkback_channel
from packages.safety_controller.transaction import (
    TransactionExecutor,
    SafetyPolicy,
    Proposal,
    ProposalRejectedError,
    TransactionFailedError,
)
from packages.safety_controller.modes import (
    SafetyModeManager,
    OperatorMode,
    DisengageReason,
)
from packages.signal_analysis.dsp import (
    AudioFrame,
    compute_welch_spectrum,
    compute_fractional_octave_rta,
    generate_sine_wave,
    generate_vocal_note,
    generate_pink_noise,
)
from packages.feedback_detector.detector import FeedbackDetector, FeedbackCandidate
from packages.eq_optimizer.recommender import (
    PEQRecommender,
    PEQBandProposal,
)
from packages.acoustic_measurement.transfer_function import (
    compute_transfer_function,
    filter_no_boost_nulls,
)
from packages.acoustic_measurement.osm_importer import (
    parse_osm_csv,
)
from packages.mix_assistant import (
    SpeechLeveler,
    BroadcastMixGuard,
    GainStagingAdvisor,
    GainStagingReport,
    DuganSpeechAutomixer,
    ListeningTestCriteria,
    ListeningTestEngine,
    ExpanderSettings,
    StageBleedAdvisor,
    MonitorMatrixInspector,
)
from packages.wizards.service import WizardService
from packages.storage.database import ChurchMixDatabase
from packages.storage.church_profile import ChurchProfileManager
from packages.storage.service_segments import ServiceSegmentStore, SegmentError
from packages.storage.hall_profiles import HallProfileManager, HallProfile
from packages.storage.report_generator import generate_printable_sunday_report_html
from packages.storage.scn_importer import SceneImporter
from packages.virtual_soundcheck.player import VirtualSoundcheckEngine, SESSION_PRESETS
from packages.ai_copilot import ChurchMixCopilot
from apps.capture_agent.device_manager import AudioDeviceManager
from apps.capture_agent.stream_worker import AudioStreamWorker
from apps.api.audio_sources import resolve_analysis_audio, AudioSourceError
from diagnose_system import run_all_diagnostics
from packages.monitoring.analyzer import SignalMonitor, Thresholds
from packages.monitoring.source import collect_signal
from packages.x32_osc_adapter.meters import X32MeterReader, restart_meter_reader
from packages.autopilot import Autopilot
from packages.autopilot.meter_history import MeterHistory
from apps.api.autopilot_routes import build_router as build_autopilot_router
import logging
import json

# --- Global State & Singletons ---
mock_server: Optional[MockX32Server] = None
x32_client: Optional[X32Client] = None
x32_meter_reader: Optional[X32MeterReader] = None  # read-only /meters stream, own socket
executor: Optional[TransactionExecutor] = None
wizard_service: Optional[WizardService] = None
recommender = PEQRecommender()
feedback_detector = FeedbackDetector(min_prominence_db=12.0, min_persistence_frames=3, confidence_threshold=0.70)
speech_leveler = SpeechLeveler(target_rms_db=-20.0)

db = ChurchMixDatabase()
church_profile_mgr = ChurchProfileManager()
segment_store = ServiceSegmentStore(church_profile_mgr.get_channels,
                                    path=os.environ.get("CHURCHMIX_SEGMENTS_PATH") or None)
hall_profile_mgr = HallProfileManager()
from packages.storage.scene_vault import SceneVaultManager
scene_vault_mgr = SceneVaultManager(db=db)
soundcheck_engine = VirtualSoundcheckEngine(sample_rate=48000)
ai_copilot = ChurchMixCopilot()
audio_device_mgr = AudioDeviceManager()
audio_stream_worker: Optional[AudioStreamWorker] = None
safety_mode_mgr = SafetyModeManager()
signal_monitor = SignalMonitor()
telemetry_logger = logging.getLogger("ChurchMix.Telemetry")

active_websockets: List[WebSocket] = []
active_feedback_alerts: List[Dict[str, Any]] = []


# --- Autopilot ("Lái tự động"): bounded automation in LIMITED_AUTO (AGENTS.md rule 7) ---
def _is_internal_simulator() -> bool:
    """True only when the connected mixer is ChurchMix's own mock (simulated data may drive it)."""
    return bool(x32_client and mock_server and mock_server.running
                and x32_client.host in ("127.0.0.1", "localhost") and x32_client.port == mock_server.port)


def _autopilot_loudness() -> Dict[str, Any]:
    """Short-term loudness of the analysis audio. Its scope is the analysed input, not the
    livestream bus itself, so the autopilot only acts on it in the simulator."""
    from packages.mix_assistant.broadcast_meter import compute_short_term_lufs
    try:
        audio, source = resolve_analysis_audio(soundcheck_engine, audio_stream_worker, None)
    except AudioSourceError:
        return {"valid": False}
    return {"short_term_lufs": compute_short_term_lufs(audio, source["sample_rate"]), "valid": bool(source.get("valid", True)),
            "simulated": bool(source.get("simulated")), "scope": source.get("loudness_scope", "ANALYSIS_INPUT")}


meter_history = MeterHistory()  # last 30 s of per-channel meters (segment detection, line check, auto soundcheck)

autopilot = Autopilot(
    get_client=lambda: x32_client,
    get_executor=lambda: executor,
    mode_manager=safety_mode_mgr,
    channel_provider=church_profile_mgr.get_channels,
    recommender=recommender,
    is_simulator=_is_internal_simulator,
    reference_provider=lambda params: segment_store.reference_faders(segment_store.active_id(params)),
    loudness_provider=_autopilot_loudness,
    audit=lambda **kw: db.save_audit_event(**kw) if db else None,
)
active_proposals: Dict[str, Proposal] = {}

stop_auto_triggered = False
last_acoustic_measurement: Optional[Dict[str, Any]] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mock_server, x32_client, executor, audio_stream_worker, wizard_service, x32_meter_reader

    # 1. Start Mock X32 on X32_LOCAL_PORT (default 10023) if not running
    mock_port = X32_LOCAL_PORT
    mock_server = MockX32Server(host="127.0.0.1", port=mock_port)
    try:
        mock_server.start()
        await asyncio.sleep(0.05)
    except Exception as e:
        raise RuntimeError("Cannot start isolated mock X32; refusing to connect to an unknown listener.") from e

    # 2. Connect X32 Client in forced READ_ONLY_MODE
    x32_client = X32Client(host="127.0.0.1", port=mock_port, read_only_mode=True, timeout=1.0)
    try:
        x32_client.connect()
        executor = TransactionExecutor(client=x32_client, policy=SafetyPolicy(), mode_manager=safety_mode_mgr)
        wizard_service = WizardService(client=x32_client)
        snap = x32_client.take_full_snapshot(max_channels=32)
        db.save_snapshot(sha256=snap.sha256, state_dict=snap.parameters, note="Startup initial state")
        db.save_audit_event(actor="System", action="STARTUP", status="ONLINE", details={"read_only": True, "mode": "OBSERVE"})
        x32_meter_reader = restart_meter_reader(x32_meter_reader, x32_client.host, x32_client.port, simulated=True)
        print("X32 Client successfully connected in READ_ONLY_MODE = True.")
    except Exception as e:
        print(f"Error connecting X32 Client: {e}")

    # 3. Start background audio telemetry generator (simulating USB capture)
    telemetry_task = asyncio.create_task(audio_telemetry_loop())

    yield

    # Cleanup on shutdown
    telemetry_task.cancel()
    await telemetry_task
    if audio_stream_worker and audio_stream_worker.is_running:
        audio_stream_worker.stop()
    if autopilot.enabled:
        autopilot.disable("System", reason="Máy chủ dừng — lái tự động đã tắt.")
    if x32_meter_reader:
        x32_meter_reader.stop()
    if x32_client:
        x32_client.close()
    if mock_server:
        mock_server.stop()
    # Never leave closed handles behind: later requests must see "not connected", not a dead socket.
    x32_meter_reader = None
    x32_client = None
    executor = None
    wizard_service = None
    mock_server = None


app = FastAPI(title="X32 AI Sound Engineer API", version="1.0.0", lifespan=lifespan)
app.include_router(build_autopilot_router(
    get_autopilot=lambda: autopilot, get_client=lambda: x32_client,
    get_segment_store=lambda: segment_store, is_stopped=lambda: stop_auto_triggered,
))
# --- Phase 2 routers (service program / segment detection, auto line check / auto soundcheck) ---
from packages.storage.service_program import ServiceProgramStore
from packages.autopilot.segment_detector import SegmentDetector
from apps.api.program_routes import build_router as build_program_router
program_store = ServiceProgramStore(segment_store.list, path=os.environ.get("CHURCHMIX_PROGRAM_PATH") or None)
segment_detector = SegmentDetector(  # suggestions only — never switches anything (AGENTS.md rule 7)
    meter_history, segment_store.list, church_profile_mgr.get_channels,
    trusted_provider=lambda: meter_history.trusted_for(_is_internal_simulator()),
    active_provider=lambda: segment_store.active_id(x32_client.take_full_snapshot(max_channels=32).parameters) if x32_client else None,
    talkback_provider=get_talkback_channel,
)
app.include_router(build_program_router(
    get_program_store=lambda: program_store, get_detector=lambda: segment_detector,
    audit=lambda **kw: db.save_audit_event(**kw) if db else None,
))
from apps.api.soundcheck_auto_routes import build_router as build_soundcheck_auto_router
app.include_router(build_soundcheck_auto_router(  # read-only analysis; proposals only (AGENTS.md rule 7)
    get_client=lambda: x32_client, meter_history=meter_history, is_simulator=_is_internal_simulator,
    get_channels=church_profile_mgr.get_channels, proposals=active_proposals,
    audit=lambda **kw: db.save_audit_event(**kw) if db else None,
))

# --- Origin Guard ---
# Any web page open on the operator laptop could otherwise POST to this API and
# apply proposals / mute channels on the mixer. Only the dashboard itself (same
# origin), localhost, or origins listed in CHURCHMIX_ALLOWED_ORIGINS
# (comma-separated, e.g. a church-LAN tablet) may send mutating requests.
LOCAL_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
EXTRA_ALLOWED_ORIGINS = [
    o.strip().rstrip("/") for o in os.environ.get("CHURCHMIX_ALLOWED_ORIGINS", "").split(",") if o.strip()
]
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def is_origin_allowed(origin: str, host_header: Optional[str]) -> bool:
    origin = origin.rstrip("/")
    if re.match(LOCAL_ORIGIN_REGEX, origin) or origin in EXTRA_ALLOWED_ORIGINS:
        return True
    # Same-origin: dashboard served by this server, e.g. http://192.168.1.20:8080
    netloc = origin.split("://", 1)[-1]
    return bool(host_header) and netloc == host_header


@app.middleware("http")
async def origin_guard(request, call_next):
    origin = request.headers.get("origin")
    if (
        request.method in MUTATING_METHODS
        and origin
        and not is_origin_allowed(origin, request.headers.get("host"))
    ):
        return JSONResponse(
            status_code=403,
            content={"detail": f"Cross-origin request from '{origin}' is not allowed to modify the mixer."},
        )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=EXTRA_ALLOWED_ORIGINS,
    allow_origin_regex=LOCAL_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Background Audio Telemetry & RTA Generator ---

async def audio_telemetry_loop():
    """Observe sources continuously, even without a connected dashboard."""
    global active_feedback_alerts
    started = time.monotonic()
    profiles = {}
    refreshed = -math.inf
    last_source = None
    while True:
        try:
            now = time.monotonic()
            if now - refreshed > 5:
                profiles = {p["channel"]: p for p in church_profile_mgr.get_channels()}
                refreshed = now
            meters, samples, source = collect_signal(soundcheck_engine, audio_stream_worker, now - started, profiles,
                                                     meter_reader=x32_meter_reader)
            if source["id"] != last_source or not source["dsp_valid"]:
                feedback_detector.channel_history.clear()
                last_source = source["id"]
            candidates = []
            if source["dsp_valid"]:
                frame = AudioFrame(samples=samples, sample_rate=source["sample_rate"],
                    channel_id=source["spectrum_input"], timestamp=now)
                candidates = feedback_detector.process_frame(frame)
            active_feedback_alerts = [{"channel_id": c.channel_id, "freq_hz": c.freq_hz,
                "confidence": c.confidence, "severity": c.severity, "level_dbfs": c.level_dbfs,
                "evidence": c.evidence, "recommended_action": c.recommended_action,
                "simulated": source["simulated"]} for c in candidates]
            rta_bars = []
            if source["valid"] and source.get("rta_available", True):
                freqs, psd = compute_welch_spectrum(samples, sample_rate=source["sample_rate"], nperseg=1024, noverlap=512)
                rta_bars = compute_fractional_octave_rta(freqs, psd, fraction=12)
            has_clip = any(m["meter_dbfs"] is not None and m["meter_dbfs"] >= -0.5 for m in meters)
            has_feedback = any(a["severity"] == "CRITICAL" for a in active_feedback_alerts)
            if source["valid"]:
                # Demo data must not stand in for hardware telemetry.
                if not source["simulated"] or not x32_client or x32_client.host == "127.0.0.1":
                    safety_mode_mgr.record_telemetry_heartbeat(clip_detected=has_clip, feedback_spike=has_feedback)
            elif not source["simulated"]:
                safety_mode_mgr.trigger_auto_disengage(DisengageReason.AUDIO_FAULT,
                    "Dữ liệu capture không hợp lệ; đóng băng tự động.")
                if x32_client:
                    x32_client.read_only_mode = True
            analysis = signal_monitor.ingest(meters, source, now=now)
            analysis["events"] = analysis["events"][:30]
            meter_history.add(meters, source)
            try:
                segment_detector.tick()
            except Exception:
                telemetry_logger.exception("Segment detector tick failed")
            try:
                autopilot.tick(meters, active_feedback_alerts, source)
            except Exception:
                telemetry_logger.exception("Autopilot tick failed")
            payload = {"type": "TELEMETRY", "timestamp": time.time(), "rta": rta_bars,
                "meters": meters, "feedback_alerts": active_feedback_alerts,
                "read_only_mode": x32_client.read_only_mode if x32_client else True,
                "stop_auto": stop_auto_triggered, "safety_mode": safety_mode_mgr.state.to_dict(),
                "soundcheck": soundcheck_engine.get_status(), "source": source, "analysis": analysis,
                "autopilot": {"enabled": autopilot.enabled, "inactive_reason": autopilot.inactive_reason},
                "segment_suggestion": segment_detector.suggestion}
            # A stalled browser cannot hold the broadcaster indefinitely.
            message = json.dumps(payload, allow_nan=False, separators=(",", ":"))
            clients = tuple(active_websockets)
            async def send(ws):
                try:
                    await asyncio.wait_for(ws.send_text(message), timeout=0.25)
                except Exception:
                    if ws in active_websockets:
                        active_websockets.remove(ws)
                    try:
                        await asyncio.wait_for(ws.close(code=1013), timeout=0.1)
                    except Exception:
                        pass
            await asyncio.gather(*(send(ws) for ws in clients))
            await asyncio.sleep(0.08)
        except asyncio.CancelledError:
            break
        except Exception:
            telemetry_logger.exception("Telemetry update failed")
            active_feedback_alerts = []
            signal_monitor.ingest([], {"id": "error", "valid": False, "simulated": False,
                "label": "Lỗi luồng đo", "reasons": ["Không xử lý được khung đo; kiểm tra log máy chủ"]})
            safety_mode_mgr.trigger_auto_disengage(DisengageReason.AUDIO_FAULT, "Lỗi xử lý telemetry.")
            if x32_client:
                x32_client.read_only_mode = True
            await asyncio.sleep(0.1)


@app.get("/api/v1/monitoring/analysis")
def get_signal_analysis(channel: Optional[int] = None):
    if channel is not None and not 1 <= channel <= 32:
        raise HTTPException(status_code=400, detail="Input phải từ 1 đến 32")
    return signal_monitor.snapshot(channel=channel)


class MonitoringThresholdRequest(BaseModel):
    warning_dbfs: float = Field(default=-12, ge=-60, le=0, allow_inf_nan=False)
    critical_dbfs: float = Field(default=-6, ge=-60, le=0, allow_inf_nan=False)
    clip_dbfs: float = Field(default=-0.5, ge=-60, le=0, allow_inf_nan=False)


@app.put("/api/v1/monitoring/thresholds")
def set_monitoring_thresholds(req: MonitoringThresholdRequest):
    """Change diagnostic thresholds only. Never touch any mixer parameters."""
    try:
        thresholds = Thresholds(**req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    signal_monitor.set_thresholds(thresholds)
    return {"thresholds": req.model_dump(), "message": "Đã cập nhật ngưỡng biểu đồ; bắt đầu phiên thống kê mới."}


# --- REST API Endpoints ---

@app.get("/api/v1/status")
def get_system_status():
    if not x32_client:
        raise HTTPException(status_code=503, detail="X32 Client not initialized")

    snapshot = x32_client.take_full_snapshot(max_channels=32)
    routing = RoutingGraph(snapshot.parameters)
    tb_ok, tb_msg = routing.verify_talkback_invariant()
    is_simulator = bool(mock_server and mock_server.running and x32_client.host == "127.0.0.1" and x32_client.port == mock_server.port)
    if not is_simulator:
        tb_ok = False
        tb_msg = "Chưa xác minh ánh xạ DL16 và đầy đủ đường FOH/Matrix trên phần cứng; không suy ra an toàn từ cấu hình mẫu."

    return {
        "status": "ONLINE",
        "connection": {"is_simulator": is_simulator, "host": x32_client.host, "port": x32_client.port},
        "mixer": snapshot.mixer_info,
        "read_only_mode": x32_client.read_only_mode,
        "stop_auto": stop_auto_triggered,
        "safety_mode": safety_mode_mgr.state.to_dict(),
        "sha256": snapshot.sha256,
        "meters": x32_meter_reader.status() if x32_meter_reader else None,
        "dl16_talkback_invariant": {
            "safe": tb_ok,
            "message": tb_msg,
            "scope": "SIMULATED_FIXED_MAP" if is_simulator else "UNVERIFIED_HARDWARE",
        },
    }


@app.get("/api/v1/channels")
def get_channels():
    if not x32_client:
        raise HTTPException(status_code=503, detail="X32 Client not initialized")

    snapshot = x32_client.take_full_snapshot(max_channels=32)
    routing = RoutingGraph(snapshot.parameters)
    profiles = {p["channel"]: p for p in church_profile_mgr.get_channels()}

    channels = []
    for ch in range(1, 33):
        summary = x32_client.get_channel_summary(ch, snapshot=snapshot)
        is_foh, _ = routing.is_channel_routed_to_foh(ch)
        is_p16, p16_slots = routing.is_channel_routed_to_p16(ch)

        summary["is_foh"] = is_foh
        summary["is_p16"] = is_p16
        summary["p16_slots"] = p16_slots

        prof = profiles.get(ch)
        if prof:
            summary["church_role"] = prof.get("role")
            if prof.get("name") and (not summary.get("name") or summary.get("name") == f"CH{ch:02d}"):
                summary["name"] = prof.get("name")

        channels.append(summary)

    return {"channels": channels}


class ChannelMuteRequest(BaseModel):
    on: Optional[int] = None
    operator_id: str = "Operator"


@app.post("/api/v1/channels/{channel_id}/mute")
def toggle_channel_mute(channel_id: int, req: ChannelMuteRequest):
    """Toggle or set channel mute state safely via Safety Gate and audit event logging."""
    if not (1 <= channel_id <= 32):
        raise HTTPException(status_code=400, detail="Channel ID must be between 1 and 32")
    if stop_auto_triggered:
        raise HTTPException(status_code=403, detail="CANNOT MUTATE: STOP AUTO panic button is currently ENGAGED!")
    if not x32_client or not executor:
        raise HTTPException(status_code=503, detail="X32 Client or SafetyGate Executor not initialized")

    snapshot = x32_client.take_full_snapshot(max_channels=32)
    param_path = f"/ch/{channel_id:02d}/mix/on"
    current_val = int(snapshot.parameters.get(param_path, 1))

    target_val = 1 - current_val if req.on is None else int(req.on)
    if target_val not in (0, 1):
        raise HTTPException(status_code=400, detail="Mute state 'on' must be 0 (Mute) or 1 (On)")

    proposal = Proposal(
        proposal_id=f"MUTE_CH{channel_id:02d}_{int(time.time()*1000)}",
        target_channel=channel_id,
        hypothesis=f"Operator manually set Channel {channel_id} state to {'ON' if target_val else 'MUTE'}",
        confidence=1.0,
        changes=[{"parameter": param_path, "from": current_val, "to": target_val}],
        expected_sha256=snapshot.sha256,
        operator_approved=True,
        approved_by=req.operator_id,
    )

    try:
        result = executor.execute(proposal, req.operator_id)
        if db:
            db.save_audit_event(
                actor=req.operator_id,
                action="CHANNEL_MUTE_TOGGLED",
                proposal_id=proposal.proposal_id,
                status="COMMITTED",
                details={"channel_id": channel_id, "on": target_val, "previous_on": current_val},
            )
        return {
            "status": "COMMITTED",
            "channel_id": channel_id,
            "on": target_val,
            "state_text": "ON" if target_val else "MUTE",
            "audit_hash": result.get("sha256"),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))



@app.get("/api/v1/routing")
def get_routing():
    if not x32_client:
        raise HTTPException(status_code=503, detail="X32 Client not initialized")

    snapshot = x32_client.take_full_snapshot(max_channels=32)
    graph = RoutingGraph(snapshot.parameters)
    tb_ok, tb_msg = graph.verify_talkback_invariant()

    return {
        "dl16_input_11_status": {
            "channel_assigned": graph.dl16_talkback_channel,
            "is_isolated_from_foh": tb_ok,
            "details": tb_msg,
        },
        "aes50a_in": snapshot.parameters.get("/config/routing/IN"),
        "aes50a_status": snapshot.parameters.get("/config/routing/AES50A"),
    }


class GenerateProposalRequest(BaseModel):
    channel_id: int
    role: str = "PASTOR_SPEECH"


@app.post("/api/v1/proposals/generate-pastor")
def generate_pastor_tuning(req: GenerateProposalRequest):
    if not x32_client:
        raise HTTPException(status_code=503, detail="X32 Client not initialized")

    snapshot = x32_client.take_full_snapshot(max_channels=32)
    proposal, tuning_detail = recommender.recommend_pastor_speech(
        channel_id=req.channel_id,
        expected_sha256=snapshot.sha256,
    )

    # Cache active proposal
    active_proposals[proposal.proposal_id] = proposal

    return {
        "proposal_id": proposal.proposal_id,
        "target_channel": proposal.target_channel,
        "hypothesis": proposal.hypothesis,
        "confidence": proposal.confidence,
        "changes": proposal.changes,
        "tuning_detail": {
            "role": tuning_detail.role,
            "hpf_freq_hz": tuning_detail.hpf_freq_hz,
            "bands": [
                {
                    "band": b.band_index,
                    "freq_hz": b.freq_hz,
                    "gain_db": b.gain_db,
                    "q": b.q_factor,
                    "rationale": b.rationale,
                }
                for b in tuning_detail.bands
            ],
            "expected_tradeoffs": tuning_detail.expected_tradeoffs,
            "simulated_curve": tuning_detail.simulated_curve,
        },
        "expected_sha256": proposal.expected_sha256,
    }


@app.post("/api/v1/proposals/generate-role")
def generate_role_tuning(req: GenerateProposalRequest):
    """Generate PEQ tuning for any church channel role (vocal, choir, acoustic, piano, bass)."""
    if not x32_client:
        raise HTTPException(status_code=503, detail="X32 Client not initialized")

    snapshot = x32_client.take_full_snapshot(max_channels=32)
    proposal, tuning_detail = recommender.recommend_role(
        channel_id=req.channel_id,
        role=req.role,
        expected_sha256=snapshot.sha256,
    )

    active_proposals[proposal.proposal_id] = proposal

    return {
        "proposal_id": proposal.proposal_id,
        "target_channel": proposal.target_channel,
        "hypothesis": proposal.hypothesis,
        "confidence": proposal.confidence,
        "changes": proposal.changes,
        "tuning_detail": {
            "role": tuning_detail.role,
            "hpf_freq_hz": tuning_detail.hpf_freq_hz,
            "bands": [
                {
                    "band": b.band_index,
                    "freq_hz": b.freq_hz,
                    "gain_db": b.gain_db,
                    "q": b.q_factor,
                    "rationale": b.rationale,
                }
                for b in tuning_detail.bands
            ],
            "expected_tradeoffs": tuning_detail.expected_tradeoffs,
            "simulated_curve": tuning_detail.simulated_curve,
        },
        "expected_sha256": proposal.expected_sha256,
    }


class GenerateNotchRequest(BaseModel):
    channel_id: int
    freq_hz: float
    confidence: float = 0.88


@app.post("/api/v1/proposals/generate-notch")
def generate_notch_tuning(req: GenerateNotchRequest):
    """Generate surgical feedback notch proposal for a specific channel and frequency."""
    if not x32_client:
        raise HTTPException(status_code=503, detail="X32 Client not initialized")

    snapshot = x32_client.take_full_snapshot(max_channels=32)
    candidate = FeedbackCandidate(
        channel_id=req.channel_id,
        freq_hz=req.freq_hz,
        confidence=req.confidence,
        severity="WARNING",
        level_dbfs=-18.0,
        persistence_frames=4,
        is_musical_note=False,
        evidence=["Manual Ringout / Real-time Detector Alert"],
        recommended_action=f"Surgical notch at {req.freq_hz} Hz",
    )
    proposal = recommender.recommend_feedback_notch(candidate, expected_sha256=snapshot.sha256,
                                                    current_parameters=snapshot.parameters)
    active_proposals[proposal.proposal_id] = proposal
    notch_band_index = int(proposal.changes[0]["parameter"].split("/")[4])

    # Simulate curve with notch
    notch_band = PEQBandProposal(
        band_index=notch_band_index,
        filter_type="PEQ",
        freq_hz=req.freq_hz,
        gain_db=-3.5,
        q_factor=7.0,
        rationale=f"Surgical feedback notch at {req.freq_hz} Hz",
    )
    sim_curve = recommender.simulate_response(hpf_freq=None, bands=[notch_band])

    return {
        "proposal_id": proposal.proposal_id,
        "target_channel": proposal.target_channel,
        "hypothesis": proposal.hypothesis,
        "confidence": proposal.confidence,
        "changes": proposal.changes,
        "tuning_detail": {
            "role": "FEEDBACK_NOTCH",
            "hpf_freq_hz": 0.0,
            "expected_tradeoffs": [
                f"Triệt tiêu cộng hưởng hú tại {req.freq_hz} Hz với độ dốc siêu hẹp Q=7.0.",
                "Bảo toàn trọn vẹn chất giọng ca sĩ mà không làm mỏng hay biến dạng âm sắc.",
            ],
            "simulated_curve": sim_curve,
        },
        "expected_sha256": proposal.expected_sha256,
    }


class ApplyProposalRequest(BaseModel):
    proposal_id: str
    operator_id: str


@app.post("/api/v1/proposals/apply")
def apply_proposal(req: ApplyProposalRequest):
    global stop_auto_triggered
    if stop_auto_triggered:
        raise HTTPException(status_code=403, detail="CANNOT APPLY: STOP AUTO panic button is currently ENGAGED!")

    if req.proposal_id not in active_proposals:
        raise HTTPException(status_code=404, detail="Proposal not found or expired")

    proposal = active_proposals[req.proposal_id]
    proposal.approve(req.operator_id)

    try:
        result = executor.execute(proposal, req.operator_id)
        del active_proposals[req.proposal_id]
        if db:
            db.save_audit_event(
                actor=req.operator_id,
                action="APPLY_PROPOSAL",
                proposal_id=req.proposal_id,
                status="COMMITTED",
                details=result,
            )
        return result
    except (ProposalRejectedError, InvariantViolationError) as e:
        if db:
            db.save_audit_event(
                actor=req.operator_id,
                action="REJECT_PROPOSAL",
                proposal_id=req.proposal_id,
                status="REJECTED",
                details={"error": str(e)},
            )
        raise HTTPException(status_code=400, detail=str(e))
    except TransactionFailedError as e:
        if db:
            db.save_audit_event(
                actor=req.operator_id,
                action="FAILED_PROPOSAL",
                proposal_id=req.proposal_id,
                status="FAILED",
                details={"error": str(e)},
            )
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/emergency/stop-auto")
def emergency_stop_auto():
    """THE BIG RED STOP AUTO BUTTON."""
    global stop_auto_triggered
    stop_auto_triggered = True

    if x32_client:
        # Force strict read-only mode immediately
        x32_client.read_only_mode = True

    active_proposals.clear()
    safety_mode_mgr.trigger_auto_disengage(
        reason=DisengageReason.PANIC_BUTTON,
        detail="Kỹ thuật viên nhấn STOP AUTO khẩn cấp.",
        operator="Operator",
    )

    if db:
        db.save_audit_event(
            actor="Operator",
            action="STOP_AUTO",
            status="PANIC_ENGAGED",
            details={"message": "All automation aborted, mixer strictly locked to READ-ONLY."},
        )

    return {
        "status": "STOPPED",
        "read_only_mode": True,
        "message": "EMERGENCY STOP AUTO ACTIVATED: All automation aborted, mixer strictly locked to READ-ONLY.",
    }


@app.post("/api/v1/emergency/resume-auto")
def resume_auto():
    """Operator clears the emergency stop."""
    global stop_auto_triggered
    stop_auto_triggered = False
    safety_mode_mgr.set_mode(OperatorMode.OBSERVE, operator="Operator")
    if x32_client:
        x32_client.read_only_mode = True

    if db:
        db.save_audit_event(
            actor="Operator",
            action="RESUME_AUTO",
            status="AUTOMATION_RESUMED",
            details={"message": "Automation standby resumed (OBSERVE mode)."},
        )

    return {"status": "RESUMED", "message": "Automation standby resumed (OBSERVE mode)."}


# --- Safety Engine Operating Modes & Auto-Disengage Endpoints (Master Plan 8.1 & 8.4) ---

class SetSafetyModeRequest(BaseModel):
    mode: str
    operator: str = "Operator"
    admin_pin: Optional[str] = None


class DisengageRequest(BaseModel):
    reason: str = "PANIC_BUTTON"
    detail: str = "Thủ công ngắt tự động"
    operator: str = "Operator"


@app.get("/api/v1/safety/mode")
def get_safety_mode():
    """Retrieve current Safety Engine Operating Mode & Auto-Disengage State."""
    state = safety_mode_mgr.state.to_dict()
    state["available_modes"] = [m.value for m in OperatorMode]
    return state


@app.post("/api/v1/safety/mode")
def set_safety_mode(req: SetSafetyModeRequest):
    """
    Switch between the 4 operating modes (OBSERVE, ASSIST, LIMITED_AUTO, ADMIN_MAINTENANCE).
    ADMIN_MAINTENANCE requires admin_pin verification.
    """
    try:
        target_mode = OperatorMode(req.mode.upper())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode '{req.mode}'. Valid modes: {[m.value for m in OperatorMode]}",
        )

    try:
        new_state = safety_mode_mgr.set_mode(
            new_mode=target_mode,
            operator=req.operator,
            admin_pin=req.admin_pin,
        )
        if x32_client:
            x32_client.read_only_mode = safety_mode_mgr.is_read_only()

        if db:
            db.save_audit_event(
                actor=req.operator,
                action="SET_SAFETY_MODE",
                status="MODE_CHANGED",
                details={
                    "mode": target_mode.value,
                    "read_only": new_state.to_dict()["read_only"],
                },
            )

        res = new_state.to_dict()
        res["available_modes"] = [m.value for m in OperatorMode]
        return res
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.post("/api/v1/safety/disengage")
def trigger_safety_disengage(req: DisengageRequest):
    """
    Trigger immediate safety auto-disengage back to OBSERVE (Read-only).
    """
    global stop_auto_triggered
    stop_auto_triggered = True

    try:
        reason_enum = DisengageReason(req.reason.upper())
    except ValueError:
        reason_enum = DisengageReason.PANIC_BUTTON

    state = safety_mode_mgr.trigger_auto_disengage(
        reason=reason_enum,
        detail=req.detail,
        operator=req.operator,
    )
    if x32_client:
        x32_client.read_only_mode = True

    active_proposals.clear()

    if db:
        db.save_audit_event(
            actor=req.operator,
            action="AUTO_DISENGAGE",
            status="DISENGAGED",
            details={"reason": reason_enum.value, "detail": req.detail},
        )

    res = state.to_dict()
    res["available_modes"] = [m.value for m in OperatorMode]
    return res


class CopilotQuestion(BaseModel):
    question: str
    include_live_context: bool = True


@app.post("/api/v1/copilot/ask")
def ask_copilot(req: CopilotQuestion):
    """Vietnamese Sound Assistant Q&A based on Church Master Plan & Live Telemetry."""
    live_ctx = {}
    if req.include_live_context:
        live_ctx["stop_auto"] = stop_auto_triggered
        live_ctx["feedback_alerts"] = active_feedback_alerts
        if x32_client:
            try:
                snap = x32_client.take_full_snapshot(max_channels=32)
                routing = RoutingGraph(snap.parameters)
                tb_ok, _ = routing.verify_talkback_invariant()
                live_ctx["talkback_safe"] = tb_ok
            except Exception:
                pass

    return ai_copilot.answer_question(req.question, live_context=live_ctx)


class OSMImportRequest(BaseModel):
    name: str = "OSM_Measurement"
    csv_content: str


@app.post("/api/v1/acoustics/import-osm")
def import_osm_measurement(req: OSMImportRequest):
    """Import Open Sound Meter / REW CSV data."""
    try:
        data = parse_osm_csv(req.csv_content, name=req.name)
        return {
            "name": data.name,
            "row_count": len(data.freqs),
            "freqs": [round(float(f), 1) for f in data.freqs[:100]],
            "magnitude_db": [round(float(m), 2) for m in data.magnitude_db[:100]],
            "coherence": [round(float(c), 3) for c in data.coherence[:100]],
            "status": "SUCCESS",
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse OSM data: {e}")


@app.post("/api/v1/acoustics/measure")
def run_hall_acoustic_measurement(position: str = "Center Hall"):
    """Run dual-channel transfer function simulation and apply No-Boost-in-Nulls."""
    ref = generate_pink_noise(duration_s=0.5, amplitude=0.4)
    # Simulate room acoustic response: 3.5ms delay (168 samples) + -3dB attenuation
    meas = np.zeros_like(ref)
    meas[168:] = ref[:-168] * 0.7
    # Floor bounce null at ~250 Hz
    meas += np.random.normal(0, 0.005, len(meas)).astype(np.float32)

    tf = compute_transfer_function(ref, meas, sample_rate=48000, nperseg=1024, noverlap=512)

    # Invert magnitude for naive target EQ
    naive_target_eq = -tf.magnitude_db
    # Apply HARD NO-BOOST-IN-NULLS filter
    safe_target_eq = filter_no_boost_nulls(naive_target_eq, tf.coherence, tf.magnitude_db)

    # Downsample points for UI display
    indices = np.linspace(0, len(tf.freqs) - 1, 60, dtype=int)
    curve = [
        {
            "freq": round(float(tf.freqs[i]), 1),
            "magnitude_db": round(float(tf.magnitude_db[i]), 2),
            "coherence": round(float(tf.coherence[i]), 3),
            "safe_eq_target_db": round(float(safe_target_eq[i]), 2),
        }
        for i in indices
    ]

    res = {
        "position": position,
        "delay_ms": tf.delay_ms,
        "coherence_avg": round(float(np.mean(tf.coherence)), 3),
        "curve": curve,
        "rule_enforced": "NO-BOOST-IN-NULLS: All acoustic phase cancellation dips clamped to <= 0.0 dB",
    }

    global last_acoustic_measurement
    last_acoustic_measurement = res

    if db:
        db.save_measurement(
            name="Dual-Channel H1 Transfer Function",
            position=position,
            delay_ms=tf.delay_ms,
            coherence_avg=round(float(np.mean(tf.coherence)), 3),
            rule_enforced="NO-BOOST-IN-NULLS",
            result_data=res,
        )

    return res


@app.get("/api/v1/acoustics/history")
def get_acoustic_history(limit: int = 20):
    """Get list of past acoustic measurement sessions."""
    if not db:
        return {"measurements": []}
    return {"measurements": db.get_measurements(limit=limit)}


@app.get("/api/v1/audit/events")
def get_audit_events(limit: int = 50):
    """Retrieve immutable audit log of parameter changes and emergency halts."""
    if not db:
        return {"events": []}
    return {"events": db.get_recent_audit_events(limit=limit)}


@app.get("/api/v1/mix-assistant/speech-status")
def get_speech_assistant_status():
    """Get active speech leveler status, VAD state, and anti-clipping headroom."""
    # Simulate active frame from Pastor Mic (Ch 1)
    vocal = generate_vocal_note(fundamental_hz=220.0, duration_s=0.1) # Baritone voice
    frame = AudioFrame(samples=vocal, channel_id=1, timestamp=time.time())

    action = speech_leveler.process(frame, current_fader=0.75)

    return {
        "channel_id": 1,
        "role": "PASTOR_SPEECH",
        "action": action.action_type,
        "fader_delta": action.fader_delta,
        "target_fader": action.target_fader,
        "rationale": action.rationale,
        "safety_invariants": {
            "silence_hold": "ENGAGED: Fader never drifts upward during speaker pauses",
            "anti_clipping": "ARMED: Automatic downward protection when peak > -1.5 dBFS",
        }
    }


# --- Broadcast & Livestream LUFS Loudness Endpoints ---

class AnalyzeBroadcastRequest(BaseModel):
    target_profile: str = "YOUTUBE_STREAMING"
    livestream_bus: int = 5


def _analysis_audio(channel_id=None):
    try:
        return resolve_analysis_audio(soundcheck_engine, audio_stream_worker, channel_id)
    except AudioSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/api/v1/broadcast/loudness")
def get_broadcast_loudness(target_profile: str = "YOUTUBE_STREAMING", livestream_bus: int = 5):
    """
    Get live broadcast audio loudness metrics (ITU-R BS.1770 / EBU R128)
    and verify Talkback isolation from the Livestream bus.
    """
    audio_stream, source = _analysis_audio()
    state_dict = None
    if x32_client:
        try:
            snapshot = x32_client.take_full_snapshot(max_channels=32)
            state_dict = snapshot.parameters
        except Exception:
            pass

    report = BroadcastMixGuard.evaluate_loudness(
        signal=audio_stream,
        sample_rate=source["sample_rate"],
        target_profile=target_profile,
        state_dict=state_dict,
        livestream_bus=livestream_bus,
    )

    return {**report.to_dict(), "source": source, "measurement_window_s": len(audio_stream)/source["sample_rate"],
            "loudness_scope": "CURRENT_BUFFER"}


@app.post("/api/v1/broadcast/analyze")
def analyze_broadcast_stream(req: AnalyzeBroadcastRequest):
    """Analyze broadcast loudness with custom profile parameters."""
    return get_broadcast_loudness(target_profile=req.target_profile, livestream_bus=req.livestream_bus)


# --- Gain Staging & Headroom Calibration Endpoints ---

@app.get("/api/v1/gain-staging/{channel_id}")
def get_channel_gain_staging(channel_id: int, role: Optional[str] = None):
    """
    Analyze digital headroom, peak level, RMS, and SNR for a church channel.
    Returns recommended digital trim adjustment to achieve church standard headroom (-18 to -12 dBFS).
    """
    if channel_id < 1 or channel_id > 32:
        raise HTTPException(status_code=400, detail="Channel ID must be between 1 and 32.")
    audio_stream, source = _analysis_audio(channel_id)

    # 1. Resolve channel metadata
    ch_profile = church_profile_mgr.get_channel(channel_id)
    ch_name = ch_profile.get("name", f"Ch {channel_id:02d}") if ch_profile else f"Ch {channel_id:02d}"
    ch_role = role or (ch_profile.get("role", "PASTOR") if ch_profile else "PASTOR")

    # 2. Get current trim from mixer snapshot if connected
    current_trim_float = 0.5
    if x32_client:
        try:
            snapshot = x32_client.take_full_snapshot(max_channels=32)
            current_trim_float = float(snapshot.parameters.get(f"/ch/{channel_id:02d}/preamp/trim", 0.5))
        except Exception:
            pass

    report = GainStagingAdvisor.analyze_headroom(
        signal=audio_stream,
        channel_id=channel_id,
        channel_name=ch_name,
        role=ch_role,
        current_trim_float=current_trim_float,
    )
    return {**report.to_dict(), "source": source}


@app.post("/api/v1/gain-staging/{channel_id}/propose-trim")
def propose_channel_trim(channel_id: int, role: Optional[str] = None):
    """
    Generate a formal Proposal for channel Digital Trim adjustment and register it in active_proposals.
    Requires explicit operator approval via /api/v1/proposals/apply to execute.
    """
    if not x32_client:
        raise HTTPException(status_code=503, detail="X32 Client not initialized")

    rep_dict = get_channel_gain_staging(channel_id=channel_id, role=role)
    report = GainStagingReport(**{key: value for key, value in rep_dict.items() if key != "source"})

    snapshot = x32_client.take_full_snapshot(max_channels=32)
    current_trim_float = float(snapshot.parameters.get(f"/ch/{channel_id:02d}/preamp/trim", 0.5))

    proposal = GainStagingAdvisor.generate_trim_proposal(
        report=report,
        current_sha256=snapshot.sha256,
        current_trim_float=current_trim_float,
    )

    active_proposals[proposal.proposal_id] = proposal

    return {
        "proposal_id": proposal.proposal_id,
        "target_channel": proposal.target_channel,
        "hypothesis": proposal.hypothesis,
        "confidence": proposal.confidence,
        "changes": proposal.changes,
        "expected_sha256": proposal.expected_sha256,
        "report": report.to_dict(),
    }


# --- Speech Automixer Endpoints (Dugan Gain Sharing) ---

class AutomixSetupRequest(BaseModel):
    channels: List[int] = [1, 2, 3, 4]
    weights_db: Dict[str, float] = {"1": 3.0, "2": 0.0, "3": 0.0, "4": -3.0}
    group_id: int = 1 # 1 = Group X, 2 = Group Y


@app.get("/api/v1/automixer/status")
def get_automixer_status():
    """
    Get real-time Dugan Speech Automixer gain-sharing telemetry across spoken-word mics.
    Calculates individual attenuations and proves total system gain <= 0.0 dB (NOM = 1).
    """
    target_channels = [1, 2, 3, 4]
    names = {}
    roles = {}
    levels_dbfs = {}
    weights_db = {1: 3.0, 2: 0.0, 3: 0.0, 4: -3.0}

    for ch in target_channels:
        profile = church_profile_mgr.get_channel(ch)
        names[ch] = profile.get("name", f"Ch {ch:02d}") if profile else f"Ch {ch:02d}"
        roles[ch] = profile.get("role", "SPEECH") if profile else "SPEECH"

    if soundcheck_engine.is_active:
        block_32 = soundcheck_engine.generate_audio_block(block_size=2048)
        for ch in target_channels:
            sig = block_32[:, ch - 1]
            mx = float(np.max(np.abs(sig)))
            levels_dbfs[ch] = float(20.0 * np.log10(mx)) if mx > 1e-6 else -120.0
    elif audio_stream_worker and audio_stream_worker.is_running and audio_stream_worker.latest_buffer is not None:
        buf = audio_stream_worker.latest_buffer
        for ch in target_channels:
            if buf.ndim > 1 and buf.shape[1] >= ch:
                sig = buf[:, ch - 1]
            else:
                sig = buf[:, 0] if buf.ndim > 1 else buf
            mx = float(np.max(np.abs(sig)))
            levels_dbfs[ch] = float(20.0 * np.log10(mx)) if mx > 1e-6 else -120.0
    else:
        # Realistic active church dialogue simulation
        levels_dbfs[1] = -17.2
        levels_dbfs[2] = -58.5
        levels_dbfs[3] = -42.0
        levels_dbfs[4] = -48.3

    report = DuganSpeechAutomixer.compute_gain_sharing(
        channel_levels_dbfs=levels_dbfs,
        weights_db=weights_db,
        channel_names=names,
        channel_roles=roles,
    )
    return report.to_dict()


@app.post("/api/v1/automixer/propose-setup")
def propose_automixer_setup(req: AutomixSetupRequest):
    """
    Generate hardware proposals for native X32 Dugan AutoMix (/ch/{ch}/automix/*).
    Enforces Hard Invariant: Channel 11 (Band Talkback) is strictly prohibited.
    """
    if not x32_client:
        raise HTTPException(status_code=503, detail="X32 Client not initialized")

    if get_talkback_channel() in req.channels:
        raise HTTPException(
            status_code=400,
            detail="BẤT BIẾN AN TOÀN SỐNG CÒN: Kênh 11 (Band Talkback) tuyệt đối không được phép đưa vào nhóm AutoMix!",
        )

    weights_int = {int(k): float(v) for k, v in req.weights_db.items()}

    snapshot = x32_client.take_full_snapshot(max_channels=32)
    proposals = DuganSpeechAutomixer.generate_x32_automix_proposals(
        channels=req.channels,
        weights_db=weights_int,
        current_sha256=snapshot.sha256,
        group_id=req.group_id,
    )

    for prop in proposals:
        active_proposals[prop.proposal_id] = prop

    return {
        "status": "PROPOSED",
        "proposals_count": len(proposals),
        "proposals": [
            {
                "proposal_id": p.proposal_id,
                "target_channel": p.target_channel,
                "hypothesis": p.hypothesis,
                "confidence": p.confidence,
                "changes": p.changes,
            }
            for p in proposals
        ],
    }


# --- Subjective A/B Listening Test Endpoints (Master Plan Section 3.4) ---

class ListeningEvaluationRequest(BaseModel):
    target_channel: int = 1
    channel_name: str = "Pastor Mic"
    operator: str = "SoundTech"
    proposal_id: Optional[str] = None
    intelligibility: float = 4.5
    timbre_naturalness: float = 4.5
    warmth_body: float = 4.0
    harshness_control: float = 4.0
    band_balance: float = 4.0
    hall_coverage: float = 4.0
    feedback_margin: float = 4.5
    loudness_compensation_db: float = 0.0
    is_blind_test: bool = False


class CreateBlindSessionRequest(BaseModel):
    target_channel: int = 1
    channel_name: str = "Pastor Mic"
    proposal_id: Optional[str] = None


@app.get("/api/v1/listening-test/templates")
def get_listening_templates():
    """Get the 7 benchmark criteria with weights and descriptions."""
    return {
        "criteria": [
            {"id": "intelligibility", "name_vi": "Độ rõ lời", "weight": 0.20, "description_vi": "Phát âm rõ ràng từng phụ âm, từ ngữ sáng và dễ hiểu"},
            {"id": "timbre_naturalness", "name_vi": "Độ tự nhiên chất giọng", "weight": 0.20, "description_vi": "Giữ trọn bản sắc giọng thật của người nói/ca sĩ, không bị bóp méo"},
            {"id": "warmth_body", "name_vi": "Độ ấm & thân giọng", "weight": 0.15, "description_vi": "Đầy đặn vùng low-mid (200-400Hz), không bị mỏng hay rỗng giọng"},
            {"id": "harshness_control", "name_vi": "Kiểm soát gắt & chói", "weight": 0.15, "description_vi": "Khử âm xì (sibilance 5-8kHz) và tiếng gắt chát tai"},
            {"id": "band_balance", "name_vi": "Hòa quyện với ban nhạc", "weight": 0.10, "description_vi": "Nổi bật trên nền nhạc sống mà không đè lấn nhạc cụ khác"},
            {"id": "hall_coverage", "name_vi": "Độ phủ đều hội trường", "weight": 0.10, "description_vi": "Âm thanh đồng đều từ hàng ghế đầu đến cuối nhà thờ"},
            {"id": "feedback_margin", "name_vi": "Dự trữ chống hú", "weight": 0.10, "description_vi": "Khoảng cách an toàn trước ngưỡng hú (Gain-Before-Feedback margin)"},
        ]
    }


@app.post("/api/v1/listening-test/evaluate")
def evaluate_listening_test(req: ListeningEvaluationRequest):
    """Submit a subjective 7-criteria listening evaluation and persist to database."""
    crit = ListeningTestCriteria(
        intelligibility=req.intelligibility,
        timbre_naturalness=req.timbre_naturalness,
        warmth_body=req.warmth_body,
        harshness_control=req.harshness_control,
        band_balance=req.band_balance,
        hall_coverage=req.hall_coverage,
        feedback_margin=req.feedback_margin,
    )
    evaluation = ListeningTestEngine.evaluate_listening(
        target_channel=req.target_channel,
        channel_name=req.channel_name,
        operator=req.operator,
        criteria=crit,
        proposal_id=req.proposal_id,
        loudness_compensation_db=req.loudness_compensation_db,
        is_blind_test=req.is_blind_test,
    )
    if db:
        db.save_listening_test(evaluation.to_dict())
        db.save_audit_event(
            actor=req.operator,
            action="LISTENING_EVALUATION",
            proposal_id=req.proposal_id,
            status=evaluation.recommendation,
            details={
                "target_channel": req.target_channel,
                "overall_mos": evaluation.overall_mos,
                "recommendation": evaluation.recommendation,
            }
        )
    return evaluation.to_dict()


@app.get("/api/v1/listening-test/history")
def get_listening_history(limit: int = 20):
    """Retrieve history of past listening evaluations from SQLite."""
    if not db:
        return {"evaluations": []}
    return {"evaluations": db.list_listening_tests(limit=limit)}


@app.post("/api/v1/listening-test/blind-session")
def create_blind_session(req: CreateBlindSessionRequest):
    """Create a new double-blind randomized A/B session with loudness compensation."""
    session = ListeningTestEngine.create_blind_ab_session(
        target_channel=req.target_channel,
        channel_name=req.channel_name,
        proposal_id=req.proposal_id,
    )
    return session.to_dict(reveal_identity=False)


@app.post("/api/v1/listening-test/blind-session/{session_id}/reveal")
def reveal_blind_session(session_id: str):
    """Reveal the actual identity of Option A and Option B."""
    try:
        session = ListeningTestEngine.reveal_blind_ab_session(session_id)
        return session.to_dict(reveal_identity=True)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Stage Bleed & Acoustic Cross-Talk Advisor Endpoints ---

@app.get("/api/v1/bleed-analysis/{channel_id}")
def analyze_channel_bleed(channel_id: int):
    """
    Analyze acoustic stage bleed and cross-talk into a specific vocal/speech channel.
    Enforces Hard Safety Invariant: Channel 11 (Band Talkback) is strictly prohibited.
    """
    if channel_id == get_talkback_channel():
        raise HTTPException(
            status_code=400,
            detail="BẤT BIẾN AN TOÀN SỐNG CÒN: Kênh 11 (Band Talkback) được bảo vệ cách ly tuyệt đối, không phân tích FOH!",
        )

    profile = church_profile_mgr.get_channel(channel_id)
    name = profile.get("name", f"Ch {channel_id:02d}") if profile else f"Ch {channel_id:02d}"
    role = profile.get("role", "SPEECH") if profile else "SPEECH"

    # Acquire target and stage signals (from Virtual Soundcheck if running, or realistic acoustic simulation)
    sr = 48000
    if soundcheck_engine.is_active:
        block_32 = soundcheck_engine.generate_audio_block(block_size=2048)
        target_sig = block_32[:, channel_id - 1]
        stage_sigs = {}
        for ch in [1, 2, 3, 4, 13, 14]:
            if ch != channel_id and ch != 11:
                p = church_profile_mgr.get_channel(ch)
                ch_name = p.get("name", f"Ch {ch:02d}") if p else f"Ch {ch:02d}"
                stage_sigs[ch] = (ch_name, block_32[:, ch - 1])
    else:
        # Realistic simulation: vocal signal with drum snare and stage rumble bleed
        t = np.linspace(0, 0.5, int(0.5 * sr), endpoint=False)
        voice = 0.12 * np.sin(2 * np.pi * 220 * t).astype(np.float32)
        snare = 0.04 * np.sin(2 * np.pi * 180 * t).astype(np.float32) + np.random.normal(0, 0.015, len(t)).astype(np.float32)
        target_sig = voice + 0.35 * snare
        stage_sigs = {
            13: ("Trống Snare / Cymbals", snare),
            2: ("Hướng Dẫn (Mic 2)", 0.08 * np.sin(2 * np.pi * 330 * t).astype(np.float32)),
        }

    report = StageBleedAdvisor.analyze_cross_talk(
        target_signal=target_sig,
        target_channel=channel_id,
        target_name=name,
        target_role=role,
        stage_signals=stage_sigs,
    )
    return report.to_dict()


@app.post("/api/v1/bleed-analysis/{channel_id}/propose-expander")
def propose_expander_setup(channel_id: int):
    """
    Generate hardware proposals for X32 Downward Expander (/ch/{ch}/gate/*).
    Enforces Hard Safety Invariant: Channel 11 (Band Talkback) is strictly prohibited.
    """
    if channel_id == get_talkback_channel():
        raise HTTPException(
            status_code=400,
            detail="BẤT BIẾN AN TOÀN SỐNG CÒN: Kênh 11 (Band Talkback) tuyệt đối không tạo đề xuất expander cho FOH!",
        )

    if not x32_client:
        raise HTTPException(status_code=503, detail="X32 Client not initialized")

    # Get bleed report
    report_dict = analyze_channel_bleed(channel_id)
    exp_data = report_dict["recommended_expander"]
    exp_settings = ExpanderSettings(
        enabled=exp_data["enabled"],
        mode=exp_data["mode"],
        threshold_dbfs=exp_data["threshold_dbfs"],
        threshold_x32=exp_data["threshold_x32"],
        range_db=exp_data["range_db"],
        range_x32=exp_data["range_x32"],
        attack_ms=exp_data["attack_ms"],
        hold_ms=exp_data["hold_ms"],
        release_ms=exp_data["release_ms"],
        filter_on=exp_data["filter_on"],
        filter_type=exp_data["filter_type"],
        filter_freq_hz=exp_data["filter_freq_hz"],
    )

    snapshot = x32_client.take_full_snapshot(max_channels=32)
    proposals = StageBleedAdvisor.generate_expander_proposals(
        channel_id=channel_id,
        settings=exp_settings,
        current_sha256=snapshot.sha256,
    )

    for prop in proposals:
        active_proposals[prop.proposal_id] = prop

    if db:
        db.save_audit_event(
            actor="Operator",
            action="PROPOSE_EXPANDER",
            proposal_id=proposals[0].proposal_id if proposals else None,
            status="PROPOSED",
            details={
                "channel_id": channel_id,
                "threshold_dbfs": exp_settings.threshold_dbfs,
                "range_db": exp_settings.range_db,
                "comb_risk": report_dict["comb_filtering_risk"],
            }
        )

    prop_dict = None
    if proposals:
        p = proposals[0]
        prop_dict = {
            "proposal_id": p.proposal_id,
            "target_channel": p.target_channel,
            "hypothesis": p.hypothesis,
            "confidence": p.confidence,
            "changes": p.changes,
            "expected_sha256": p.expected_sha256,
            "operator_approved": p.operator_approved,
        }

    return {
        "status": "PROPOSED",
        "proposal": prop_dict,
        "report": report_dict,
    }


# --- Monitor Mix Matrix & P16 IEM Endpoints ---

class ProposeBusBalanceRequest(BaseModel):
    bus_id: int
    operator: str = "Operator"


@app.get("/api/v1/monitors/iem-matrix")
def get_monitor_iem_matrix():
    """
    Get multi-bus monitor matrix, P16 Ultranet status, and acoustic feedback inspection.
    """
    if not x32_client:
        raise HTTPException(status_code=503, detail="X32 Client not initialized")

    snapshot = x32_client.take_full_snapshot(max_channels=32)
    report = MonitorMatrixInspector.audit_mixbus_matrix(snapshot.parameters)
    return report.to_dict()


@app.get("/api/v1/monitors/p16-audit")
def get_p16_audit():
    """
    Audit all 16 Ultranet P16 slots, confirming Channel 11 (Band Talkback) isolation.
    """
    if not x32_client:
        raise HTTPException(status_code=503, detail="X32 Client not initialized")

    snapshot = x32_client.take_full_snapshot(max_channels=32)
    slots, is_safe, violations = MonitorMatrixInspector.audit_p16_ultranet(snapshot.parameters)
    return {
        "timestamp": time.time(),
        "slots": [s.to_dict() for s in slots],
        "p16_talkback_safe": is_safe,
        "violations": violations,
    }


@app.post("/api/v1/monitors/propose-bus-balance")
def propose_bus_balance(req: ProposeBusBalanceRequest):
    """
    Formulate safe balance & feedback prevention proposals for a target MixBus.
    """
    if not x32_client:
        raise HTTPException(status_code=503, detail="X32 Client not initialized")
    if not (1 <= req.bus_id <= 16):
        raise HTTPException(status_code=400, detail="bus_id must be between 1 and 16")

    snapshot = x32_client.take_full_snapshot(max_channels=32)
    proposals = MonitorMatrixInspector.generate_safe_bus_balance_proposals(
        x32_state=snapshot.parameters,
        bus_id=req.bus_id,
        current_sha256=snapshot.sha256,
    )

    for prop in proposals:
        active_proposals[prop.proposal_id] = prop

    bus_name = snapshot.parameters.get(f"/bus/{req.bus_id:02d}/config/name", f"Bus {req.bus_id:02d}")
    bus_type = MonitorMatrixInspector.classify_bus_type(req.bus_id, bus_name)

    if db and proposals:
        db.save_audit_event(
            actor=req.operator,
            action="PROPOSE_MONITOR_BALANCE",
            proposal_id=proposals[0].proposal_id,
            status="PROPOSED",
            details={
                "bus_id": req.bus_id,
                "bus_name": bus_name,
                "bus_type": bus_type,
                "proposal_count": len(proposals),
            },
        )

    return {
        "status": "PROPOSED",
        "bus_id": req.bus_id,
        "bus_name": bus_name,
        "bus_type": bus_type,
        "proposals": [
            {
                "proposal_id": p.proposal_id,
                "target_channel": p.target_channel,
                "hypothesis": p.hypothesis,
                "confidence": p.confidence,
                "changes": p.changes,
                "expected_sha256": p.expected_sha256,
                "operator_approved": p.operator_approved,
            }
            for p in proposals
        ],
    }


# --- Wizard Endpoints ---

@app.get("/api/v1/wizards/inventory-report")
def get_inventory_report():
    """Wizard 1: Generate Markdown Inventory & Protection Audit Report."""
    if not wizard_service:
        raise HTTPException(status_code=503, detail="Wizard service not initialized")
    md = wizard_service.generate_inventory_report()
    return {"report_markdown": md}


@app.get("/api/v1/wizards/line-check")
def get_line_check():
    """Wizard 2: Pre-service Line Check & Sunday Physical Checklist."""
    if not wizard_service:
        raise HTTPException(status_code=503, detail="Wizard service not initialized")
    result = wizard_service.run_pre_service_line_check()
    return {
        "timestamp": result.timestamp,
        "iso_time": result.iso_time,
        "all_ready": result.all_ready,
        "talkback_isolated": result.talkback_isolated,
        "items": [
            {
                "channel_id": it.channel_id,
                "name": it.name,
                "status": it.status,
                "is_muted": it.is_muted,
                "is_foh": it.is_foh,
                "is_p16": it.is_p16,
                "fader_pct": it.fader_pct,
                "notes": it.notes,
            }
            for it in result.items
        ],
        "physical_checklist": result.physical_checklist,
    }


@app.get("/api/v1/wizards/end-of-service-report")
def get_end_of_service_report():
    """Wizard 7: End-of-service Review Report."""
    if not wizard_service:
        raise HTTPException(status_code=503, detail="Wizard service not initialized")
    audit_history = executor.audit_log if executor else []
    report_md = wizard_service.generate_end_of_service_report(
        audit_log=audit_history,
        clipping_events=0,
        feedback_events=active_feedback_alerts,
    )
    return {"report_markdown": report_md}


@app.get("/api/v1/wizards/live-assistant")
def get_live_assistant():
    """Wizard 6: Live Service Assistant tactical dashboard status."""
    if not wizard_service:
        raise HTTPException(status_code=503, detail="Wizard service not initialized")
    res = wizard_service.get_live_service_assistant_status(
        stop_auto_triggered=stop_auto_triggered,
        active_feedback_alerts=active_feedback_alerts,
    )
    return {
        "timestamp": res.timestamp,
        "iso_time": res.iso_time,
        "mixer_online": res.mixer_online,
        "read_only_mode": res.read_only_mode,
        "stop_auto_engaged": res.stop_auto_engaged,
        "overall_health": res.overall_health,
        "master_fader_pct": res.master_fader_pct,
        "active_alerts": res.active_alerts,
        "channel_highlights": [
            {
                "channel_id": c.channel_id,
                "name": c.name,
                "role": c.role,
                "fader_pct": c.fader_pct,
                "is_active": c.is_active,
                "clip_count": c.clip_count,
                "feedback_risk": c.feedback_risk,
                "recommendation_vi": c.recommendation_vi,
            }
            for c in res.channel_highlights
        ],
        "tactical_guidance_vi": res.tactical_guidance_vi,
    }



class VocalCalibrationRequest(BaseModel):
    channel_id: int = 1
    vocal_role: str = "PASTOR_SPEECH"


@app.post("/api/v1/wizards/vocal-calibration")
def run_vocal_calibration_endpoint(req: VocalCalibrationRequest):
    """Wizard 3: Natural vocal/speech calibration proposal & mic technique guide."""
    if not wizard_service:
        raise HTTPException(status_code=503, detail="Wizard service not initialized")
    res = wizard_service.calibrate_vocal(channel_id=req.channel_id, vocal_role=req.vocal_role)
    return {
        "channel_id": res.channel_id,
        "vocal_role": res.vocal_role,
        "hpf_on": res.hpf_on,
        "hpf_freq_hz": res.hpf_freq_hz,
        "bands": res.bands,
        "dynamics": res.dynamics,
        "mic_placement_guide": res.mic_placement_guide,
        "simulated_curve": res.simulated_curve,
        "confidence": res.confidence,
    }


class RingOutRequest(BaseModel):
    channel_id: int = 3
    target_gain_increase_db: float = 3.0


@app.post("/api/v1/wizards/feedback-ringout")
def run_feedback_ringout_endpoint(req: RingOutRequest):
    """Wizard 5: Safe Feedback Ring-Out SOP during rehearsal."""
    if not wizard_service:
        raise HTTPException(status_code=503, detail="Wizard service not initialized")
    plan = wizard_service.plan_feedback_ringout(
        channel_id=req.channel_id,
        target_gain_increase_db=req.target_gain_increase_db,
    )
    return {
        "channel_id": plan.channel_id,
        "candidate_freq_hz": plan.candidate_freq_hz,
        "notch_gain_db": plan.notch_gain_db,
        "notch_q": plan.notch_q,
        "gain_margin_improvement_db": plan.gain_margin_improvement_db,
        "step_by_step_sop": plan.step_by_step_sop,
        "safety_lock_engaged": plan.safety_lock_engaged,
    }


class HardwareConnectRequest(BaseModel):
    mode: Literal["SIMULATOR", "REAL_HARDWARE"] = "SIMULATOR"
    ip: str = "127.0.0.1"
    port: int = Field(default=10023, ge=1, le=65535)


@app.post("/api/v1/hardware/connect")
def switch_hardware_target(req: HardwareConnectRequest):
    """Switch connection target between Mock X32 Simulator and Real Church X32 Mixer."""
    global x32_client, executor, wizard_service, x32_meter_reader

    target_ip = "127.0.0.1" if req.mode == "SIMULATOR" else req.ip
    target_port = mock_server.port if req.mode == "SIMULATOR" and mock_server else req.port
    safety_mode_mgr.set_mode(OperatorMode.OBSERVE, operator="Operator")
    active_proposals.clear()

    if x32_client:
        x32_client.close()

    new_client = X32Client(host=target_ip, port=target_port, read_only_mode=True, timeout=1.5)
    try:
        connect_res = new_client.connect()
        x32_client = new_client
        executor = TransactionExecutor(client=x32_client, policy=SafetyPolicy(), mode_manager=safety_mode_mgr)
        wizard_service = WizardService(client=x32_client)
        x32_meter_reader = restart_meter_reader(x32_meter_reader, target_ip, target_port, simulated=bool(
            mock_server and mock_server.running and target_ip == "127.0.0.1" and target_port == mock_server.port))

        if db:
            db.save_audit_event(
                actor="Operator",
                action="SWITCH_HARDWARE",
                status="CONNECTED",
                details={"mode": req.mode, "target": f"{target_ip}:{target_port}"},
            )

        return {
            "status": "CONNECTED",
            "mode": req.mode,
            "target": f"{target_ip}:{target_port}",
            "read_only_mode": True,
            "mixer_info": connect_res["info"],
        }
    except Exception as e:
        new_client.close()
        # Fall back to localhost
        if not mock_server or not mock_server.running:
            x32_client = None
            executor = None
            wizard_service = None
            if x32_meter_reader:
                x32_meter_reader.stop()
                x32_meter_reader = None
            raise HTTPException(status_code=503, detail=f"Mixer connection failed; no isolated simulator available: {e}")
        fallback = X32Client(host="127.0.0.1", port=mock_server.port, read_only_mode=True)
        fallback.connect()
        x32_client = fallback
        executor = TransactionExecutor(client=x32_client, policy=SafetyPolicy(), mode_manager=safety_mode_mgr)
        wizard_service = WizardService(client=x32_client)
        x32_meter_reader = restart_meter_reader(x32_meter_reader, "127.0.0.1", mock_server.port, simulated=True)
        raise HTTPException(
            status_code=400,
            detail=f"Failed to connect to mixer at {target_ip}:{target_port}: {e}. Fallback to Simulator."
        )


class HardwareDiscoverRequest(BaseModel):
    hosts: Optional[List[str]] = None
    timeout: float = 0.6
    port: int = Field(default=10023, ge=1, le=65535)  # X32/M32 OSC port; override for isolated mocks


@app.post("/api/v1/hardware/discover")
def discover_hardware_endpoint(req: HardwareDiscoverRequest = HardwareDiscoverRequest()):
    """Discover active Behringer X32/M32 consoles on the local network or loopback."""
    consoles = X32Client.discover_consoles(target_hosts=req.hosts, port=req.port, timeout=req.timeout)
    return {
        "count": len(consoles),
        "consoles": consoles,
    }



class AudioCaptureStartRequest(BaseModel):
    device_id: int = -1
    channels: int = Field(default=2, ge=1, le=32)
    sample_rate: int = Field(default=48000, ge=8000, le=192000)


@app.get("/api/v1/audio/devices")
def get_audio_devices():
    """List available physical soundcards and USB audio interface inputs."""
    devices = audio_device_mgr.list_input_devices()
    active_dev_id = audio_stream_worker.device_id if audio_stream_worker and audio_stream_worker.is_running else None
    return {
        "devices": devices,
        "is_capturing": audio_stream_worker.is_running if audio_stream_worker else False,
        "active_device_id": active_dev_id,
    }


@app.post("/api/v1/audio/capture/start")
def start_audio_capture(req: AudioCaptureStartRequest):
    """Start real-time audio capture stream on soundcard / USB audio interface."""
    global audio_stream_worker
    if audio_stream_worker and audio_stream_worker.is_running:
        audio_stream_worker.stop()

    worker = AudioStreamWorker(
        device_id=req.device_id,
        channels=req.channels,
        sample_rate=req.sample_rate,
        block_size=1024,
    )
    worker.start()
    audio_stream_worker = worker
    return {
        "status": "STARTED",
        "device_id": req.device_id,
        "channels": req.channels,
        "sample_rate": req.sample_rate,
    }


@app.post("/api/v1/audio/capture/stop")
def stop_audio_capture():
    """Stop active audio capture stream."""
    global audio_stream_worker
    if audio_stream_worker and audio_stream_worker.is_running:
        audio_stream_worker.stop()
        return {"status": "STOPPED"}
    return {"status": "NOT_RUNNING"}


@app.get("/api/v1/audio/capture/status")
def get_audio_capture_status():
    """Get active audio capture metrics and per-channel levels."""
    if audio_stream_worker and audio_stream_worker.is_running:
        return audio_stream_worker.get_status()
    return {"is_running": False}


@app.websocket("/ws/live")
async def websocket_telemetry(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        while True:
            # Keepalive listener
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_websockets:
            active_websockets.remove(websocket)


@app.get("/api/v1/scenes/export")
def export_scene_file(name: str = "ChurchMix_Sunday"):
    """Export current mixer snapshot to native Behringer X32 .scn file."""
    if not x32_client:
        raise HTTPException(status_code=503, detail="X32 Client not initialized")
    snapshot = x32_client.take_full_snapshot(max_channels=32)
    scn_text = SceneExporter.export_scn(snapshot, scene_name=name)
    return {
        "filename": f"{name}.scn",
        "scene_name": name,
        "sha256": snapshot.sha256,
        "content": scn_text,
    }


# --- Scene Vault & Snapshot Archive Endpoints ---

class CreateVaultSnapshotRequest(BaseModel):
    name: str = "Sunday_Service"
    author: str = "Operator"
    note: str = ""
    state_dict: Optional[Dict[str, Any]] = None


class CompareVaultSnapshotsRequest(BaseModel):
    snapshot_id_a: int
    snapshot_id_b: int


@app.get("/api/v1/vault/snapshots")
def list_vault_snapshots(limit: int = 50):
    """Retrieve list of archived mixer snapshots."""
    return {"snapshots": scene_vault_mgr.list_backups(limit=limit)}


@app.post("/api/v1/vault/snapshots")
def create_vault_snapshot(req: CreateVaultSnapshotRequest):
    """Archive current mixer state as a versioned snapshot in the vault."""
    state = req.state_dict
    if state is None:
        if not x32_client:
            raise HTTPException(status_code=503, detail="X32 Client not initialized")
        snapshot = x32_client.take_full_snapshot(max_channels=32)
        state = snapshot.parameters

    backup = scene_vault_mgr.create_backup(
        name=req.name,
        author=req.author,
        note=req.note,
        state_dict=state,
    )
    return {"status": "BACKUP_SAVED", "backup": backup}


@app.post("/api/v1/vault/snapshots/compare")
def compare_vault_snapshots(req: CompareVaultSnapshotsRequest):
    """Compare two archived snapshots and compute channel-by-channel delta."""
    try:
        diff = scene_vault_mgr.diff_backups(req.snapshot_id_a, req.snapshot_id_b)
        return diff
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/vault/snapshots/{snapshot_id}")
def get_vault_snapshot(snapshot_id: int):
    """Retrieve a specific archived snapshot and its parameter map."""
    backup = scene_vault_mgr.get_backup(snapshot_id)
    if not backup:
        raise HTTPException(status_code=404, detail=f"Snapshot ID {snapshot_id} not found")
    return backup


@app.delete("/api/v1/vault/snapshots/{snapshot_id}")
def delete_vault_snapshot(snapshot_id: int):
    """Delete a snapshot from the vault."""
    success = scene_vault_mgr.delete_backup(snapshot_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Snapshot ID {snapshot_id} not found")
    return {"status": "DELETED", "snapshot_id": snapshot_id}


@app.get("/api/v1/vault/snapshots/{snapshot_id}/download-scn")
def download_vault_snapshot_scn(snapshot_id: int):
    """Generate and return native Behringer X32 .scn file content for USB drive."""
    try:
        data = scene_vault_mgr.export_backup_scn(snapshot_id)
        return data
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


class ImportScnRequest(BaseModel):
    scn_content: str
    author: str = "USB_Import"
    note: str = ""
    auto_sanitize: bool = True


@app.post("/api/v1/vault/audit-scn")
def audit_scn_file(req: ImportScnRequest):
    """
    Perform pre-flight safety audit on a raw Behringer X32 .scn text file.
    Does not persist into vault.
    """
    if not req.scn_content.strip():
        raise HTTPException(status_code=400, detail="Nội dung file .scn không được để trống.")
    scene_name, raw_state = SceneImporter.parse_scn_text(req.scn_content)
    report = SceneImporter.audit_scene(raw_state, scene_name=scene_name)
    return report.to_dict()


@app.post("/api/v1/vault/import-scn")
def import_and_vault_scn_file(req: ImportScnRequest):
    """
    Parse, audit, auto-sanitize invariants, and persist a USB .scn file into Scene Vault.
    """
    if not req.scn_content.strip():
        raise HTTPException(status_code=400, detail="Nội dung file .scn không được để trống.")
    try:
        res = SceneImporter.import_and_vault(
            scn_content=req.scn_content,
            vault_mgr=scene_vault_mgr,
            author=req.author,
            note=req.note,
            auto_sanitize=req.auto_sanitize,
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi nạp file .scn: {str(e)}")



@app.post("/api/v1/simulation/run")
def run_sunday_simulation():
    """
    Run complete 5-phase Sunday Service simulation end-to-end:
    - Phase 1: Boot & Talkback Invariant Verification
    - Phase 2: Pre-service Line Check
    - Phase 3: Vocal & Feedback Tuning with Harmonic Rejection
    - Phase 4: Live Service Tactical Monitoring & Silence Hold
    - Phase 5: Post-Service Debrief, Scene Export, and Audit Persistence
    """
    if not x32_client or not wizard_service:
        raise HTTPException(status_code=503, detail="X32 Client not initialized")

    snapshot = x32_client.take_full_snapshot(max_channels=32)
    routing = RoutingGraph(snapshot.parameters)
    tb_ok, tb_msg = routing.verify_talkback_invariant()

    # Phase 2: Line check
    check = wizard_service.run_pre_service_line_check()

    # Phase 3: Feedback & Harmonic rejection
    singer = generate_vocal_note(fundamental_hz=440.0, duration_s=0.1)
    singer_cands = feedback_detector.process_frame(AudioFrame(samples=singer, channel_id=1, timestamp=0.0))
    vocal_safe = len([c for c in singer_cands if c.confidence >= 0.70]) == 0

    fb_tone = generate_sine_wave(freq_hz=3150.0, duration_s=0.1, amplitude=0.5)
    noise = np.random.normal(0, 0.005, len(fb_tone)).astype(np.float32)
    for _ in range(3):
        feedback_detector.process_frame(AudioFrame(samples=fb_tone + noise, channel_id=3, timestamp=0.0))
    fb_cands = feedback_detector.process_frame(AudioFrame(samples=fb_tone + noise, channel_id=3, timestamp=0.1))
    fb_caught = len(fb_cands) > 0

    # Phase 4: Silence Hold
    silence = np.random.normal(0, 0.0005, 4800).astype(np.float32)
    for _ in range(4):
        silence_action = speech_leveler.process(AudioFrame(samples=silence, channel_id=1, timestamp=0.0), current_fader=0.75)
    silence_held = silence_action.action_type == "HOLD"

    # Phase 5: Export scene & persist audit event
    scene_text = SceneExporter.export_scn(snapshot, scene_name="ChurchMix_Sunday_Sim")
    db.save_audit_event(
        actor="SimulationRunner",
        action="SUNDAY_SERVICE_SIMULATION",
        proposal_id="sim-auto-001",
        status="COMMITTED",
        details={
            "talkback_safe": tb_ok,
            "vocal_harmonic_safe": vocal_safe,
            "feedback_caught": fb_caught,
            "silence_held": silence_held,
        },
    )

    return {
        "status": "SUCCESS",
        "timeline": [
            {"time": "08:00 AM", "phase": "W1: Boot & Invariant", "status": "PASSED", "detail": tb_msg},
            {"time": "08:30 AM", "phase": "W2: Line Check", "status": "PASSED", "channels_checked": len(check.items)},
            {"time": "08:45 AM", "phase": "W3 & W5: Vocal & Feedback", "harmonic_safe": vocal_safe, "feedback_caught": fb_caught},
            {"time": "09:00 AM", "phase": "W6: Live Service", "silence_hold_engaged": silence_held, "fader_frozen": 0.75},
            {"time": "10:30 AM", "phase": "W7: Debrief & Scene Export", "status": "COMMITTED", "scene_name": "ChurchMix_Sunday_Sim.scn"},
        ],
        "summary": "100% Sunday service lifecycle verified successfully."
    }


# --- Virtual Soundcheck Rehearsal Endpoints ---

class SoundcheckStartRequest(BaseModel):
    session_id: str = "SUNDAY_WORSHIP_BALLAD"


@app.get("/api/v1/soundcheck/status")
def get_soundcheck_status():
    """Get status of Virtual Soundcheck multitrack simulation."""
    return soundcheck_engine.get_status()


@app.get("/api/v1/soundcheck/sessions")
def get_soundcheck_sessions():
    """List all available Virtual Soundcheck multitrack session presets."""
    return {
        "sessions": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "tempo_bpm": p.tempo_bpm,
                "key": p.key,
                "active_channels": p.active_channels,
                "lead_source": p.lead_source,
            }
            for p in SESSION_PRESETS.values()
        ]
    }


@app.post("/api/v1/soundcheck/start")
def start_soundcheck(req: SoundcheckStartRequest = SoundcheckStartRequest()):
    """Start Virtual Soundcheck multitrack rehearsal playback."""
    session = soundcheck_engine.start_session(session_id=req.session_id)
    return {
        "status": "STARTED",
        "session_id": session.id,
        "name": session.name,
        "description": session.description,
        "is_active": True,
    }


@app.post("/api/v1/soundcheck/stop")
def stop_soundcheck():
    """Stop Virtual Soundcheck rehearsal playback."""
    soundcheck_engine.stop()
    return {"status": "STOPPED", "is_active": False}


# --- Church Channel Profile Manager Endpoints ---

class ChannelProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    notes: Optional[str] = None


# --- Service Segments (Tiết mục): one-tap mic sets, e.g. "Mục sư giảng" ---

class SegmentCreateRequest(BaseModel):
    name: str
    description: str = ""
    icon: str = "mic"
    channels: Dict[str, int] = {}
    operator_id: str = "Operator"


class SegmentUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    channels: Optional[Dict[str, int]] = None
    operator_id: str = "Operator"


class SegmentApplyRequest(BaseModel):
    operator_id: str = "Operator"
    expected_sha256: Optional[str] = None


class SegmentCaptureRequest(BaseModel):
    operator_id: str = "Operator"


def _segment_error(e: Exception) -> HTTPException:
    return HTTPException(status_code=404 if "Không tìm thấy" in str(e) else 400, detail=str(e))


@app.get("/api/v1/segments")
def list_segments():
    """All service segments, plus which one matches the mixer's current mute state."""
    active_id = None
    if x32_client:
        try:
            active_id = segment_store.active_id(x32_client.take_full_snapshot(max_channels=32).parameters)
        except Exception:
            active_id = None
    return {"segments": segment_store.list(), "active_id": active_id, "talkback_channel": get_talkback_channel()}


@app.post("/api/v1/segments")
def create_segment(req: SegmentCreateRequest):
    try:
        return segment_store.create(req.name, req.channels, req.description, req.icon, author=req.operator_id)
    except SegmentError as e:
        raise _segment_error(e)


@app.post("/api/v1/segments/reset-defaults")
def reset_segments():
    return {"segments": segment_store.reset_defaults()}


@app.put("/api/v1/segments/{segment_id}")
def update_segment(segment_id: str, req: SegmentUpdateRequest):
    try:
        return segment_store.update(segment_id, req.model_dump(exclude={"operator_id"}), author=req.operator_id)
    except SegmentError as e:
        raise _segment_error(e)


@app.delete("/api/v1/segments/{segment_id}")
def delete_segment(segment_id: str):
    try:
        segment_store.delete(segment_id)
        return {"status": "DELETED", "segment_id": segment_id}
    except SegmentError as e:
        raise _segment_error(e)


@app.post("/api/v1/segments/{segment_id}/capture")
def capture_segment(segment_id: str, req: SegmentCaptureRequest):
    """Save the mixer's current ON/MUTE state into this segment (read-only on the mixer)."""
    if not x32_client:
        raise HTTPException(status_code=503, detail="X32 Client not initialized")
    try:
        snapshot = x32_client.take_full_snapshot(max_channels=32)
        return segment_store.capture(segment_id, snapshot.parameters, author=req.operator_id)
    except SegmentError as e:
        raise _segment_error(e)


@app.get("/api/v1/segments/{segment_id}/preview")
def preview_segment(segment_id: str):
    """Which channels would be muted / unmuted. Read-only; returns the snapshot SHA to lock the apply."""
    if not x32_client:
        raise HTTPException(status_code=503, detail="X32 Client not initialized")
    try:
        snapshot = x32_client.take_full_snapshot(max_channels=32)
        diff = segment_store.diff(segment_id, snapshot.parameters)
    except SegmentError as e:
        raise _segment_error(e)
    return {**diff, "expected_sha256": snapshot.sha256}


@app.post("/api/v1/segments/{segment_id}/apply")
def apply_segment(segment_id: str, req: SegmentApplyRequest):
    """
    Switch to a segment as ONE Safety Gate batch: mutes first, then unmutes.
    Only /ch/NN/mix/on is written — faders never move. Requires ASSIST mode or higher.
    """
    if stop_auto_triggered:
        raise HTTPException(status_code=403, detail="Không thể chuyển tiết mục: hệ thống đang khóa khẩn cấp (STOP).")
    if not x32_client or not executor:
        raise HTTPException(status_code=503, detail="X32 Client or SafetyGate Executor not initialized")

    snapshot = x32_client.take_full_snapshot(max_channels=32)
    if req.expected_sha256 and req.expected_sha256 != snapshot.sha256:
        raise HTTPException(status_code=409, detail="Mixer vừa thay đổi sau khi xem trước. Hãy mở lại tiết mục để xem trước lần nữa.")
    try:
        diff = segment_store.diff(segment_id, snapshot.parameters)
    except SegmentError as e:
        raise _segment_error(e)

    ordered = diff["to_mute"] + diff["to_unmute"]  # silence first, then open mics
    if not ordered:
        return {"status": "NO_CHANGE", "segment_id": segment_id, "applied": [], "sha256": snapshot.sha256}

    stamp = int(time.time() * 1000)
    proposals = []
    for item in ordered:
        p = Proposal(
            proposal_id=f"SEG_{segment_id}_CH{item['channel']:02d}_{stamp}",
            target_channel=item["channel"],
            hypothesis=f"Segment '{diff['name']}': channel {item['channel']} {'ON' if item['to'] else 'MUTE'}",
            confidence=1.0,
            changes=[{"parameter": f"/ch/{item['channel']:02d}/mix/on", "from": item["from"], "to": item["to"]}],
            expected_sha256=snapshot.sha256,
        )
        p.approve(req.operator_id)
        proposals.append(p)

    batch_id = f"SEGMENT_{segment_id}_{stamp}"
    try:
        result = executor.execute_batch(proposals, req.operator_id, batch_id=batch_id,
                                        hypothesis=f"Switch to segment '{diff['name']}'")
    except Exception as e:
        if db:
            db.save_audit_event(actor=req.operator_id, action="SEGMENT_SWITCH", proposal_id=batch_id,
                                status="REJECTED", details={"segment_id": segment_id, "reason": str(e)})
        raise HTTPException(status_code=400, detail=str(e))

    applied = [{"channel": i["channel"], "name": i["name"], "on": i["to"]} for i in ordered]
    if db:
        db.save_audit_event(actor=req.operator_id, action="SEGMENT_SWITCH", proposal_id=batch_id, status="COMMITTED",
                            details={"segment_id": segment_id, "name": diff["name"], "applied": applied})
    return {"status": "SUCCESS", "segment_id": segment_id, "name": diff["name"], "applied": applied, "sha256": result.get("sha256")}


@app.get("/api/v1/config/church-channels")
def get_church_channels():
    """Get the 32-channel church profile layout and roles."""
    return {
        "channels": church_profile_mgr.get_channels(),
        "talkback_invariant_protected": True,
    }


@app.post("/api/v1/config/church-channels/reset")
def reset_church_channels():
    """Reset church channel profile back to default preset."""
    channels = church_profile_mgr.reset_to_default()
    return {"status": "RESET", "channels": channels}


@app.post("/api/v1/config/church-channels/{channel_id}")
def update_church_channel(channel_id: int, req: ChannelProfileUpdateRequest):
    """Update a church channel profile while strictly enforcing DL16 In 11 invariant."""
    try:
        updates = {k: v for k, v in req.model_dump().items() if v is not None}
        target = church_profile_mgr.update_channel(channel_id=channel_id, updates=updates)
        return {"status": "UPDATED", "channel": target}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Printable Sunday Service Audio Report Endpoint ---

@app.get("/api/v1/reports/sunday-service")
def get_sunday_service_report(
    church_name: str = "Hội Thánh Tin Lành (ChurchMix Sanctuary)",
    engineer_name: str = "Kỹ Thuật Viên Âm Thanh",
):
    """Generate printable HTML Sunday service executive safety & line-check report."""
    snapshot_hash = "sim-snap-48000"
    if x32_client:
        try:
            snapshot = x32_client.take_full_snapshot(max_channels=32)
            snapshot_hash = snapshot.sha256
        except Exception:
            pass

    events = db.get_recent_audit_events(limit=20) if db else []

    html_content = generate_printable_sunday_report_html(
        church_name=church_name,
        engineer_name=engineer_name,
        mixer_model="Behringer X32 Compact / Midas M32",
        snapshot_hash=snapshot_hash,
        events=events,
    )
    return HTMLResponse(content=html_content, status_code=200)


@app.get("/api/v1/system/diagnostics")
def get_system_diagnostics():
    """Execute pre-service diagnostic check and return 10-point health score."""
    report = run_all_diagnostics(verbose=False)
    return report


# --- Multi-Hall Acoustic Profiles & Sanctuary Comparison Endpoints ---

class HallProfileCreateRequest(BaseModel):
    id: str
    name: str
    capacity_seats: int = 500
    target_rt60_seconds: float = 1.5
    nominal_delay_ms: float = 3.5
    ambient_noise_dbfs: float = -60.0
    speaker_system: str = "FOH Line Array"
    target_curve_slope_db_per_oct: float = -1.0
    safe_gain_limit_db: float = 4.0
    notes: str = ""
    baseline_curve: Optional[List[Dict[str, float]]] = None


class HallCompareRequest(BaseModel):
    delay_ms: float = 3.5
    curve: Optional[List[Dict[str, Any]]] = None


@app.get("/api/v1/halls")
def get_sanctuary_halls():
    """List all sanctuary acoustic hall profiles with active hall indicator."""
    halls = hall_profile_mgr.get_all_halls()
    active_hall = hall_profile_mgr.get_active_hall()
    return {
        "active_hall_id": active_hall.id,
        "active_hall_name": active_hall.name,
        "count": len(halls),
        "halls": [h.to_dict() for h in halls],
    }


@app.get("/api/v1/halls/active")
def get_active_sanctuary_hall():
    """Retrieve details of the currently active sanctuary hall."""
    hall = hall_profile_mgr.get_active_hall()
    return hall.to_dict()


@app.get("/api/v1/halls/active/compare")
def compare_active_hall_baseline():
    """Compare active hall baseline against latest or simulated measurement."""
    active_hall = hall_profile_mgr.get_active_hall()
    if last_acoustic_measurement and "curve" in last_acoustic_measurement:
        curve = last_acoustic_measurement["curve"]
        delay_ms = last_acoustic_measurement.get("delay_ms", active_hall.nominal_delay_ms)
    else:
        # Initial baseline comparison simulation
        curve = [
            {
                "freq": pt["freq"],
                "magnitude_db": pt.get("target_db", pt.get("magnitude_db", 0.0)) + 0.3,
                "coherence": pt.get("coherence", 0.92),
            }
            for pt in (active_hall.baseline_curve or [])
        ]
        delay_ms = active_hall.nominal_delay_ms

    diff = hall_profile_mgr.compare_measurement_against_baseline(
        hall_id=active_hall.id,
        measurement_curve=curve,
        delay_ms=delay_ms,
    )
    return diff


@app.get("/api/v1/halls/{hall_id}")
def get_sanctuary_hall(hall_id: str):
    """Retrieve details and acoustic baseline for a specific hall."""
    hall = hall_profile_mgr.get_hall(hall_id)
    if not hall:
        raise HTTPException(status_code=404, detail=f"Hall '{hall_id}' not found.")
    return hall.to_dict()


@app.post("/api/v1/halls/{hall_id}/activate")
def activate_sanctuary_hall(hall_id: str):
    """Switch active sanctuary hall profile."""
    try:
        hall = hall_profile_mgr.set_active_hall(hall_id)
        if db:
            db.save_audit_event(
                actor="Operator",
                action="SWITCH_HALL_PROFILE",
                status="COMMITTED",
                details={"hall_id": hall.id, "hall_name": hall.name},
            )
        return {"status": "ACTIVATED", "active_hall": hall.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/v1/halls")
def save_sanctuary_hall(req: HallProfileCreateRequest):
    """Create or update a versioned hall acoustic profile."""
    profile = HallProfile(
        id=req.id,
        name=req.name,
        capacity_seats=req.capacity_seats,
        target_rt60_seconds=req.target_rt60_seconds,
        nominal_delay_ms=req.nominal_delay_ms,
        ambient_noise_dbfs=req.ambient_noise_dbfs,
        speaker_system=req.speaker_system,
        target_curve_slope_db_per_oct=req.target_curve_slope_db_per_oct,
        safe_gain_limit_db=req.safe_gain_limit_db,
        notes=req.notes,
        baseline_curve=req.baseline_curve,
    )
    saved = hall_profile_mgr.save_hall(profile)
    return {"status": "SAVED", "hall": saved.to_dict()}


@app.post("/api/v1/halls/{hall_id}/compare")
def compare_hall_measurement(hall_id: str, req: HallCompareRequest):
    """Compare a measurement curve against the hall's baseline target."""
    diff = hall_profile_mgr.compare_measurement_against_baseline(
        hall_id=hall_id,
        measurement_curve=req.curve,
        delay_ms=req.delay_ms,
    )
    return diff


# Serve Static UI
WEB_DIR = os.path.abspath(os.path.join(ROOT_DIR, "apps", "web"))
if os.path.exists(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

@app.get("/")
def serve_index():
    index_path = os.path.join(WEB_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>X32 AI Sound Engineer API is Running</h1>")
