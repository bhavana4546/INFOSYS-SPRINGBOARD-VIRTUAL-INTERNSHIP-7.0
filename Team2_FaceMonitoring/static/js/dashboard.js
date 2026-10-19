(() => {
  "use strict";

  const statusDot = document.getElementById("status-dot");
  const cameraStatus = document.getElementById("camera-status");
  const cameraError = document.getElementById("camera-error");
  const eventList = document.getElementById("event-list");
  const modeSelect = document.getElementById("processing-mode");
  const actionMessage = document.getElementById("action-message");
  const modeLabels = {
    normal: "Normal video",
    grayscale: "Grayscale",
    blur: "Gaussian blur",
    threshold: "Binary threshold",
    canny: "Canny edges",
  };

  function showActionMessage(message, isError = false) {
    actionMessage.textContent = message;
    actionMessage.style.color = isError ? "#ff9ba4" : "#42d392";
  }

  function renderEvents(events) {
    eventList.replaceChildren();
    document.getElementById("event-total").textContent = String(events.length);
    if (!events.length) {
      const empty = document.createElement("li");
      empty.className = "empty-state";
      empty.textContent = "No events yet.";
      eventList.append(empty);
      return;
    }
    for (const event of events) {
      const item = document.createElement("li");
      item.className = "event-item";
      const message = document.createElement("strong");
      message.textContent = event.message;
      const time = document.createElement("time");
      const date = new Date(event.timestamp);
      time.dateTime = event.timestamp;
      time.textContent = Number.isNaN(date.getTime()) ? event.timestamp : date.toLocaleString();
      item.append(message, time);
      eventList.append(item);
    }
  }

  async function refreshStatus() {
    try {
      const response = await fetch("/api/status", { cache: "no-store" });
      if (!response.ok) throw new Error(`Status request failed (${response.status}).`);
      const data = await response.json();
      const state = data.camera_status || "offline";
      cameraStatus.textContent = state.charAt(0).toUpperCase() + state.slice(1);
      statusDot.classList.toggle("online", state === "online");
      statusDot.classList.toggle("offline", state === "offline");
      cameraError.textContent = data.camera_error || "";
      document.getElementById("face-count").textContent = String(data.face_count ?? 0);
      document.getElementById("fps").textContent = Number(data.fps || 0).toFixed(1);
      document.getElementById("latency").textContent = `${Number(data.latency_ms || 0).toFixed(1)} ms`;
      document.getElementById("opencv-version").textContent = data.opencv_version || "Unavailable";
      document.getElementById("platform").textContent = data.platform || "Unavailable";
      document.getElementById("cpu-usage").textContent =
        data.system_metrics?.cpu_percent == null ? "Not available" : `${data.system_metrics.cpu_percent}%`;
      document.getElementById("memory-usage").textContent =
        data.system_metrics?.memory_percent == null ? "Not available" : `${data.system_metrics.memory_percent}%`;
      if (modeLabels[data.processing_mode]) {
        modeSelect.value = data.processing_mode;
        document.getElementById("active-mode").textContent = modeLabels[data.processing_mode];
      }
      renderEvents(Array.isArray(data.events) ? data.events : []);
    } catch (error) {
      cameraStatus.textContent = "Server unavailable";
      statusDot.classList.remove("online");
      statusDot.classList.add("offline");
      cameraError.textContent = error.message || "Could not connect to the dashboard server.";
    }
  }

  modeSelect.addEventListener("change", async () => {
    modeSelect.disabled = true;
    try {
      const response = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: modeSelect.value }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Could not update processing mode.");
      document.getElementById("active-mode").textContent = modeLabels[result.mode];
      showActionMessage(`Display mode set to ${modeLabels[result.mode]}.`);
    } catch (error) {
      showActionMessage(error.message || "Could not update processing mode.", true);
      await refreshStatus();
    } finally {
      modeSelect.disabled = false;
    }
  });

  document.getElementById("restart-camera").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const response = await fetch("/api/camera/restart", { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Camera restart failed.");
      showActionMessage(result.message);
      await refreshStatus();
    } catch (error) {
      showActionMessage(error.message || "Could not request camera restart.", true);
    } finally {
      button.disabled = false;
    }
  });

  document.getElementById("test-event").addEventListener("click", async () => {
    try {
      const response = await fetch("/api/test-event", { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Could not create test event.");
      showActionMessage(result.message);
      await refreshStatus();
    } catch (error) {
      showActionMessage(error.message || "Could not create test event.", true);
    }
  });

  refreshStatus();
  window.setInterval(refreshStatus, 2000);
})();
