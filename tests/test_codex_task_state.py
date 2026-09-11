import os
import sys
import tempfile
import unittest
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../tools')))
from codex_task_state import (
    TaskStateMachine,
    TASK_STATE_IDLE,
    TASK_STATE_RUNNING,
    TASK_STATE_WAITING_INPUT,
    TASK_STATE_WAITING_APPROVAL,
    TASK_STATE_COMPLETED,
    TASK_STATE_INTERRUPTED,
    TASK_STATE_ERROR,
)

class TestTaskStateMachine(unittest.TestCase):
    def setUp(self):
        self.tf = tempfile.NamedTemporaryFile(delete=False)
        self.tf.close()
        self.sm = TaskStateMachine(self.tf.name)

    def tearDown(self):
        if os.path.exists(self.tf.name):
            os.unlink(self.tf.name)

    def test_basic_lifecycle(self):
        s_id = 'sess-1'
        t_id = 'turn-1'
        st = self.sm.handle_event('task_started', s_id, t_id, project_name='test-proj')
        self.assertEqual(st, TASK_STATE_RUNNING)

        # Ask input
        st = self.sm.handle_event('request_user_input', s_id, t_id, project_name='test-proj', request_id='call-1')
        self.assertEqual(st, TASK_STATE_WAITING_INPUT)

        # Resolved
        st = self.sm.handle_event('input_resolved', s_id, t_id, project_name='test-proj', request_id='call-1')
        self.assertEqual(st, TASK_STATE_RUNNING)

        # Turn complete
        st = self.sm.handle_event('task_complete', s_id, t_id, project_name='test-proj')
        self.assertEqual(st, TASK_STATE_COMPLETED)

        summary = self.sm.get_summary()
        self.assertEqual(summary['pending_count'], 1)  # unread completed turn

        # Mark read
        self.sm.mark_read(s_id, t_id)
        summary2 = self.sm.get_summary()
        self.assertEqual(summary2['pending_count'], 0)

    def test_permission_request_flow(self):
        s_id = 'sess-2'
        t_id = 'turn-1'
        self.sm.handle_event('task_started', s_id, t_id, project_name='proj-2')
        st = self.sm.handle_event('permission_request', s_id, t_id, request_id='perm-1')
        self.assertEqual(st, TASK_STATE_WAITING_APPROVAL)

        summary = self.sm.get_summary()
        self.assertEqual(summary['pending_count'], 1)

        # Resolved
        st = self.sm.handle_event('permission_resolved', s_id, t_id, request_id='perm-1')
        self.assertEqual(st, TASK_STATE_RUNNING)

if __name__ == '__main__':
    unittest.main()
