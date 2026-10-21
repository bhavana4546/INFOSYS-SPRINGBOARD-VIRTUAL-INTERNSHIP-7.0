import unittest

from services.monitoring_service import MonitoringError, MonitoringService


class MockCamera:
    def __init__(self, event_logger, result=True, error=None, exception=None):
        self.event_logger = event_logger
        self.result = result
        self.error = error
        self.exception = exception
        self.released = False

    def start(self):
        if self.exception:
            raise self.exception
        return self.result

    def stop(self):
        self.released = True

    def get_status(self):
        return {
            "camera_status": "online" if self.result else "offline",
            "camera_error": self.error,
            "face_count": 0,
            "fps": 0,
            "latency_ms": 0,
            "processing_mode": "normal",
            "system_metrics": {"cpu_percent": None, "memory_percent": None},
        }


class MonitoringServiceTests(unittest.TestCase):
    def test_camera_failure_does_not_mark_session_running(self):
        camera = MockCamera(
            event_logger=None,
            result=False,
            error="Could not open webcam.",
        )
        service = MonitoringService(camera_factory=lambda _logger: camera)

        with self.assertRaises(MonitoringError) as context:
            service.start_monitoring("exam-unavailable")

        self.assertEqual(context.exception.status, "CAMERA_UNAVAILABLE")
        self.assertEqual(context.exception.status_code, 503)
        self.assertEqual(service.get_status("exam-unavailable")["status"], "CAMERA_UNAVAILABLE")
        self.assertTrue(camera.released)

    def test_identifiable_permission_error_has_specific_status(self):
        camera = MockCamera(
            event_logger=None,
            exception=PermissionError("access denied"),
        )
        service = MonitoringService(camera_factory=lambda _logger: camera)

        with self.assertRaises(MonitoringError) as context:
            service.start_monitoring("exam-permission")

        self.assertEqual(context.exception.status, "PERMISSION_DENIED")
        self.assertEqual(context.exception.status_code, 403)

    def test_invalid_id_and_start_conflict(self):
        service = MonitoringService(
            camera_factory=lambda logger: MockCamera(logger),
        )
        with self.assertRaises(MonitoringError) as invalid:
            service.start_monitoring("")
        self.assertEqual(invalid.exception.status_code, 400)

        service.start_monitoring("exam-one")
        with self.assertRaises(MonitoringError) as conflict:
            service.start_monitoring("exam-two")
        self.assertEqual(conflict.exception.status_code, 409)
        self.assertEqual(service.get_status("exam-one")["status"], "RUNNING")

    def test_stop_cannot_stop_another_session_and_events_are_isolated(self):
        cameras = []

        def factory(logger):
            camera = MockCamera(logger)
            cameras.append(camera)
            return camera

        service = MonitoringService(camera_factory=factory)
        service.start_monitoring("exam-one")
        with self.assertRaises(MonitoringError):
            service.stop_monitoring("exam-two")
        self.assertFalse(cameras[0].released)

        service.stop_monitoring("exam-one")
        service.start_monitoring("exam-two")
        self.assertTrue(
            all(event["session_id"] == "exam-two" for event in service.get_status("exam-two")["events"])
        )
        self.assertEqual(service.get_status("exam-one")["status"], "STOPPED")


if __name__ == "__main__":
    unittest.main()
