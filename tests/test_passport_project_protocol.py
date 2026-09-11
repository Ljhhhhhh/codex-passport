import os
import sys
import unittest
import struct

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../tools')))
from passport_protocol import (
    pack_projects_page,
    pack_tasks_page,
    create_frames,
    MSG_TYPE_PROJECTS,
    MSG_TYPE_TASKS,
)

class TestPassportProjectProtocol(unittest.TestCase):
    def test_pack_projects_page(self):
        items = [
            {'title': 'Fix UI alignment issue', 'project': 'open-webui', 'status': 1},
            {'title': 'Build firmware', 'project': 'ai-passport', 'status': 2},
        ]
        raw = pack_projects_page(0, 1, items)
        self.assertEqual(len(raw), 3 + 3 * (64 + 32 + 1))
        count, p_idx, total = struct.unpack('>BBB', raw[:3])
        self.assertEqual(count, 2)
        self.assertEqual(p_idx, 0)
        self.assertEqual(total, 1)

        frames = create_frames(MSG_TYPE_PROJECTS, raw)
        self.assertEqual(len(frames), 2)
        self.assertTrue(len(frames[0]) <= 240 + 8 + 2)

    def test_pack_tasks_page(self):
        items = [
            {'short_id': 'turn-1', 'state': 2, 'is_read': False, 'duration_sec': 45, 'status_label': 'Wait Input'},
        ]
        raw = pack_tasks_page('open-webui', items)
        self.assertEqual(len(raw), 32 + 1 + 4 * struct.calcsize('>16sBBH24s'))
        frames = create_frames(MSG_TYPE_TASKS, raw)
        self.assertEqual(len(frames), 1)

if __name__ == '__main__':
    unittest.main()
