(() => {
  "use strict";

  const statusDot = document.getElementById("status-dot");
  const cameraStatus = document.getElementById("camera-status");
  const cameraError = document.getElementById("camera-error");
  const eventList = document.getElementById("event-list");
  const modeSelect = document.getElementById("processing-mode");
  const sessionInput = document.getElementById("session-id");
  const startButton = document.getElementById("start-monitoring");
  const stopButton = document.getElementById("stop-monitoring");
  const retryButton = document.getElementById("retry-camera");
  const sessionFeedback = document.getElementById("session-feedback");
  const modeLabels = {
    normal: "Normal video",
    grayscale: "Grayscale",
    blur: "Gaussian blur",
    threshold: "Binary threshold",
    canny: "Canny edges",
  };
  const failedStates = new Set(["CAMERA_UNAVAILABLE", "PERMISSION_DENIED", "ERROR"]);
  let displayedFeedSession = null;
  let requestInProgress = false;

  function showMessage(element, message, isError = false) {
    element.textContent = message;
    element.style.color = isError ? "#ff9ba4" : "#42d392";
  }

  function renderEvents(events) {
    eventList.replaceChildren();
    document.getElementById("event-total").textContent = String(events.length);
    if (!events.length) {
      const empty = document.createElement("li");
      empty.className = "empty-state";
      empty.textContent = "No events for this session yet.";
      eventList.append(empty);
      return;
    }
    for (const item of events) {
      const event = document.createElement("li");
      event.className = "event-item";
      const message = document.createElement("strong");
      message.textContent = item.message;
      const time = document.createElement("time");
      const date = new Date(item.timestamp);
      time.dateTime = item.timestamp;
      time.textContent = Number.isNaN(date.getTime()) ? item.timestamp : date.toLocaleString();
      event.append(message, time);
      eventList.append(event);
    }
  }

  function updateSessionControls(status, sessionId, activeSessionId = null) {
    const isRunning = status === "RUNNING";
    const isTransitioning = status === "STARTING" || status === "STOPPING";
    const cameraOwnedByAnotherSession = activeSessionId && activeSessionId !== sessionId;
    document.getElementById("monitoring-status").textContent = status;
    document.getElementById("monitoring-status").classList.toggle("running", isRunning);
    document.getElementById("monitoring-status").classList.toggle(
      "failed",
      failedStates.has(status),
    );
    document.getElementById("current-session").textContent = sessionId || "None";
    startButton.disabled =
      requestInProgress || !sessionId || isRunning || isTransitioning || cameraOwnedByAnotherSession;
    stopButton.disabled = requestInProgress || !isRunning;
    retryButton.disabled =
      requestInProgress ||
      !sessionId ||
      cameraOwnedByAnotherSession ||
      (!isRunning && !failedStates.has(status));
    modeSelect.disabled = !isRunning || requestInProgress;
  }

  async function refreshStatus() {
    const sessionId = sessionInput.value.trim();
    if (!sessionId) {
      updateSessionControls("NOT_STARTED", "");
      cameraStatus.textContent = "No session selected";
      statusDot.classList.remove("online");
      statusDot.classList.add("offline");
      cameraError.textContent = "";
      document.getElementById("face-count").textContent = "—";
      document.getElementById("fps").textContent = "—";
      document.getElementById("latency").textContent = "—";
      renderEvents([]);
      if (displayedFeedSession !== null) {
        document.getElementById("video-feed").removeAttribute("src");
        displayedFeedSession = null;
      }
      try {
        const response = await fetch("/api/status", { cache: "no-store" });
        if (response.ok) {
          const runtime = await response.json();
          document.getElementById("opencv-version").textContent = runtime.opencv_version || "Unavailable";
          document.getElementById("platform").textContent = runtime.platform || "Unavailable";
          if (runtime.active_session_id) {
            sessionInput.value = runtime.active_session_id;
            await refreshStatus();
          }
        }
      } catch (error) {
        showMessage(sessionFeedback, error.message || "Could not connect to the monitoring server.", true);
      }
      return;
    }

    try {
      const response = await fetch(
        `/api/monitoring/status/${encodeURIComponent(sessionId)}`,
        { cache: "no-store" },
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "Could not load session status.");
      updateSessionControls(data.status, sessionId, data.active_session_id);
      document.getElementById("current-session").textContent =
        data.active_session_id || (data.status === "RUNNING" ? sessionId : "None");
      cameraStatus.textContent = data.status.replaceAll("_", " ");
      statusDot.classList.toggle("online", data.status === "RUNNING");
      statusDot.classList.toggle("offline", data.status !== "RUNNING");
      cameraError.textContent = data.error || "";
      document.getElementById("face-count").textContent = String(data.face_count ?? 0);
      document.getElementById("fps").textContent = Number(data.fps || 0).toFixed(1);
      document.getElementById("latency").textContent = `${Number(data.latency_ms || 0).toFixed(1)} ms`;
      document.getElementById("opencv-version").textContent = data.opencv_version || "—";
      document.getElementById("platform").textContent = data.platform || "—";
      document.getElementById("cpu-usage").textContent =
        data.system_metrics?.cpu_percent == null ? "Not available" : `${data.system_metrics.cpu_percent}%`;
      document.getElementById("memory-usage").textContent =
        data.system_metrics?.memory_percent == null ? "Not available" : `${data.system_metrics.memory_percent}%`;
      if (modeLabels[data.processing_mode]) {
        modeSelect.value = data.processing_mode;
        document.getElementById("active-mode").textContent = modeLabels[data.processing_mode];
      }
      renderEvents(Array.isArray(data.events) ? data.events : []);
      if (data.status === "RUNNING" && displayedFeedSession !== sessionId) {
        document.getElementById("video-feed").src = `/video_feed/${encodeURIComponent(sessionId)}`;
        displayedFeedSession = sessionId;
      } else if (data.status !== "RUNNING" && displayedFeedSession === sessionId) {
        document.getElementById("video-feed").removeAttribute("src");
        displayedFeedSession = null;
      }
    } catch (error) {
      cameraStatus.textContent = "Session unavailable";
      statusDot.classList.remove("online");
      statusDot.classList.add("offline");
      cameraError.textContent = error.message || "Could not load this session.";
    }
  }

  async function postSessionAction(url, button, successMessage) {
    const sessionId = sessionInput.value.trim();
    if (!sessionId) {
      showMessage(sessionFeedback, "Enter a valid exam session ID first.", true);
      return;
    }
    requestInProgress = true;
    button.disabled = true;
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      const result = await response.json();
      if (!response.ok) {
        const error = new Error(result.message || result.error || "Monitoring request failed.");
        error.status = result.status;
        throw error;
      }
      showMessage(sessionFeedback, result.message || successMessage);
      await refreshStatus();
    } catch (error) {
      showMessage(sessionFeedback, error.message || successMessage, true);
      await refreshStatus();
    } finally {
      requestInProgress = false;
      await refreshStatus();
    }
  }

  startButton.addEventListener("click", () =>
    postSessionAction("/api/monitoring/start", startButton, "Monitoring started."),
  );
  stopButton.addEventListener("click", () =>
    postSessionAction("/api/monitoring/stop", stopButton, "Monitoring stopped."),
  );
  retryButton.addEventListener("click", () =>
    postSessionAction("/api/camera/restart", retryButton, "Camera retry completed."),
  );
  sessionInput.addEventListener("input", refreshStatus);

  modeSelect.addEventListener("change", async () => {
    const sessionId = sessionInput.value.trim();
    modeSelect.disabled = true;
    try {
      const response = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: modeSelect.value, session_id: sessionId }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || result.error || "Could not update processing mode.");
      document.getElementById("active-mode").textContent = modeLabels[result.mode];
      showMessage(sessionFeedback, result.message);
    } catch (error) {
      showMessage(sessionFeedback, error.message || "Could not update processing mode.", true);
      await refreshStatus();
    }
  });

  document.getElementById("test-event").addEventListener("click", async () => {
    const sessionId = sessionInput.value.trim();
    try {
      const response = await fetch("/api/test-event", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || result.error || "Could not create test event.");
      showMessage(sessionFeedback, result.message);
      await refreshStatus();
    } catch (error) {
      showMessage(sessionFeedback, error.message || "Could not create test event.", true);
    }
  });

  refreshStatus();
  window.setInterval(refreshStatus, 2000);
})();
