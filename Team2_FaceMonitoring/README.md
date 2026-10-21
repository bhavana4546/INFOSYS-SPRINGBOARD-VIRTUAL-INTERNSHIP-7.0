# OpenCV & Face Monitoring — Team 2

A Flask dashboard for session-based webcam monitoring. OpenCV captures frames and detects face-shaped regions with its bundled Haar Cascade. It does not recognize or identify people, save recordings, or send camera frames to external services.

## Project structure

```text
Team2_FaceMonitoring/
├── app.py
├── config.py
├── requirements.txt
├── services/
│   ├── camera_service.py
│   ├── event_logger.py
│   ├── face_detector.py
│   └── monitoring_service.py
├── templates/index.html
├── static/css/style.css
├── static/js/dashboard.js
├── tests/
└── docs/
```

## Run in the existing Windows virtual environment

In PowerShell, change to the project folder (the folder containing `app.py`) and use its existing virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

If activation is blocked by PowerShell policy, run directly without changing policy:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open <http://127.0.0.1:5000>. The server binds to localhost. The app opens the Python host's configured webcam only after **Start Monitoring** succeeds.

Run the hardware-free automated tests from the project folder:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Camera and detector configuration can be adjusted before starting:

```powershell
$env:FACE_MONITOR_CAMERA_INDEX = "1"
$env:FACE_MONITOR_FRAME_WIDTH = "640"
$env:FACE_MONITOR_FRAME_HEIGHT = "480"
.\.venv\Scripts\python.exe app.py
```

## Session lifecycle and dashboard

Enter a 1–64 character ID containing letters, numbers, `.`, `_`, or `-` (the first character must be a letter or number). The application keeps each session's status, metrics, and newest 100 event records separate in memory. Session IDs are not exam credentials or access controls.

Statuses: `NOT_STARTED` → `STARTING` → `RUNNING` → `STOPPING` → `STOPPED`. Webcam initialization failures produce `CAMERA_UNAVAILABLE`; a clearly identifiable Python permission exception produces `PERMISSION_DENIED`; unexpected failures produce `ERROR`. A generic OpenCV failure is not labeled a permission denial because OpenCV often cannot distinguish a denied permission from a missing or busy device. Retry a failed session with **Retry Camera**.

Only one physical webcam and one active session are supported by this Flask process. A second session receives HTTP 409 while the camera is owned by another session. Stopping a session other than the current camera owner cannot stop that camera. Camera frames are processed by a background thread; an observed camera read/processing failure is logged for that session and its camera handle is released.

The dashboard retains normal, grayscale, Gaussian blur, threshold, and Canny display modes, and shows the selected session's face count, processing FPS, frame-processing latency, state, error, and events. These are runtime measurements only; no detections or metrics are fabricated.

## API

Requests use JSON. Start:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5000/api/monitoring/start `
  -ContentType "application/json" -Body '{"session_id":"exam-2026-001"}'
```

Check status and stop:

```powershell
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:5000/api/monitoring/status/exam-2026-001
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5000/api/monitoring/stop `
  -ContentType "application/json" -Body '{"session_id":"exam-2026-001"}'
```

| Method | Route | Description |
| --- | --- | --- |
| `POST` | `/api/monitoring/start` | Start a session. JSON: `{"session_id":"exam-2026-001"}`. |
| `POST` | `/api/monitoring/stop` | Stop only the named active session. |
| `GET` | `/api/monitoring/status/<session_id>` | Get that session's status, metrics, and event history. |
| `GET` | `/video_feed/<session_id>` | MJPEG stream for the named active session. |
| `POST` | `/api/settings` | Set display mode for the active session. JSON: `{"session_id":"exam-2026-001","mode":"grayscale"}`. |
| `POST` | `/api/camera/restart` | Release and retry the named session's camera. |
| `POST` | `/api/test-event` | Add a test event to a running session. JSON: `{"session_id":"exam-2026-001"}`. |
| `GET` | `/api/status` | Runtime details and the active session, if any. |

Responses from session start/stop/status contain `session_id`, `status`, and a meaningful `message`; status also provides `error`, metrics, and session-only events. Invalid IDs return 400, camera contention or invalid lifecycle operations return 409, unavailable cameras return 503, identifiable permission exceptions return 403, and unexpected initialization errors return 500.

## Camera permissions and troubleshooting

There are two different camera-access paths:

- **This project's live feed uses Python/OpenCV on the machine running Flask.** The browser displays the server's MJPEG stream and does not request browser webcam access. Grant camera access to desktop apps/the Python process in the operating system's privacy settings. Close other programs that may be holding the camera and verify the configured camera index.
- **Browser camera permission applies only to browser APIs such as `getUserMedia`.** This dashboard does not use that API. Changing browser-site camera permission will not grant OpenCV access to the machine's webcam. If the dashboard is opened from a different machine, OpenCV still uses the Flask host's camera, not the viewer's camera.

For **Camera unavailable**, connect/unlock the webcam, close other webcam applications, verify OS camera privacy settings for desktop applications/terminal/Python, and try another `FACE_MONITOR_CAMERA_INDEX`. Then use **Retry Camera**. OpenCV's generic `isOpened()` failure does not reliably reveal whether the cause is permission, disconnection, or another application, so the dashboard reports it as unavailable rather than falsely claiming permission was denied.

For **Permission denied**, allow desktop-app camera access in OS privacy settings, restart the terminal or VS Code if needed, then retry. Browser camera settings are relevant only to a browser-based camera feature, which this project does not implement.

For **No faces detected**, improve lighting, face the camera, move closer, and reduce occlusion. Haar Cascade may produce false detections or miss faces.

## Privacy and limitations

The application detects face-like regions only and does not identify, track, or verify people. It does not write webcam images/video to disk. Session event metadata and statuses live in process memory and are cleared when the app restarts. The single-webcam ownership lock is process-local; do not run multiple application worker processes against the same camera. See [docs/architecture.md](docs/architecture.md), [docs/event_specification.md](docs/event_specification.md), and [docs/limitations.md](docs/limitations.md).
