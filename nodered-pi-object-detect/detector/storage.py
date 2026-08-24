"""Atomic JPEG and event-index storage."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .tracking import Track


def _atomic_bytes(path: Path, data: bytes) -> None:
    """Write bytes through a same-directory temporary file."""

    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _atomic_json(path: Path, data: Any) -> None:
    """Write JSON through an atomic replacement."""

    encoded = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    _atomic_bytes(path, encoded)


class EventStorage:
    """Store latest preview frames and bounded event images."""

    def __init__(self, public_dir: str, max_events: int, retention_days: int) -> None:
        self.public_dir = Path(public_dir)
        self.events_dir = self.public_dir / "events"
        self.index_path = self.events_dir / "index.json"
        self.max_events = max_events
        self.retention_days = retention_days
        self.events_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            _atomic_json(self.index_path, [])

    def write_latest(self, frame: np.ndarray) -> None:
        """Replace the latest JPEG preview."""

        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if ok:
            _atomic_bytes(self.public_dir / "latest.jpg", encoded.tobytes())

    def save_event(self, frame: np.ndarray, track: Track) -> dict[str, Any]:
        """Save a padded object crop and update the event index."""

        now = datetime.now(timezone.utc)
        safe_label = "".join(character if character.isalnum() else "_" for character in track.detection.label)
        event_id = f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-{safe_label}-{track.track_id}-{uuid.uuid4().hex[:6]}"
        event_dir = self.events_dir / event_id
        event_dir.mkdir(parents=True, exist_ok=False)

        height, width = frame.shape[:2]
        x1, y1, x2, y2 = track.detection.bbox
        padding_x = max(8.0, (x2 - x1) * 0.15)
        padding_y = max(8.0, (y2 - y1) * 0.15)
        left = max(0, int(x1 - padding_x))
        top = max(0, int(y1 - padding_y))
        right = min(width, int(x2 + padding_x))
        bottom = min(height, int(y2 + padding_y))
        crop = frame[top:bottom, left:right]
        if crop.size == 0:
            shutil.rmtree(event_dir, ignore_errors=True)
            raise RuntimeError("Detected object crop was empty")

        ok, encoded = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise RuntimeError("Unable to encode event image")
        _atomic_bytes(event_dir / "image.jpg", encoded.tobytes())

        thumbnail = crop
        max_width = 280
        if thumbnail.shape[1] > max_width:
            scale = max_width / thumbnail.shape[1]
            thumbnail = cv2.resize(thumbnail, (max_width, max(1, int(thumbnail.shape[0] * scale))))
        ok, encoded_thumb = cv2.imencode(".jpg", thumbnail, [cv2.IMWRITE_JPEG_QUALITY, 78])
        if ok:
            _atomic_bytes(event_dir / "thumb.jpg", encoded_thumb.tobytes())

        event = {
            "id": event_id,
            "label": track.detection.label,
            "confidence": round(track.detection.confidence, 4),
            "timestamp": now.isoformat(),
            "bbox": [round(value, 2) for value in track.detection.bbox],
            "image": f"/events/{event_id}/image.jpg",
            "thumbnail": f"/events/{event_id}/thumb.jpg",
        }
        index = self._load_index()
        index.insert(0, event)
        self._write_bounded_index(index)
        return event

    def _load_index(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.index_path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _write_bounded_index(self, index: list[dict[str, Any]]) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        retained: list[dict[str, Any]] = []
        for event in index:
            try:
                timestamp = datetime.fromisoformat(str(event["timestamp"]))
            except (KeyError, TypeError, ValueError):
                timestamp = datetime.min.replace(tzinfo=timezone.utc)
            if timestamp >= cutoff and len(retained) < self.max_events:
                retained.append(event)
            else:
                event_id = event.get("id")
                if isinstance(event_id, str):
                    shutil.rmtree(self.events_dir / event_id, ignore_errors=True)
        _atomic_json(self.index_path, retained)
