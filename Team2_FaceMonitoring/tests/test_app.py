import unittest

from app import create_app
from services.event_logger import EventLogger


class FakeCameraService:
    available_modes = ("normal", "grayscale", "blur", "threshold", "canny")

    def __init__(self):
        self.mode = "normal"
        self.event_logger = EventLogger()
        self.restart_requested = False

    def get_status(self):
        return {
            "camera_status": "offline",
            "camera_error": "Test camera is offline.",
            "face_count": 0,
            "fps": 0,
            "latency_ms": 0,
            "processing_mode": self.mode,
            "available_modes": list(self.available_modes),
            "system_metrics": {"cpu_percent": None, "memory_percent": None},
        }

    def set_processing_mode(self, mode):
        self.mode = mode

    def request_restart(self):
        self.restart_requested = True

    def stream_frames(self):
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\nfake\r\n"

    def stop(self):
        pass


class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.camera = FakeCameraService()
        self.app = create_app(self.camera)
        self.app.testing = True
        self.client = self.app.test_client()

    def test_dashboard_and_status_routes(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"OpenCV &amp; Face Monitoring", page.data)

        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["camera_status"], "offline")
        self.assertIn("opencv_version", payload)
        self.assertIn("platform", payload)
        self.assertEqual(payload["events"], [])

    def test_video_feed_route(self):
        response = self.client.get("/video_feed")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.mimetype.startswith("multipart/x-mixed-replace"))
        self.assertIn(b"Content-Type: image/jpeg", next(response.response))
        response.close()

    def test_settings_validation_and_update(self):
        invalid = self.client.post("/api/settings", json={"mode": "identify"})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.get_json()["error"], "Invalid processing mode.")

        invalid_body = self.client.post(
            "/api/settings",
            data="not-json",
            content_type="application/json",
        )
        self.assertEqual(invalid_body.status_code, 400)

        valid = self.client.post("/api/settings", json={"mode": "canny"})
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.get_json()["mode"], "canny")
        self.assertEqual(self.camera.mode, "canny")

    def test_test_event_and_camera_restart_routes(self):
        event_response = self.client.post("/api/test-event")
        self.assertEqual(event_response.status_code, 201)
        self.assertEqual(
            event_response.get_json()["event"]["type"],
            "test_event_created",
        )
        self.assertEqual(
            self.client.get("/api/status").get_json()["events"][0]["type"],
            "test_event_created",
        )

        restart_response = self.client.post("/api/camera/restart")
        self.assertEqual(restart_response.status_code, 202)
        self.assertTrue(self.camera.restart_requested)


if __name__ == "__main__":
    unittest.main()
