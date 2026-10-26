# Event specification

Events are timestamped in UTC and kept in a separate in-memory event logger for each session; the most recent 100 are returned by `GET /api/monitoring/status/<session_id>`. Each event includes its `session_id`. The logger is thread-safe. State events are emitted on transitions rather than on every captured frame. Event history is cleared when the application restarts.

| Event type | Trigger | Dashboard behaviour |
| --- | --- | --- |
| `camera_connected` | Camera successfully opens after startup or a retry/restart. | Adds a connection event; status becomes Online. |
| `camera_unavailable` | Camera open fails or an online camera transitions offline. | Adds one event for the transition and displays the camera error/status. |
| `monitoring_started` | Webcam initialization succeeds and the session enters `RUNNING`. | Records the successful start for that session. |
| `monitoring_start_failed` | The webcam cannot be opened or initialization raises an error. | Records the session-specific failure; no running state is reported. |
| `monitoring_stopped` | The active session stops and its camera worker releases the camera. | Records a successful stop for that session. |
| `camera_release_failure` | OpenCV raises an error while releasing the camera handle. | Records cleanup failure for the owning session. |
| `frame_capture_failure` | An open camera stops returning frames, or OpenCV cannot process a captured frame. | Adds a failure event; capture retries in the background. |
| `face_detected` | Face count changes from zero to one, or multiple faces reduce to one. | Adds a face-appearance event; live face count updates. |
| `face_no_longer_visible` | Face count changes from one or more to zero. | Adds a disappearance event; live face count updates. |
| `multiple_faces_detected` | Face count changes into the multiple-face state. | Adds one event for that state transition, not one per frame. |
| `face_presence_state_changed` | Detection changes between present, absent, or unavailable. | Reports the explicit `FACE_PRESENT`, `FACE_ABSENT`, or `DETECTION_UNAVAILABLE` state. |
| `prolonged_absence` | A continuous `FACE_ABSENT` interval reaches `FACE_MONITOR_ABSENCE_THRESHOLD_SECONDS` (default 10). | Adds exactly one event for that absence interval; face return or unavailable detection resets the timer. |
| `processing_settings_changed` | A valid processing-mode selection changes the active mode. | Adds a mode-change event; the displayed stream changes mode. |
| `test_event_created` | The dashboard's test-event control is used. | Adds a test event and confirms the action to the user. |

Events are descriptive only. No event identifies a person or stores an image. A test event is accepted only for a running session. An unavailable camera/frame/detection is never treated as face absence.
