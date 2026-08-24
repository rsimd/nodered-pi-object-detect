"""Small IoU tracker used to distinguish new objects from stable objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class Detection:
    """One detector result in source-image coordinates."""

    label: str
    class_id: int
    confidence: float
    bbox: BBox


@dataclass
class Track:
    """Mutable state for one object hypothesis."""

    track_id: int
    detection: Detection
    first_seen: float
    last_seen: float
    hits: int = 1
    confirmed: bool = False


def intersection_over_union(left: BBox, right: BBox) -> float:
    """Return intersection-over-union for two ``xyxy`` boxes."""

    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


class IoUTracker:
    """Track detections and emit a track only when it becomes a new object."""

    def __init__(
        self,
        iou_threshold: float = 0.3,
        min_hits: int = 3,
        max_missing_seconds: float = 1.5,
    ) -> None:
        self.iou_threshold = iou_threshold
        self.min_hits = min_hits
        self.max_missing_seconds = max_missing_seconds
        self._tracks: dict[int, Track] = {}
        self._next_id = 1

    @property
    def tracks(self) -> tuple[Track, ...]:
        """Return the current tracks in stable ID order."""

        return tuple(self._tracks[key] for key in sorted(self._tracks))

    def update(self, detections: Iterable[Detection], now: float) -> list[Track]:
        """Update tracks and return tracks confirmed for the first time."""

        detections_list = list(detections)
        unmatched_track_ids = set(self._tracks)
        unmatched_detection_ids = set(range(len(detections_list)))

        pairs: list[tuple[float, int, int]] = []
        for track_id, track in self._tracks.items():
            if now - track.last_seen > self.max_missing_seconds:
                continue
            for detection_id, detection in enumerate(detections_list):
                if detection_id not in unmatched_detection_ids:
                    continue
                if detection.class_id != track.detection.class_id:
                    continue
                score = intersection_over_union(track.detection.bbox, detection.bbox)
                if score >= self.iou_threshold:
                    pairs.append((score, track_id, detection_id))

        new_events: list[Track] = []
        for _, track_id, detection_id in sorted(pairs, reverse=True):
            if track_id not in unmatched_track_ids or detection_id not in unmatched_detection_ids:
                continue
            track = self._tracks[track_id]
            detection = detections_list[detection_id]
            track.detection = detection
            track.last_seen = now
            track.hits += 1
            unmatched_track_ids.remove(track_id)
            unmatched_detection_ids.remove(detection_id)
            if not track.confirmed and track.hits >= self.min_hits:
                track.confirmed = True
                new_events.append(track)

        for detection_id in sorted(unmatched_detection_ids):
            detection = detections_list[detection_id]
            track = Track(
                track_id=self._next_id,
                detection=detection,
                first_seen=now,
                last_seen=now,
                confirmed=self.min_hits <= 1,
            )
            self._tracks[track.track_id] = track
            self._next_id += 1
            if track.confirmed:
                new_events.append(track)

        for track_id in tuple(unmatched_track_ids):
            track = self._tracks.get(track_id)
            if track and now - track.last_seen > self.max_missing_seconds:
                del self._tracks[track_id]

        return new_events
