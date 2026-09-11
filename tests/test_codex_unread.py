import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from codex_unread import unread_count, UNKNOWN_UNREAD


class UnreadTests(unittest.TestCase):
    def test_app_receipts_and_unavailable_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            self.assertEqual(unread_count(path), UNKNOWN_UNREAD)
            for hosts, expected in [({"local": ["a", "b", "a"], "remote": ["a"]}, 3),
                                    ({"local": ["b"]}, 1), ({"local": []}, 0),
                                    ({}, 0), ({"local": None}, UNKNOWN_UNREAD)]:
                path.write_text(json.dumps({"electron-persisted-atom-state": {
                    "unread-thread-ids-by-host-v1": hosts}}))
                self.assertEqual(unread_count(path), expected)
            for value in ["{", "{}", "null"]:
                path.write_text(value)
                self.assertEqual(unread_count(path), UNKNOWN_UNREAD)

    def test_electron_thread_read_state_v1(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps({
                "electron-thread-read-state-v1": {
                    "version": 1,
                    "unreadByIdentity": {
                        "user1": {"local": ["t1", "t2", "t1"], "remote": ["t3"]},
                        "user2": {"local": ["t4"]}
                    }
                }
            }))
            self.assertEqual(unread_count(path), 4)
            path.write_text(json.dumps({
                "electron-thread-read-state-v1": {
                    "version": 1,
                    "unreadByIdentity": {}
                }
            }))
            self.assertEqual(unread_count(path), 0)
            path.write_text(json.dumps({
                "electron-thread-read-state-v1": {
                    "version": 1,
                    "unreadByIdentity": {"user1": {"local": [None]}}
                }
            }))
            self.assertEqual(unread_count(path), UNKNOWN_UNREAD)


if __name__ == "__main__":
    unittest.main()
