import unittest
from unittest.mock import Mock, patch

import numpy as np

from services.camera_service import CameraService
from services.event_logger import EventLogger


class CameraServiceTests(unittest.TestCase):
    def setUp(self):
        self.events = EventLogger()
        self.service = CameraService(
            camera_index=0,
            frame_width=640,
            frame_height=480,
            detector=object(),
            event_logger=self.events,
        )

    def test_processing_modes_transform_the_display_frame(self):
        gradient = np.tile(np.arange(96, dtype=np.uint8), (96, 1))
        frame = np.stack(
            (gradient, np.flipud(gradient), np.full_like(gradient, 120)),
            axis=2,
        )

        for mode in ("grayscale", "blur", "threshold", "canny"):
            with self.subTest(mode=mode):
                processed = self.service._apply_mode(frame, mode)
                self.assertEqual(processed.shape, frame.shape)
                self.assertFalse(np.array_equal(processed, frame))

        grayscale = self.service._apply_mode(frame, "grayscale")
        self.assertTrue(np.array_equal(grayscale[:, :, 0], grayscale[:, :, 1]))
        self.assertTrue(np.array_equal(grayscale[:, :, 1], grayscale[:, :, 2]))

        binary = self.service._apply_mode(frame, "threshold")
        self.assertTrue(set(np.unique(binary)).issubset({0, 255}))

    def test_face_events_are_logged_only_when_state_changes(self):
        for count in (1, 1, 3, 3, 1, 0, 0):
            self.service._log_face_state(count)

        self.assertEqual(
            [event["type"] for event in self.events.get_recent_events()],
            [
                "face_no_longer_visible",
                "face_detected",
                "multiple_faces_detected",
                "face_detected",
            ],
        )

    @patch("services.camera_service.cv2.VideoCapture")
    def test_unavailable_camera_is_not_started_and_handle_is_released(self, video_capture):
        capture = Mock()
        capture.isOpened.return_value = False
        video_capture.return_value = capture

        self.assertFalse(self.service.start())
        capture.release.assert_called_once_with()
        status = self.service.get_status()
        self.assertEqual(status["camera_status"], "offline")
        self.assertIn("Could not open camera", status["camera_error"])

    @patch("services.camera_service.cv2.VideoCapture")
    def test_identifiable_camera_permission_exception(self, video_capture):
        video_capture.side_effect = PermissionError("access denied")

        self.assertFalse(self.service.start())
        status = self.service.get_status()
        self.assertIn("camera access was denied", status["camera_error"].lower())

    @patch("services.camera_service.cv2.VideoCapture")
    def test_disconnected_camera_releases_capture_and_reports_failure(self, video_capture):
        capture = Mock()
        capture.isOpened.return_value = True
        capture.read.return_value = (False, None)
        video_capture.return_value = capture

        self.assertTrue(self.service.start())
        self.service._thread.join(timeout=2)
        self.assertFalse(self.service._thread.is_alive())
        capture.release.assert_called_once_with()
        self.assertEqual(self.service.get_status()["camera_status"], "offline")
        event_types = [event["type"] for event in self.events.get_recent_events()]
        self.assertIn("camera_unavailable", event_types)
        self.assertIn("frame_capture_failure", event_types)


if __name__ == "__main__":
    unittest.main()
