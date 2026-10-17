"""
Autopilot ("Lái tự động") test suite — mock X32 only.

Checks the safety contract of bounded automation:
- speech rider: small steps, hard ±limit, Silence Hold, no raise during feedback,
  follows manual fader moves instead of fighting them
- refuses untrusted measurements (simulated data on real hardware, unmapped USB)
- STOP / disengage stops it immediately
- auto notch: budget per channel, never overwrites an EQ band in use
- livestream: only the configured bus, only with a usable measurement
- clip watch only warns; revert restores the reference
"""

import math
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from packages.autopilot.engine import Autopilot, apply_hard_caps, DEFAULT_CONFIG
from packages.autopilot.x32_scale import db_to_fader, fader_to_db
from packages.eq_optimizer.recommender import PEQRecommender
from packages.mock_x32.server import MockX32Server
from packages.safety_controller.modes import SafetyModeManager, OperatorMode, DisengageReason
from packages.safety_controller.transaction import (
    TransactionExecutor, SafetyPolicy, Proposal, ProposalRejectedError,
)
from packages.storage.church_profile import DEFAULT_CHURCH_CHANNELS
from packages.x32_osc_adapter.client import X32Client

SIM_SOURCE = {"valid": True, "simulated": True, "mapping_verified": True, "label": "test"}


def _config():
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_CONFIG.items()}
    return apply_hard_caps(cfg)


class TestFaderLaw(unittest.TestCase):
    def test_round_trip_and_unity(self):
        self.assertAlmostEqual(fader_to_db(0.75), 0.0)
        self.assertAlmostEqual(db_to_fader(0.0), 0.75)
        for db in (-55.0, -25.0, -12.0, -3.0, 0.0, 5.0):
            self.assertAlmostEqual(fader_to_db(db_to_fader(db)), db, places=1)
        self.assertEqual(fader_to_db(0.0), -math.inf)
        self.assertEqual(db_to_fader(-math.inf), 0.0)

    def test_hard_caps_cannot_be_loosened(self):
        cfg = _config()
        cfg["speech_rider"]["max_offset_db"] = 20
        cfg["speech_rider"]["min_interval_s"] = 0.1
        cfg["auto_notch"]["budget_per_channel"] = 10
        capped = apply_hard_caps(cfg)
        self.assertEqual(capped["speech_rider"]["max_offset_db"], 6.0)
        self.assertEqual(capped["speech_rider"]["min_interval_s"], 1.0)
        self.assertEqual(capped["auto_notch"]["budget_per_channel"], 3)


class TestBusPolicy(unittest.TestCase):
    def _bus(self, bus, frm=0.75, to=0.76):
        return Proposal("B", 0, "t", 1.0, [{"parameter": f"/bus/{bus:02d}/mix/fader", "from": frm, "to": to}], "sha", target_bus=bus)

    def test_only_allowed_bus_small_steps(self):
        policy = SafetyPolicy(allowed_bus_faders={5})
        policy.validate_proposal(self._bus(5))
        with self.assertRaises(ProposalRejectedError):
            policy.validate_proposal(self._bus(6))
        with self.assertRaises(ProposalRejectedError):
            policy.validate_proposal(self._bus(5, 0.75, 0.85))
        with self.assertRaises(ProposalRejectedError):
            SafetyPolicy(allowed_bus_faders=set()).validate_proposal(self._bus(5))

    def test_bus_proposal_cannot_smuggle_other_paths(self):
        p = Proposal("B", 0, "t", 1.0, [{"parameter": "/main/st/mix/fader", "from": 0.75, "to": 0.76}], "sha", target_bus=5)
        with self.assertRaises(ProposalRejectedError):
            SafetyPolicy(allowed_bus_faders={5}).validate_proposal(p)


class TestAutopilotEngine(unittest.TestCase):
    PORT = 10047

    @classmethod
    def setUpClass(cls):
        cls.server = MockX32Server(host="127.0.0.1", port=cls.PORT)
        cls.server.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def setUp(self):
        with self.server.lock:
            self.server.state.clear()
            self.server._init_default_church_state()
        self.client = X32Client(host="127.0.0.1", port=self.PORT, read_only_mode=True, timeout=1.0)
        self.client.connect()
        self.modes = SafetyModeManager()
        self.executor = TransactionExecutor(self.client, SafetyPolicy(allowed_bus_faders={5}), mode_manager=self.modes)
        self.now = [1000.0]
        self.sim = [True]
        self.loudness = [None]
        self.ap = Autopilot(
            get_client=lambda: self.client, get_executor=lambda: self.executor, mode_manager=self.modes,
            channel_provider=lambda: [dict(c) for c in DEFAULT_CHURCH_CHANNELS], recommender=PEQRecommender(),
            is_simulator=lambda: self.sim[0], loudness_provider=lambda: self.loudness[0],
            config=_config(), clock=lambda: self.now[0], run_inline=True,
        )

    def tearDown(self):
        self.client.close()

    def _tick(self, seconds, ch_levels, alerts=None, source=SIM_SOURCE, step=0.1):
        end = self.now[0] + seconds
        while self.now[0] < end:
            meters = [{"channel": c, "name": f"Kênh {c}", "meter_dbfs": lvl, "rms_dbfs": None} for c, lvl in ch_levels.items()]
            self.ap.tick(meters, alerts or [], source)
            self.now[0] += step

    def _fader_db(self, ch):
        return fader_to_db(self.server.state[f"/ch/{ch:02d}/mix/fader"])

    def test_enable_sets_limited_auto(self):
        self.ap.enable("op")
        self.assertEqual(self.modes.get_mode(), OperatorMode.LIMITED_AUTO)
        self.assertIn(1, self.ap.riders)

    def test_rider_raises_quiet_speech_in_small_steps_up_to_limit(self):
        self.ap.enable("op")
        self.ap.features.update(auto_notch=False, livestream=False)
        start = self._fader_db(1)
        self._tick(2.5, {1: -26.0})  # 1.5 s of speech, then one 0.5 dB step (next allowed 2 s later)
        first = self._fader_db(1) - start
        self.assertAlmostEqual(first, 0.5, delta=0.15)
        self._tick(40.0, {1: -26.0})
        self.assertAlmostEqual(self._fader_db(1) - start, 3.0, delta=0.15, msg="never beyond the ±3 dB limit")
        self.assertTrue(any(a["feature"] == "speech_rider" for a in self.ap.status()["alerts"]))

    def test_silence_hold_never_moves(self):
        self.ap.enable("op")
        start = self.server.state["/ch/01/mix/fader"]
        self._tick(20.0, {1: -70.0})
        self.assertEqual(self.server.state["/ch/01/mix/fader"], start)

    def test_no_raise_while_feedback_but_lowering_allowed(self):
        self.ap.enable("op")
        self.ap.features.update(auto_notch=False, livestream=False)
        alert = [{"channel_id": 3, "freq_hz": 3150.0, "confidence": 0.5, "severity": "LOW", "simulated": True}]
        start = self._fader_db(1)
        self._tick(10.0, {1: -30.0}, alerts=alert)
        self.assertAlmostEqual(self._fader_db(1), start, delta=0.01)
        self._tick(6.0, {1: -8.0}, alerts=alert)
        self.assertLess(self._fader_db(1), start)

    def test_follows_manual_fader_move(self):
        self.ap.enable("op")
        self.ap.features.update(auto_notch=False, livestream=False)
        with self.server.lock:
            self.server.state["/ch/01/mix/fader"] = db_to_fader(-6.0)
        self.now[0] += 6.0
        self._tick(0.2, {1: -70.0})  # triggers a mixer refresh
        r = self.ap.riders[1]
        self.assertAlmostEqual(fader_to_db(r["anchor"]), -6.0, delta=0.1)
        self.assertEqual(r["offset_db"], 0.0)

    def test_untrusted_measurements_are_ignored(self):
        self.ap.enable("op")
        self.sim[0] = False  # real console: simulated data must not drive it
        start = self.server.state["/ch/01/mix/fader"]
        self._tick(10.0, {1: -30.0})
        unmapped = {"valid": True, "simulated": False, "mapping_verified": False}
        self._tick(10.0, {1: -30.0}, source=unmapped)
        self.assertEqual(self.server.state["/ch/01/mix/fader"], start)

    def test_stop_disengages_immediately(self):
        self.ap.enable("op")
        self.modes.trigger_auto_disengage(DisengageReason.PANIC_BUTTON, "STOP")
        self.assertFalse(self.ap.enabled)
        start = self.server.state["/ch/01/mix/fader"]
        self._tick(10.0, {1: -30.0})
        self.assertEqual(self.server.state["/ch/01/mix/fader"], start)
        self.assertIn("Tự ngắt", self.ap.status()["inactive_reason"])

    def test_auto_notch_budget_and_free_band_only(self):
        self.ap.enable("op")
        self.ap.features.update(speech_rider=False, livestream=False)
        alert = lambda f: [{"channel_id": 3, "freq_hz": f, "confidence": 0.92, "severity": "HIGH", "simulated": True}]
        self._tick(0.2, {}, alerts=alert(3150.0))
        self.assertLess(self.server.state["/ch/03/eq/3/g"], 0.5)
        self._tick(0.2, {}, alerts=alert(3150.0))  # same frequency: no second cut
        self.assertEqual(len(self.ap.notches), 1)
        self._tick(0.2, {}, alerts=alert(1200.0))  # second distinct frequency: band 2
        self.assertEqual(len(self.ap.notches), 2)
        self.assertLess(self.server.state["/ch/03/eq/2/g"], 0.5)
        self._tick(0.2, {}, alerts=alert(6000.0))  # budget (2) exhausted
        self.assertEqual(len(self.ap.notches), 2)
        self.assertTrue(any("hết" in a["message"] for a in self.ap.status()["alerts"]))

    def test_auto_notch_never_overwrites_bands_in_use(self):
        with self.server.lock:
            self.server.state["/ch/03/eq/2/g"] = 0.6
            self.server.state["/ch/03/eq/3/g"] = 0.4
        self.ap.enable("op")
        self.ap.features.update(speech_rider=False, livestream=False)
        self._tick(0.2, {}, alerts=[{"channel_id": 3, "freq_hz": 3150.0, "confidence": 0.95, "severity": "HIGH", "simulated": True}])
        self.assertEqual(self.ap.notches, [])
        self.assertEqual(self.server.state["/ch/03/eq/3/g"], 0.4)

    def test_low_or_critical_severity_is_left_to_humans(self):
        self.ap.enable("op")
        self.ap.features.update(speech_rider=False, livestream=False)
        self._tick(0.2, {}, alerts=[{"channel_id": 3, "freq_hz": 3150.0, "confidence": 0.95, "severity": "LOW", "simulated": True}])
        self.assertEqual(self.ap.notches, [])

    def test_livestream_only_with_usable_measurement(self):
        self.ap.enable("op")
        self.ap.features.update(speech_rider=False, auto_notch=False)
        start = fader_to_db(self.server.state["/bus/05/mix/fader"])
        self.sim[0] = False
        self.loudness[0] = {"short_term_lufs": -24.0, "valid": True, "simulated": False, "scope": "ANALYSIS_INPUT"}
        real_source = {"valid": True, "simulated": False, "mapping_verified": True}
        self._tick(6.0, {}, source=real_source)
        self.assertAlmostEqual(fader_to_db(self.server.state["/bus/05/mix/fader"]), start, delta=0.01)
        self.loudness[0] = {"short_term_lufs": -24.0, "valid": True, "simulated": False, "scope": "LIVESTREAM_BUS"}
        self._tick(6.0, {}, source=real_source)
        self.assertAlmostEqual(fader_to_db(self.server.state["/bus/05/mix/fader"]) - start, 0.5, delta=0.1)

    def test_revert_restores_livestream_bus(self):
        self.ap.enable("op")
        self.ap.features.update(speech_rider=False, auto_notch=False)
        start = self.server.state["/bus/05/mix/fader"]
        self.loudness[0] = {"short_term_lufs": -26.0, "valid": True, "simulated": True, "scope": "ANALYSIS_INPUT"}
        self._tick(16.0, {})
        self.assertGreater(self.server.state["/bus/05/mix/fader"], start)
        self.ap.revert("op")
        self.assertAlmostEqual(self.server.state["/bus/05/mix/fader"], start, delta=0.003)

    def test_clip_watch_only_warns(self):
        before = dict(self.server.state)
        self._tick(1.0, {4: -0.3})
        self.assertTrue(any(a["feature"] == "clip_watch" for a in self.ap.status()["alerts"]))
        self.assertEqual(self.server.state["/ch/04/preamp/trim"], before["/ch/04/preamp/trim"])

    def test_revert_restores_reference(self):
        self.ap.enable("op")
        self.ap.features.update(livestream=False)
        start_fader = self.server.state["/ch/01/mix/fader"]
        start_eq = self.server.state["/ch/03/eq/3/g"]
        self._tick(12.0, {1: -26.0})
        self._tick(0.2, {}, alerts=[{"channel_id": 3, "freq_hz": 3150.0, "confidence": 0.92, "severity": "HIGH", "simulated": True}])
        self.assertNotEqual(self.server.state["/ch/01/mix/fader"], start_fader)
        self.ap.revert("op")
        self.assertAlmostEqual(self.server.state["/ch/01/mix/fader"], start_fader, delta=0.003)
        self.assertAlmostEqual(self.server.state["/ch/03/eq/3/g"], start_eq, delta=0.003)
        self.assertEqual(self.ap.notches, [])

    def test_talkback_channel_is_never_touched(self):
        self.ap.enable("op")
        before = {k: v for k, v in self.server.state.items() if k.startswith("/ch/11/")}
        self._tick(0.2, {11: -0.2}, alerts=[{"channel_id": 11, "freq_hz": 2000.0, "confidence": 0.99, "severity": "HIGH", "simulated": True}])
        self._tick(10.0, {11: -30.0})
        after = {k: v for k, v in self.server.state.items() if k.startswith("/ch/11/")}
        self.assertEqual(before, after)


class TestAutopilotApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        from fastapi.testclient import TestClient
        import apps.api.main as main_module
        cls.main = main_module
        cls.tmp = tempfile.TemporaryDirectory()
        cls.original_path = main_module.segment_store.path
        main_module.segment_store.path = os.path.join(cls.tmp.name, "segments.json")
        cls._ctx = TestClient(main_module.app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.main.autopilot.disable("test")
        cls._ctx.__exit__(None, None, None)
        cls.main.segment_store.path = cls.original_path
        cls.tmp.cleanup()

    def setUp(self):
        self.main.stop_auto_triggered = False

    def test_enable_disable_cycle(self):
        res = self.client.post("/api/v1/autopilot/enable", json={"operator_id": "test"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["enabled"])
        self.assertEqual(res.json()["mode"], "LIMITED_AUTO")
        res = self.client.put("/api/v1/autopilot/features/auto_notch", json={"enabled": False, "operator_id": "test"})
        self.assertFalse(res.json()["features"]["auto_notch"])
        self.assertEqual(self.client.put("/api/v1/autopilot/features/bogus", json={"enabled": True}).status_code, 400)
        res = self.client.post("/api/v1/autopilot/disable", json={"operator_id": "test"})
        self.assertFalse(res.json()["enabled"])
        self.assertEqual(res.json()["mode"], "OBSERVE")

    def test_enable_refused_while_stopped(self):
        self.main.stop_auto_triggered = True
        res = self.client.post("/api/v1/autopilot/enable", json={"operator_id": "test"})
        self.assertEqual(res.status_code, 403)

    def test_stop_endpoint_pauses_autopilot(self):
        self.client.post("/api/v1/autopilot/enable", json={"operator_id": "test"})
        self.client.post("/api/v1/emergency/stop-auto")
        self.assertFalse(self.client.get("/api/v1/autopilot").json()["enabled"])
        self.client.post("/api/v1/emergency/resume-auto")

    def test_segment_reference_and_drift(self):
        self.main.safety_mode_mgr.set_mode(OperatorMode.ASSIST, operator="test")
        self.client.post("/api/v1/segments/PASTOR_SERMON/capture", json={"operator_id": "test"})
        drift = self.client.get("/api/v1/segments/PASTOR_SERMON/drift").json()
        self.assertTrue(drift["has_reference"])
        self.assertEqual(drift["drift"], [])
        self.main.safety_mode_mgr.set_mode(OperatorMode.OBSERVE, operator="test")


if __name__ == "__main__":
    unittest.main()
