import unittest

from detector.tracking import Detection, IoUTracker, intersection_over_union


def detection(x1: float, y1: float, x2: float, y2: float) -> Detection:
    return Detection("person", 0, 0.9, (x1, y1, x2, y2))


class TrackerTests(unittest.TestCase):
    def test_iou_is_symmetric(self):
        left = (0, 0, 10, 10)
        right = (5, 5, 15, 15)
        self.assertEqual(intersection_over_union(left, right), intersection_over_union(right, left))

    def test_stable_object_emits_one_event_after_three_hits(self):
        tracker = IoUTracker(iou_threshold=0.3, min_hits=3, max_missing_seconds=1.5)
        self.assertEqual(tracker.update([detection(0, 0, 10, 10)], 0.0), [])
        self.assertEqual(tracker.update([detection(1, 0, 11, 10)], 0.2), [])
        events = tracker.update([detection(2, 0, 12, 10)], 0.4)
        self.assertEqual(len(events), 1)
        self.assertEqual(tracker.update([detection(2, 0, 12, 10)], 0.6), [])

    def test_reappearing_object_gets_new_event(self):
        tracker = IoUTracker(iou_threshold=0.3, min_hits=1, max_missing_seconds=1.0)
        first = tracker.update([detection(0, 0, 10, 10)], 0.0)
        self.assertEqual(len(first), 1)
        self.assertEqual(tracker.update([], 2.0), [])
        second = tracker.update([detection(0, 0, 10, 10)], 2.1)
        self.assertEqual(len(second), 1)
        self.assertNotEqual(second[0].track_id, first[0].track_id)

    def test_two_same_class_objects_are_tracked_separately(self):
        tracker = IoUTracker(iou_threshold=0.3, min_hits=2, max_missing_seconds=1.0)
        tracker.update([detection(0, 0, 10, 10), detection(30, 0, 40, 10)], 0.0)
        events = tracker.update([detection(1, 0, 11, 10), detection(31, 0, 41, 10)], 0.2)
        self.assertEqual({event.track_id for event in events}, {1, 2})


if __name__ == "__main__":
    unittest.main()
