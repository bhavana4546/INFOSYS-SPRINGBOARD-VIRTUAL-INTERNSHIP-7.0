# OpenCV & Face Monitoring — Team 2

A beginner-friendly Sprint 1 dashboard that reads a local webcam, detects face-shaped regions using OpenCV's Haar Cascade, and displays the live feed, performance metrics, and recent state-change events. It detects faces only; it does not recognize or identify people.

## Project structure

```text
Team2_FaceMonitoring/
├── app.py                     # Flask app and API routes
├── config.py                  # Camera and detector settings
├── requirements.txt           # Python dependencies
├── services/
│   ├── camera_service.py      # Background webcam and frame processing
│   ├── face_detector.py       # Haar Cascade detection
│   └── event_logger.py        # Thread-safe recent event history
├── templates/index.html       # Dashboard page
├── static/css/style.css       # Responsive dashboard styling
├── static/js/dashboard.js     # Browser controls and status refresh
├── tests/                     # Hardware-free API and image-processing tests
└── docs/                      # Architecture, events, and limitations
```

## Windows setup and run

Open PowerShell in this project folder and verify `python --version` reports Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000** in a browser. The app binds to localhost only. If PowerShell blocks virtual-environment activation, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use `.\.venv\Scripts\python.exe app.py` after installing dependencies into the environment.

Run the hardware-free checks from the project root with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Optional camera/detector overrides can be set before starting:

```powershell
$env:FACE_MONITOR_CAMERA_INDEX = "1"
$env:FACE_MONITOR_FRAME_WIDTH = "640"
$env:FACE_MONITOR_FRAME_HEIGHT = "480"
python app.py
```

## Dashboard features

- Live MJPEG camera preview, face count, approximate FPS, and frame-processing latency.
- Normal, grayscale, Gaussian blur, binary threshold, and Canny-edge display modes. Face detection and metrics continue to use the original captured frame; overlays appear in normal mode.
- Camera restart, test-event control, runtime information, and the latest 100 in-memory events.
- Optional CPU and memory metrics provided by `psutil`.

## API

| Method | Route | Description |
| --- | --- | --- |
| `GET` | `/` | Serves the dashboard. |
| `GET` | `/video_feed` | Streams processed frames as MJPEG. |
| `GET` | `/api/status` | Returns camera status, metrics, runtime details, and recent events. |
| `POST` | `/api/settings` | Sets display processing mode. JSON: `{"mode":"normal"}`; valid modes: `normal`, `grayscale`, `blur`, `threshold`, `canny`. Invalid JSON or mode returns HTTP 400. |
| `POST` | `/api/test-event` | Creates a dashboard test event; returns HTTP 201. |
| `POST` | `/api/camera/restart` | Requests a background camera restart; returns HTTP 202. |

## Troubleshooting

- **Camera unavailable:** Check that the webcam is connected, close other apps using it, grant camera permission to the terminal/browser, and try another camera index with `FACE_MONITOR_CAMERA_INDEX`.
- **Dashboard loads but preview is offline:** This is expected without an accessible webcam. The backend keeps retrying while the dashboard and API remain available.
- **PowerShell cannot activate `.venv`:** Use the execution-policy command above or call the environment's `python.exe` directly.
- **OpenCV import or install issue:** Activate the intended environment and run `python -m pip install -r requirements.txt`. Install only `opencv-python`; this project does not need the conflicting headless or contrib packages.
- **No CPU/memory values:** Install the listed `psutil` dependency; camera and face metrics work without it.
- **No faces found:** Improve lighting, face the camera, move closer, and ensure the face is not occluded.

## Limitations and privacy

Haar Cascade detection is affected by lighting, angle, occlusion, resolution, and processing load and can miss faces or detect false positives. It detects face-like regions only, not identities. The application does not save webcam recordings or send frames to external services; event metadata is held in memory and cleared on restart. Use camera monitoring with permission and appropriate notice. See [docs/limitations.md](docs/limitations.md) for more.
