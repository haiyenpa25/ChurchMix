import math
import asyncio
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

from packages.monitoring.analyzer import SignalMonitor, Thresholds
from packages.monitoring.source import collect_signal
from apps.capture_agent.stream_worker import AudioStreamWorker
from packages.virtual_soundcheck.player import VirtualSoundcheckEngine


class TestSignalMonitor(unittest.TestCase):
    def setUp(self):
        self.monitor = SignalMonitor()
        self.source = {"id": "fixture", "valid": True, "simulated": True, "label": "Fixture", "sample_rate": 48000}

    def meter(self, peak, channel=1, rms=-24):
        return {"channel": channel, "meter_dbfs": peak, "rms_dbfs": rms, "name": f"Input {channel}"}

    def test_threshold_boundaries(self):
        for peak, expected in [(-61,"SILENT"),(-60,"NORMAL"),(-12,"WARNING"),(-6,"CRITICAL"),(-0.5,"CLIP_RISK"),(0,"CLIP_RISK")]:
            with self.subTest(peak=peak):
                self.assertEqual(self.monitor.ingest([self.meter(peak)],self.source,now=1)["channels"][0]["status"], expected)

    def test_missing_and_nonfinite_are_unknown_not_silent(self):
        for peak in (None, math.nan, math.inf, -math.inf):
            row = self.monitor.ingest([self.meter(peak)],self.source,now=1)["channels"][0]
            self.assertFalse(row["measured"])
            self.assertEqual(row["status"],"UNKNOWN")
            self.assertIsNone(row["peak_dbfs"])

    def test_durations_count_observed_intervals_and_clip_transitions(self):
        self.monitor.ingest([self.meter(-0.2)],self.source,now=0)
        result = self.monitor.ingest([self.meter(-0.2)],self.source,now=0.5)
        row = result["channels"][0]
        self.assertEqual(row["clip_events"],1)
        self.assertEqual(row["over_seconds"],0.5)
        self.assertEqual(row["critical_seconds"],0.5)
        self.monitor.ingest([self.meter(-20)],self.source,now=0.75)
        result = self.monitor.ingest([self.meter(-0.2)],self.source,now=1)
        self.assertEqual(result["channels"][0]["clip_events"],2)
        self.assertEqual(result["channels"][0]["streak_seconds"],0)

    def test_missing_channels_do_not_gain_duration(self):
        self.monitor.ingest([self.meter(-3)],self.source,now=0)
        result=self.monitor.ingest([self.meter(None)],self.source,now=0.5)
        self.assertEqual(result["channels"][0]["over_seconds"],0)

    def test_source_changes_reset_history_and_statistics(self):
        self.monitor.ingest([self.meter(-0.1)],self.source,now=0)
        self.monitor.ingest([self.meter(-0.1)],self.source,now=0.5)
        result=self.monitor.ingest([self.meter(-20)],{**self.source,"id":"new"},now=0.75)
        self.assertEqual(result["channels"][0]["over_seconds"],0)
        self.assertEqual(result["events"],[])
        self.assertEqual(len(self.monitor.snapshot(now=0.75)["history"]),1)

    def test_stale_read_is_unknown_and_does_not_retain_current_peak(self):
        self.monitor.ingest([self.meter(-20)],self.source,now=1)
        snapshot=self.monitor.snapshot(now=2.1)
        self.assertTrue(snapshot["stale"])
        self.assertFalse(snapshot["source"]["valid"])
        self.assertIsNone(snapshot["channels"][0]["peak_dbfs"])
        self.assertEqual(snapshot["counts"],{"UNKNOWN":1})

    def test_long_gap_not_counted_as_continuous_overload(self):
        self.monitor.ingest([self.meter(-3)],self.source,now=1)
        row=self.monitor.ingest([self.meter(-3)],self.source,now=5)["channels"][0]
        self.assertEqual(row["over_seconds"],0)

    def test_history_bounded_and_selected_channel_filter(self):
        for index in range(1000):
            self.monitor.ingest([self.meter(-10 if index%2 else -20),self.meter(-22,2)],self.source,now=index*0.25)
        snapshot=self.monitor.snapshot(channel=2,now=249.75)
        self.assertLessEqual(len(snapshot["history"]),480)
        self.assertLessEqual(len(snapshot["events"]),200)
        self.assertTrue(all(p["levels"][0]["channel"]==2 for p in snapshot["history"]))
        self.assertEqual(snapshot["events"],[])

    def test_invalid_thresholds_rejected_and_valid_updates_reset(self):
        for values in [(-6,-12,-0.5),(-12,-12,-0.5),(-61,-6,0),(-12,-6,1),(math.nan,-6,0)]:
            with self.assertRaises(ValueError):Thresholds(*values)
        self.monitor.ingest([self.meter(-3)],self.source,now=1)
        self.monitor.set_thresholds(Thresholds(-18,-10,-1))
        self.assertEqual(self.monitor.snapshot()["channels"],[])


class TestSignalSources(unittest.TestCase):
    def setUp(self):
        self.soundcheck=VirtualSoundcheckEngine()

    def test_demo_explicitly_simulated_and_measured_from_samples(self):
        meters,samples,source=collect_signal(self.soundcheck,None,0,{})
        self.assertTrue(source["simulated"])
        self.assertFalse(source["mapping_verified"])
        peak=20*np.log10(max(np.max(np.abs(samples)),1e-7))
        self.assertAlmostEqual(meters[source["spectrum_input"]-1]["meter_dbfs"],float(peak),delta=0.06)

    def test_soundcheck_uses_engine_sample_rate(self):
        self.soundcheck=VirtualSoundcheckEngine(sample_rate=44100)
        self.soundcheck.start_session("SERMON_PREACHING")
        _,_,source=collect_signal(self.soundcheck,None,0,{})
        self.assertEqual(source["sample_rate"],44100)
        self.assertTrue(source["simulated"])

    def test_musical_demo_does_not_create_false_feedback_alerts(self):
        from packages.feedback_detector.detector import FeedbackDetector
        from packages.signal_analysis.dsp import AudioFrame
        detector=FeedbackDetector(min_prominence_db=12,min_persistence_frames=3)
        for i in range(8):
            _,samples,source=collect_signal(self.soundcheck,None,i*0.08,{})
            alerts=detector.process_frame(AudioFrame(samples,channel_id=source["spectrum_input"],timestamp=i*0.08))
            self.assertEqual(alerts,[])

    def worker(self):
        worker=AudioStreamWorker(device_id=-1,channels=2,sample_rate=44100)
        worker._running=True
        worker._process_audio_block(np.ones((1024,2),dtype=np.float32)*0.25)
        return worker

    def test_unmeasured_inputs_are_not_fabricated_as_silence(self):
        meters,_,source=collect_signal(self.soundcheck,self.worker(),0,{})
        self.assertEqual(source["sample_rate"],44100)
        self.assertIsNone(meters[2]["meter_dbfs"])
        self.assertAlmostEqual(meters[0]["meter_dbfs"],-12,delta=0.1)

    def test_physical_unknown_tap_is_labeled_usb_and_dsp_disabled(self):
        worker=self.worker();worker.is_simulated=False;worker.tap_point="UNKNOWN"
        meters,_,source=collect_signal(self.soundcheck,worker,0,{1:{"name":"Pastor"}})
        self.assertIn("USB Input",meters[0]["name"])
        self.assertNotIn("Pastor",meters[0]["name"])
        self.assertTrue(source["valid"])
        self.assertFalse(source["dsp_valid"])

    def test_overflow_clock_fault_and_stale_buffer_invalidate(self):
        for attribute,value in [("overflow_count",1),("clock_verified",False),("clock_fault",True),("last_block_monotonic",0)]:
            worker=self.worker();worker.is_simulated=False;setattr(worker,attribute,value)
            meters,_,source=collect_signal(self.soundcheck,worker,0,{})
            self.assertFalse(source["valid"])
            self.assertFalse(source["dsp_valid"])
            self.assertIsNone(meters[0]["meter_dbfs"])

    def test_failed_physical_capture_keeps_fallback_label(self):
        worker=self.worker();worker.capture_error="fixture failure"
        _,_,source=collect_signal(self.soundcheck,worker,0,{})
        self.assertTrue(source["simulated"])
        self.assertIn("mô phỏng",source["reasons"][0])

    def test_buffer_and_meters_published_together(self):
        worker=self.worker();frame=worker.get_latest_frame()
        self.assertEqual(frame["sequence"],1)
        self.assertEqual(frame["samples"].shape,(1024,2))
        self.assertAlmostEqual(frame["peaks"][0],frame["rms"][0],delta=0.01)

    def test_physical_adc_clock_discontinuity_and_missing_timestamp(self):
        from apps.capture_agent import stream_worker
        from types import SimpleNamespace
        for fault in (0.0,10.0):
            with patch.object(stream_worker,"SOUNDDEVICE_AVAILABLE",True), \
                    patch.object(stream_worker.sd,"InputStream") as stream_factory:
                worker=AudioStreamWorker(device_id=4,channels=2)
                worker._start_physical_stream()
                callback=stream_factory.call_args.kwargs['callback']
                block=np.ones((1024,2),dtype=np.float32)*0.1
                for i in range(7):callback(block,1024,SimpleNamespace(inputBufferAdcTime=1+i*1024/48000),False)
                self.assertTrue(worker.clock_verified)
                callback(block,1024,SimpleNamespace(inputBufferAdcTime=fault),False)
                self.assertFalse(worker.clock_verified)
                self.assertTrue(worker.clock_fault)


class TestMonitoringAPI(unittest.TestCase):
    def test_read_and_threshold_change_do_not_call_mixer(self):
        from apps.api import main
        from fastapi.testclient import TestClient
        with patch.object(main,"signal_monitor",SignalMonitor()),patch.object(main,"x32_client",Mock()) as mixer:
            client=TestClient(main.app)
            self.assertEqual(client.get('/api/v1/monitoring/analysis').status_code,200)
            self.assertEqual(client.get('/api/v1/monitoring/analysis?channel=33').status_code,400)
            updated=client.put('/api/v1/monitoring/thresholds',json={"warning_dbfs":-18,"critical_dbfs":-8,"clip_dbfs":-1})
            self.assertEqual(updated.status_code,200)
            self.assertIn("Đã cập nhật ngưỡng biểu đồ",updated.json()["message"])
            self.assertEqual(client.put('/api/v1/monitoring/thresholds',json={"warning_dbfs":-5,"critical_dbfs":-12,"clip_dbfs":-1}).status_code,400)
            self.assertEqual(mixer.mock_calls,[])

    def test_capture_input_validation(self):
        from apps.api.main import AudioCaptureStartRequest
        from pydantic import ValidationError
        for kwargs in ({"channels":0},{"channels":33},{"sample_rate":0}):
            with self.assertRaises(ValidationError):AudioCaptureStartRequest(**kwargs)

    def test_reconnect_resets_observe_and_keeps_mode_gate(self):
        from apps.api import main
        from packages.safety_controller.modes import SafetyModeManager,OperatorMode
        from packages.x32_osc_adapter.client import X32Client
        manager=SafetyModeManager();manager.set_mode(OperatorMode.ASSIST)
        new_client=X32Client()
        new_client.connect=Mock(return_value={"info":["fixture"]})
        proposals={"old":Mock()}
        with patch.object(main,"x32_client",None),patch.object(main,"executor",None), \
                patch.object(main,"wizard_service",None),patch.object(main,"mock_server",None), \
                patch.object(main,"safety_mode_mgr",manager),patch.object(main,"db",None), \
                patch.object(main,"active_proposals",proposals),patch.object(main,"X32Client",return_value=new_client):
            result=main.switch_hardware_target(main.HardwareConnectRequest(mode="SIMULATOR"))
            self.assertTrue(result["read_only_mode"])
            self.assertEqual(manager.get_mode(),OperatorMode.OBSERVE)
            self.assertIs(main.executor.mode_manager,manager)
            self.assertEqual(proposals,{})


class TestTelemetryProducer(unittest.IsolatedAsyncioTestCase):
    async def test_history_updates_without_any_dashboard_clients(self):
        from apps.api import main
        from packages.feedback_detector.detector import FeedbackDetector
        from packages.safety_controller.modes import SafetyModeManager
        monitor=SignalMonitor();profiles=Mock();profiles.get_channels.return_value=[]
        with patch.object(main,"signal_monitor",monitor),patch.object(main,"active_websockets",[]), \
                patch.object(main,"audio_stream_worker",None),patch.object(main,"x32_client",None), \
                patch.object(main,"soundcheck_engine",VirtualSoundcheckEngine()), \
                patch.object(main,"feedback_detector",FeedbackDetector()), \
                patch.object(main,"church_profile_mgr",profiles),patch.object(main,"safety_mode_mgr",SafetyModeManager()):
            task=asyncio.create_task(main.audio_telemetry_loop())
            try:
                await asyncio.sleep(0.2)
                result=monitor.snapshot()
                self.assertEqual(len(result["channels"]),32)
                self.assertTrue(result["source"]["simulated"])
                self.assertFalse(result["stale"])
                self.assertGreaterEqual(len(result["history"]),1)
            finally:
                task.cancel();await task

    async def test_stalled_websocket_does_not_delay_other_client_send(self):
        from apps.api import main
        from packages.feedback_detector.detector import FeedbackDetector
        from packages.safety_controller.modes import SafetyModeManager
        received=asyncio.Event()
        class Slow:
            async def send_text(self,message):await asyncio.Event().wait()
            async def close(self,code):pass
        class Fast:
            async def send_text(self,message):received.set()
        slow=Slow();clients=[slow,Fast()];profiles=Mock();profiles.get_channels.return_value=[]
        with patch.object(main,"signal_monitor",SignalMonitor()),patch.object(main,"active_websockets",clients), \
                patch.object(main,"audio_stream_worker",None),patch.object(main,"x32_client",None), \
                patch.object(main,"soundcheck_engine",VirtualSoundcheckEngine()),patch.object(main,"feedback_detector",FeedbackDetector()), \
                patch.object(main,"church_profile_mgr",profiles),patch.object(main,"safety_mode_mgr",SafetyModeManager()):
            task=asyncio.create_task(main.audio_telemetry_loop())
            try:
                await asyncio.wait_for(received.wait(),timeout=0.15)
                await asyncio.sleep(0.3)
                self.assertNotIn(slow,clients)
            finally:
                task.cancel();await task


if __name__=='__main__':unittest.main()
