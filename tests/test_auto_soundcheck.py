"""Automatic per-channel soundcheck: trim math/clamping, HPF by role, refusals, Safety Gate, API + apply on the mock."""

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.autopilot import auto_soundcheck as asc
from packages.autopilot.meter_history import MeterHistory
from packages.mix_assistant.gain_staging import trim_to_x32
from packages.safety_controller.transaction import SafetyPolicy
from packages.storage.church_profile import DEFAULT_CHURCH_CHANNELS

X32 = {"id": "x32-meters", "valid": True, "simulated": False, "mapping_verified": True}


def params(ch=1, trim=0.5, hpon=0, hpf=0.25, on=1):
    p = f"/ch/{ch:02d}"
    return {f"{p}/preamp/trim": trim, f"{p}/preamp/hpon": hpon, f"{p}/preamp/hpf": hpf, f"{p}/mix/on": on}


def history(levels_by_ch, seconds=10.0, step=0.1):
    now = [500.0]
    h = MeterHistory(window_s=30.0, clock=lambda: now[0])
    for i in range(int(seconds / step)):
        h.add([{"channel": ch, "meter_dbfs": (fn(i * step) if callable(fn) else fn)} for ch, fn in levels_by_ch.items()], X32)
        now[0] += step
    return h


def steady(peak):
    """Speech-like: mostly 8 dB below `peak`, regular peaks at `peak`."""
    return lambda t: peak if int(t * 10) % 5 == 0 else peak - 8.0


def run(ch, levels, role="PASTOR_SPEECH", p=None, trusted=True, tb=11, protected=False):
    return asc.analyze(ch, history({ch: levels}), role, p if p is not None else params(ch), 10.0,
                       trusted=trusted, talkback_channel=tb, protected=protected, name="Test")


class TestTrim(unittest.TestCase):
    def test_quiet_speech_gets_boost_toward_minus_12(self):
        r = run(1, steady(-18.0))
        trim = r["plan"]["trim"]
        self.assertTrue(trim["change"])
        self.assertAlmostEqual(trim["delta_db"], 6.0, delta=0.01)
        self.assertEqual(trim["target_peak_dbfs"], -12.0)

    def test_instrument_target_is_minus_15(self):
        r = run(6, steady(-21.0), role="ACOUSTIC_GUITAR", p=params(6))
        self.assertAlmostEqual(r["plan"]["trim"]["delta_db"], 6.0, delta=0.01)
        self.assertEqual(r["measurement"]["target_peak_dbfs"], -15.0)

    def test_boost_clamped_to_safety_limit(self):
        r = run(1, steady(-40.0))
        trim = r["plan"]["trim"]
        self.assertEqual(trim["delta_db"], asc.MAX_TRIM_STEP_DB)
        self.assertTrue(trim["clamped"])
        props = asc.build_proposals(r, params(1), "a" * 64)
        change = props[0][0].changes[0]
        self.assertLessEqual(abs(change["to"] - change["from"]), 0.20)

    def test_trim_cannot_exceed_plus_18(self):
        r = run(1, steady(-30.0), p=params(1, trim=trim_to_x32(16.0)))
        self.assertEqual(r["plan"]["trim"]["target_trim_db"], 18.0)
        self.assertTrue(any("tối đa" in a for a in r["advice_vi"]))

    def test_clipping_channel_never_made_louder(self):
        # clips at -0.5 but the typical peak is low: a naive rule would boost it
        r = run(1, lambda t: -0.5 if int(t * 10) == 3 else -40.0)
        trim = r["plan"]["trim"]
        self.assertTrue(r["measurement"]["clipping"])
        self.assertLess(trim["delta_db"], 0.0)
        props = asc.build_proposals(r, params(1), "a" * 64)
        trim_changes = [c for p, m in props if m["kind"] == "TRIM" for c in p.changes]
        self.assertTrue(trim_changes)
        self.assertLess(trim_changes[0]["to"], trim_changes[0]["from"])

    def test_headroom_cap_keeps_true_peak_below_minus_3(self):
        # typical peak -20 but one transient at -4: boost limited to +1 dB
        r = run(1, lambda t: -4.0 if int(t * 10) == 7 else -20.0)
        self.assertLessEqual(r["measurement"]["peak_dbfs"] + r["plan"]["trim"]["delta_db"], -3.0 + 0.01)

    def test_deadband_no_proposal_when_close(self):
        r = run(1, steady(-12.5), p=params(1, hpon=1, hpf=asc.hpf_hz_to_norm(100)))
        self.assertFalse(r["plan"]["trim"]["change"])
        self.assertEqual(asc.build_proposals(r, params(1, hpon=1, hpf=asc.hpf_hz_to_norm(100)), "a" * 64), [])

    def test_rebuild_after_trim_applied_has_no_trim(self):
        r = run(1, steady(-18.0))
        applied = params(1, trim=trim_to_x32(r["plan"]["trim"]["target_trim_db"]))
        kinds = [m["kind"] for _, m in asc.build_proposals(r, applied, "b" * 64)]
        self.assertNotIn("TRIM", kinds)
        self.assertIn("HPF", kinds)


class TestHpf(unittest.TestCase):
    def kinds(self, role, p):
        r = run(1, steady(-12.0), role=role, p=p)
        return r, {m["kind"]: prop for prop, m in asc.build_proposals(r, p, "a" * 64)}

    def test_hpf_frequency_by_role(self):
        expected = {"PASTOR_SPEECH": 100, "LEAD_VOCAL_FEMALE": 100, "LEAD_VOCAL_MALE": 80, "CHOIR_OVERHEAD": 100,
                    "ACOUSTIC_GUITAR": 80, "PIANO_KEYS": 40}
        for role, hz in expected.items():
            _, props = self.kinds(role, params(1, hpon=0, hpf=0.9))
            changes = {c["parameter"]: c["to"] for c in props["HPF"].changes}
            self.assertEqual(changes["/ch/01/preamp/hpon"], 1, role)
            self.assertAlmostEqual(asc.hpf_norm_to_hz(changes["/ch/01/preamp/hpf"]), hz, delta=1.0, msg=role)

    def test_bass_and_drums_unchanged(self):
        for role in ("BASS_GUITAR", "DRUMS"):
            r, props = self.kinds(role, params(1, hpon=0))
            self.assertNotIn("HPF", props, role)
            self.assertFalse(r["plan"]["hpf"]["change"])

    def test_already_sensible_hpf_is_left_alone(self):
        _, props = self.kinds("PASTOR_SPEECH", params(1, hpon=1, hpf=asc.hpf_hz_to_norm(110)))
        self.assertNotIn("HPF", props)

    def test_hpf_on_but_too_low_changes_frequency_only(self):
        _, props = self.kinds("PASTOR_SPEECH", params(1, hpon=1, hpf=asc.hpf_hz_to_norm(42)))
        self.assertEqual([c["parameter"] for c in props["HPF"].changes], ["/ch/01/preamp/hpf"])


class TestRefusalsAndSafety(unittest.TestCase):
    def test_talkback_refused(self):
        with self.assertRaises(asc.SoundcheckRefused) as cm:
            run(11, steady(-20.0), role="TALKBACK_BAND", p=params(11))
        self.assertEqual(cm.exception.code, "TALKBACK")
        with self.assertRaises(asc.SoundcheckRefused):
            run(7, steady(-20.0), role="PIANO_KEYS", p=params(7), tb=7)  # configured talkback channel

    def test_no_sound_refused(self):
        with self.assertRaises(asc.SoundcheckRefused) as cm:
            run(1, -75.0)
        self.assertEqual(cm.exception.code, "NO_SOUND")

    def test_untrusted_refused(self):
        with self.assertRaises(asc.SoundcheckRefused) as cm:
            run(1, steady(-20.0), trusted=False)
        self.assertEqual(cm.exception.code, "UNTRUSTED")

    def test_insufficient_history_refused(self):
        h = history({1: steady(-20.0)}, seconds=3.0)
        with self.assertRaises(asc.SoundcheckRefused) as cm:
            asc.analyze(1, h, "PASTOR_SPEECH", params(1), 10.0, trusted=True, talkback_channel=11)
        self.assertEqual(cm.exception.code, "INSUFFICIENT")

    def test_proposals_pass_safety_policy_and_only_touch_whitelisted_params(self):
        policy = SafetyPolicy()
        for level in (steady(-40.0), steady(-2.0), lambda t: -0.2):
            r = run(3, level, role="LEAD_VOCAL_FEMALE", p=params(3, hpon=0))
            for prop, _ in asc.build_proposals(r, params(3, hpon=0), "c" * 64):
                policy.validate_proposal(prop)
                self.assertFalse(prop.operator_approved, "a proposal is never pre-approved")
                for c in prop.changes:
                    self.assertIn(c["parameter"], ("/ch/03/preamp/trim", "/ch/03/preamp/hpon", "/ch/03/preamp/hpf"))


# --- API on an isolated app with fakes ---------------------------------------------------
class FakeSnapshot:
    def __init__(self, p):
        self.parameters = p
        self.sha256 = "d" * 64


class FakeClient:
    def __init__(self, p):
        self.p = p

    def take_full_snapshot(self, max_channels=32):
        return FakeSnapshot(dict(self.p))


class TestSoundcheckApiIsolated(unittest.TestCase):
    def setUp(self):
        from apps.api.soundcheck_auto_routes import build_router
        self.h = history({1: steady(-20.0), 2: -80.0, 9: steady(-20.0), 11: steady(-20.0)})
        self.proposals = {}
        p = {**params(1), **params(2), **params(9), **params(11)}
        app = FastAPI()
        app.include_router(build_router(get_client=lambda: FakeClient(p), meter_history=self.h, is_simulator=lambda: False,
                                        get_channels=lambda: [dict(c) for c in DEFAULT_CHURCH_CHANNELS],
                                        proposals=self.proposals))
        self.c = TestClient(app)

    def test_analyze_registers_proposals(self):
        res = self.c.post("/api/v1/auto-soundcheck/1/analyze", json={"seconds": 10})
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        kinds = {p["kind"] for p in data["proposals"]}
        self.assertEqual(kinds, {"TRIM", "HPF"})
        for p in data["proposals"]:
            self.assertIn(p["proposal_id"], self.proposals)
            self.assertTrue(p["explanation_vi"])
        self.assertIn("SAU digital trim", data["assumption_vi"])
        self.assertTrue(data["role_eq"]["available"])
        # analysing again replaces this channel's earlier proposals
        self.c.post("/api/v1/auto-soundcheck/1/analyze", json={"seconds": 10})
        self.assertEqual(len(self.proposals), 2)

    def test_talkback_403_and_no_sound_422(self):
        r = self.c.post("/api/v1/auto-soundcheck/11/analyze", json={"seconds": 10})
        self.assertEqual(r.status_code, 403)
        self.assertIn("Talkback", r.json()["detail"])
        r = self.c.post("/api/v1/auto-soundcheck/2/analyze", json={"seconds": 10})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.proposals, {})

    def test_bass_gets_trim_only(self):
        data = self.c.post("/api/v1/auto-soundcheck/9/analyze", json={"seconds": 10}).json()
        self.assertEqual([p["kind"] for p in data["proposals"]], ["TRIM"])

    def test_rebuild_requires_measurement(self):
        self.assertEqual(self.c.post("/api/v1/auto-soundcheck/3/proposals").status_code, 404)

    def test_channel_list_voice_order_excludes_talkback(self):
        data = self.c.get("/api/v1/auto-soundcheck/channels").json()
        self.assertEqual(data["voice_order"][:5], [1, 2, 3, 4, 5])
        self.assertNotIn(11, [c["channel"] for c in data["channels"]])


# --- Full flow on the main app against the mock X32: analyze -> apply via Safety Gate -----
class TestSoundcheckApplyOnMock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import apps.api.main as main_module
        cls.main = main_module
        cls.tmp = tempfile.TemporaryDirectory()
        cls.orig_profiles = main_module.church_profile_mgr.config_path
        path = os.path.join(cls.tmp.name, "church_channels.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CHURCH_CHANNELS, f, ensure_ascii=False)
        main_module.church_profile_mgr.config_path = path
        cls.orig_segments = main_module.segment_store.path
        main_module.segment_store.path = os.path.join(cls.tmp.name, "segments.json")
        cls._ctx = TestClient(main_module.app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)
        cls.main.church_profile_mgr.config_path = cls.orig_profiles
        cls.main.segment_store.path = cls.orig_segments
        cls.tmp.cleanup()

    def _inject_clipping(self, ch):
        """Wait for the mock meter stream, then add 10 s of loud samples to the shared history."""
        h = self.main.meter_history
        deadline = time.monotonic() + 5.0
        while h.source.get("id") != "x32-meters" and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(h.source.get("id"), "x32-meters")
        with h._lock:
            now = time.monotonic()
            h.source_since = min(h.source_since or now, now - 12.0)
            dq = h._samples[ch]
            for i in range(100):
                dq.append((now - 10.0 + i * 0.1, -0.5))
            h._samples[ch] = type(dq)(sorted(dq))

    def test_analyze_then_apply_trim_on_mock(self):
        from packages.safety_controller.modes import OperatorMode
        self.main.stop_auto_triggered = False
        self.main.safety_mode_mgr.set_mode(OperatorMode.ASSIST, operator="test")
        self.assertTrue(self.main._is_internal_simulator(), "this test must only ever talk to the internal mock")
        self._inject_clipping(3)
        res = self.client.post("/api/v1/auto-soundcheck/3/analyze", json={"seconds": 10})
        self.assertEqual(res.status_code, 200, res.text)
        props = {p["kind"]: p for p in res.json()["proposals"]}
        self.assertIn("TRIM", props)
        trim = props["TRIM"]["changes"][0]
        self.assertLess(trim["to"], trim["from"], "clipping channel: trim goes down")
        self.assertIn(props["TRIM"]["proposal_id"], self.main.active_proposals)

        before = self.main.mock_server.state["/ch/03/preamp/trim"]
        r = self.client.post("/api/v1/proposals/apply", json={"proposal_id": props["TRIM"]["proposal_id"], "operator_id": "test"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self.main.mock_server.state["/ch/03/preamp/trim"], trim["to"], places=3)
        self.assertNotEqual(self.main.mock_server.state["/ch/03/preamp/trim"], before)

        # the HPF proposal is now stale (snapshot changed): rebuild on a fresh snapshot, without trim
        rebuilt = self.client.post("/api/v1/auto-soundcheck/3/proposals")
        self.assertEqual(rebuilt.status_code, 200, rebuilt.text)
        kinds = [p["kind"] for p in rebuilt.json()["proposals"]]
        self.assertNotIn("TRIM", kinds)

        # restore the mock
        self.main.mock_server.state["/ch/03/preamp/trim"] = before

    def test_talkback_refused_on_main_app(self):
        r = self.client.post("/api/v1/auto-soundcheck/11/analyze", json={"seconds": 10})
        self.assertEqual(r.status_code, 403, r.text)


if __name__ == "__main__":
    unittest.main()
