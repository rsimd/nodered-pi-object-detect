"use strict";

const preview = document.querySelector("#preview");
const health = document.querySelector("#health");
const metrics = document.querySelector("#metrics");
const eventsElement = document.querySelector("#events");
const eventCount = document.querySelector("#event-count");
const empty = document.querySelector("#empty");
const viewer = document.querySelector("#viewer");
const largeImage = document.querySelector("#large-image");
const largeCaption = document.querySelector("#large-caption");

function setPreview() {
  preview.src = `/latest.jpg?t=${Date.now()}`;
}

function formatTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("ja-JP");
}

function showViewer(event) {
  largeImage.src = event.image;
  largeCaption.textContent = `${event.label} / 信頼度 ${(event.confidence * 100).toFixed(1)}% / ${formatTime(event.timestamp)}`;
  if (typeof viewer.showModal === "function") viewer.showModal();
  else viewer.setAttribute("open", "");
}

function renderEvents(events) {
  eventsElement.replaceChildren();
  eventCount.textContent = `${events.length}件`;
  empty.hidden = events.length > 0;
  for (const event of events) {
    const button = document.createElement("button");
    button.className = "event-item";
    button.type = "button";
    button.addEventListener("click", () => showViewer(event));

    const image = document.createElement("img");
    image.src = `${event.thumbnail}?t=${encodeURIComponent(event.timestamp)}`;
    image.alt = event.label;
    image.loading = "lazy";
    button.appendChild(image);

    const label = document.createElement("span");
    label.className = "event-label";
    label.textContent = event.label;
    button.appendChild(label);

    const detail = document.createElement("small");
    detail.textContent = `${(event.confidence * 100).toFixed(1)}% / ${formatTime(event.timestamp)}`;
    button.appendChild(detail);
    eventsElement.appendChild(button);
  }
}

async function refreshState() {
  try {
    const [healthResponse, eventsResponse] = await Promise.all([
      fetch(`/api/health?t=${Date.now()}`, { cache: "no-store" }),
      fetch(`/events/index.json?t=${Date.now()}`, { cache: "no-store" })
    ]);
    const healthData = await healthResponse.json();
    const events = await eventsResponse.json();
    const status = healthData.status || healthData.detector || {};
    const camera = healthData.camera || {};
    health.textContent = healthData.ok ? "稼働中" : (status.state || "エラー");
    health.className = `health ${healthData.ok ? "health-ok" : "health-error"}`;
    metrics.textContent = `映像 ${Number(camera.fps || 0).toFixed(1)} FPS / 推論 ${Number(status.inference_ms || 0).toFixed(0)} ms`;
    renderEvents(Array.isArray(events) ? events : []);
  } catch (error) {
    health.textContent = "接続エラー";
    health.className = "health health-error";
    metrics.textContent = "Node-REDまたはカメラを確認してください";
  }
}

document.querySelector("#close-viewer").addEventListener("click", () => viewer.close());
viewer.addEventListener("click", (event) => {
  if (event.target === viewer) viewer.close();
});

setPreview();
refreshState();
setInterval(setPreview, 250);
setInterval(refreshState, 1000);
