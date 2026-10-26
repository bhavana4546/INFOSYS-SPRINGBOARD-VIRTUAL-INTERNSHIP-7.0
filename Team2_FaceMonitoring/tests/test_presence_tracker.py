import unittest

from services.presence_tracker import FacePresenceState, FacePresenceTracker


class FacePresenceTrackerTests(unittest.TestCase):
    def test_face_present_and_short_absence_do_not_alert(self):
        tracker = FacePresenceTracker(absence_threshold_seconds=10)

        present = tracker.update(True, 100.0)
        absent = tracker.update(False, 101.0)
        still_absent = tracker.update(False, 110.9)

        self.assertEqual(present.state, FacePresenceState.FACE_PRESENT)
        self.assertEqual(absent.state, FacePresenceState.FACE_ABSENT)
        self.assertFalse(absent.prolonged_absence_started)
        self.assertAlmostEqual(still_absent.absence_duration_seconds, 9.9)
        self.assertFalse(still_absent.prolonged_absence_started)

    def test_prolonged_absence_alerts_once_until_face_returns(self):
        tracker = FacePresenceTracker(absence_threshold_seconds=10)

        tracker.update(False, 100.0)
        reached = tracker.update(False, 110.0)
        continued = tracker.update(False, 111.0)
        tracker.update(True, 112.0)
        next_absence = tracker.update(False, 113.0)
        reached_again = tracker.update(False, 123.0)

        self.assertTrue(reached.prolonged_absence_started)
        self.assertFalse(continued.prolonged_absence_started)
        self.assertFalse(next_absence.prolonged_absence_started)
        self.assertTrue(reached_again.prolonged_absence_started)

    def test_unavailable_detection_invalidates_absence_timer(self):
        tracker = FacePresenceTracker(absence_threshold_seconds=10)

        tracker.update(False, 100.0)
        unavailable = tracker.update(None, 109.0)
        resumed_absence = tracker.update(False, 200.0)
        threshold_reached = tracker.update(False, 210.0)

        self.assertEqual(unavailable.state, FacePresenceState.DETECTION_UNAVAILABLE)
        self.assertEqual(unavailable.absence_duration_seconds, 0)
        self.assertFalse(unavailable.prolonged_absence_started)
        self.assertEqual(resumed_absence.absence_duration_seconds, 0)
        self.assertTrue(threshold_reached.prolonged_absence_started)

    def test_zero_threshold_triggers_on_first_absent_sample(self):
        tracker = FacePresenceTracker(absence_threshold_seconds=0)

        first_absence = tracker.update(False, 1.0)

        self.assertTrue(first_absence.prolonged_absence_started)


if __name__ == "__main__":
    unittest.main()
