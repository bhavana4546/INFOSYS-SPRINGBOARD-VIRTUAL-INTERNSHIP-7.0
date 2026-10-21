# System architecture

## Frame and metrics pipeline

**Exam session → Webcam ownership → Frame acquisition → Preprocessing → Face detection → Metrics & events → Dashboard**

1. **Session:** `MonitoringService` validates session IDs and stores each session's state, camera metrics, and event history separately.
2. **Webcam:** One `MonitoringService` lock grants the configured camera to at most one session. `CameraService.start()` opens the camera synchronously; the session becomes `RUNNING` only after `isOpened()` succeeds.
3. **Frame acquisition:** `CameraService` captures frames on a dedicated background thread so Flask can continue responding to dashboard and API requests.
4. **Preprocessing:** Frames are converted to grayscale and blurred for the Haar Cascade detector. Display mode can show normal color, grayscale, Gaussian blur, binary thresholding, or Canny edges.
5. **Face detection:** The bundled OpenCV frontal-face Haar Cascade finds face-like regions; it does not identify people.
6. **Metrics:** The service updates face count, smoothed frame rate, frame-processing latency, and camera status. CPU and memory values are reported if `psutil` is available.
7. **Dashboard:** Flask serves a session-specific MJPEG stream, status JSON, and controls. Browser JavaScript polls the selected session and renders event messages with safe DOM text nodes.

## Module responsibilities

- `app.py` creates the Flask app and API routes. Camera access begins only after a valid session start request.
- `config.py` holds camera and detector settings, with camera/detection overrides available through environment variables.
- `services/monitoring_service.py` validates IDs, maintains the session lifecycle, prevents concurrent camera ownership, and scopes events/status/metrics.
- `services/camera_service.py` synchronously initializes one camera, owns its worker thread, processing modes, metrics, safe release, and MJPEG stream.
- `services/face_detector.py` loads OpenCV's bundled Haar Cascade and performs face detection and generic box drawing.
- `services/event_logger.py` stores up to 100 recent, timestamped, session-tagged events in a lock-protected in-memory queue.
- `templates/index.html` defines dashboard structure and educational project information.
- `static/css/style.css` contains the responsive dark dashboard styling without external assets.
- `static/js/dashboard.js` refreshes the selected session's status, safely renders event messages, and calls the session controls and settings APIs.
