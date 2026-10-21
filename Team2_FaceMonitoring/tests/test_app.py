import unittest

from app import create_app
from services.monitoring_service import MonitoringService


class FakeCameraService:
    available_modes = ("normal", "grayscale", "blur", "threshold", "canny")

    def __init__(
        self,
        event_logger,
        start_result=True,
        startup_error=None,
        startup_exception=None,
    ):
        self.event_logger = event_logger
        self.mode = "normal"
        self.released = False
        self.start_result = start_result
        self.startup_error = startup_error
        self.startup_exception = startup_exception

    def start(self):
        if self.startup_exception:
            raise self.startup_exception
        return self.start_result

    def get_status(self):
        return {
            "camera_status": "online" if self.start_result else "offline",
            "camera_error": self.startup_error,
            "face_count": 2,
            "fps": 12.5,
            "latency_ms": 18.2,
            "processing_mode": self.mode,
            "available_modes": list(self.available_modes),
            "system_metrics": {"cpu_percent": None, "memory_percent": None},
        }

    def set_processing_mode(self, mode):
        self.mode = mode
        self.event_logger.add_event(
            "processing_settings_changed",
            f"Processing mode changed to {mode}.",
        )

    def stream_frames(self):
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\nfake\r\n"

    def stop(self):
        self.released = True


class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.cameras = []

        def camera_factory(event_logger):
            camera = FakeCameraService(event_logger)
            self.cameras.append(camera)
            return camera

        self.monitoring = MonitoringService(camera_factory=camera_factory)
        self.app = create_app(monitoring_service=self.monitoring)
        self.app.testing = True
        self.client = self.app.test_client()

    def test_dashboard_and_session_status_routes(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"OpenCV &amp; Face Monitoring", page.data)
        self.assertIn(b"Start Monitoring", page.data)

        response = self.client.get("/api/monitoring/status/exam-1")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["session_id"], "exam-1")
        self.assertEqual(payload["status"], "NOT_STARTED")
        self.assertEqual(payload["events"], [])
        self.assertIn("opencv_version", payload)

    def test_start_stop_duplicate_start_and_wrong_session_stop(self):
        started = self.client.post("/api/monitoring/start", json={"session_id": "exam-1"})
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.get_json()["status"], "RUNNING")
        self.assertEqual(started.get_json()["face_count"], 2)

        duplicate = self.client.post("/api/monitoring/start", json={"session_id": "exam-1"})
        self.assertEqual(duplicate.status_code, 409)

        wrong_stop = self.client.post("/api/monitoring/stop", json={"session_id": "exam-2"})
        self.assertEqual(wrong_stop.status_code, 409)
        self.assertEqual(self.monitoring.get_status("exam-1")["status"], "RUNNING")
        self.assertFalse(self.cameras[0].released)

        stopped = self.client.post("/api/monitoring/stop", json={"session_id": "exam-1"})
        self.assertEqual(stopped.status_code, 200)
        self.assertEqual(stopped.get_json()["status"], "STOPPED")
        self.assertTrue(self.cameras[0].released)

        repeated_stop = self.client.post("/api/monitoring/stop", json={"session_id": "exam-1"})
        self.assertEqual(repeated_stop.status_code, 200)
        repeated_start = self.client.post("/api/monitoring/start", json={"session_id": "exam-1"})
        self.assertEqual(repeated_start.status_code, 200)
        self.assertEqual(repeated_start.get_json()["status"], "RUNNING")

    def test_missing_invalid_and_conflicting_session_ids(self):
        missing = self.client.post("/api/monitoring/start", json={})
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.get_json()["status"], "ERROR")

        invalid = self.client.post(
            "/api/monitoring/start",
            json={"session_id": "../not-valid"},
        )
        self.assertEqual(invalid.status_code, 400)

        non_object = self.client.post(
            "/api/monitoring/start",
            data="not-json",
            content_type="application/json",
        )
        self.assertEqual(non_object.status_code, 400)

        self.client.post("/api/monitoring/start", json={"session_id": "exam-1"})
        conflict = self.client.post("/api/monitoring/start", json={"session_id": "exam-2"})
        self.assertEqual(conflict.status_code, 409)

    def test_camera_unavailable_and_permission_http_responses(self):
        unavailable_monitoring = MonitoringService(
            camera_factory=lambda logger: FakeCameraService(
                logger,
                start_result=False,
                startup_error="No webcam is available.",
            )
        )
        unavailable_client = create_app(
            monitoring_service=unavailable_monitoring,
        ).test_client()
        unavailable = unavailable_client.post(
            "/api/monitoring/start",
            json={"session_id": "exam-offline"},
        )
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable.get_json()["status"], "CAMERA_UNAVAILABLE")

        denied_monitoring = MonitoringService(
            camera_factory=lambda logger: FakeCameraService(
                logger,
                startup_exception=PermissionError("access denied"),
            )
        )
        denied_client = create_app(
            monitoring_service=denied_monitoring,
        ).test_client()
        denied = denied_client.post(
            "/api/monitoring/start",
            json={"session_id": "exam-denied"},
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.get_json()["status"], "PERMISSION_DENIED")

    def test_events_and_metrics_are_associated_with_their_session(self):
        self.client.post("/api/monitoring/start", json={"session_id": "exam-a"})
        first_event = self.client.post(
            "/api/test-event",
            json={"session_id": "exam-a"},
        )
        self.assertEqual(first_event.status_code, 201)
        self.assertEqual(first_event.get_json()["event"]["session_id"], "exam-a")
        self.client.post("/api/monitoring/stop", json={"session_id": "exam-a"})

        self.client.post("/api/monitoring/start", json={"session_id": "exam-b"})
        second = self.client.get("/api/monitoring/status/exam-b").get_json()
        first = self.client.get("/api/monitoring/status/exam-a").get_json()
        self.assertTrue(
            all(event["session_id"] == "exam-b" for event in second["events"])
        )
        self.assertTrue(all(event["session_id"] == "exam-a" for event in first["events"]))

    def test_session_scoped_video_and_settings(self):
        inactive_feed = self.client.get("/video_feed/exam-1")
        self.assertEqual(inactive_feed.status_code, 409)
        self.client.post("/api/monitoring/start", json={"session_id": "exam-1"})
        feed = self.client.get("/video_feed/exam-1")
        self.assertEqual(feed.status_code, 200)
        self.assertTrue(feed.mimetype.startswith("multipart/x-mixed-replace"))
        self.assertIn(b"Content-Type: image/jpeg", next(feed.response))
        feed.close()

        invalid = self.client.post(
            "/api/settings",
            json={"mode": "identify", "session_id": "exam-1"},
        )
        self.assertEqual(invalid.status_code, 400)
        valid = self.client.post(
            "/api/settings",
            json={"mode": "canny", "session_id": "exam-1"},
        )
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.get_json()["mode"], "canny")
        self.assertEqual(
            self.client.get("/api/monitoring/status/exam-1").get_json()["events"][0]["type"],
            "processing_settings_changed",
        )


if __name__ == "__main__":
    unittest.main()
