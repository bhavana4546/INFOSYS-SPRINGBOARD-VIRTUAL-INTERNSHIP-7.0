# Event specification

Events are timestamped in UTC and kept in memory; the most recent 100 are returned by `GET /api/status`. The logger is thread-safe. State events are emitted on transitions rather than on every captured frame.

| Event type | Trigger | Dashboard behaviour |
| --- | --- | --- |
| `camera_connected` | Camera successfully opens after startup or a retry/restart. | Adds a connection event; status becomes Online. |
| `camera_unavailable` | Camera open fails or an online camera transitions offline. | Adds one event for the transition and displays the camera error/status. |
| `frame_capture_failure` | An open camera stops returning frames, or OpenCV cannot process a captured frame. | Adds a failure event; capture retries in the background. |
| `face_detected` | Face count changes from zero to one, or multiple faces reduce to one. | Adds a face-appearance event; live face count updates. |
| `face_no_longer_visible` | Face count changes from one or more to zero. | Adds a disappearance event; live face count updates. |
| `multiple_faces_detected` | Face count changes into the multiple-face state. | Adds one event for that state transition, not one per frame. |
| `processing_settings_changed` | A valid processing-mode selection changes the active mode. | Adds a mode-change event; the displayed stream changes mode. |
| `test_event_created` | The dashboard's test-event control is used. | Adds a test event and confirms the action to the user. |

Events are descriptive only. No event identifies a person or stores an image.
