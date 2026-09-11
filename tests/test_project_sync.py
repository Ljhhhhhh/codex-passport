import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import time
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from codex_task_state import TranscriptWatcher
from codex_unread import UNKNOWN_UNREAD
from passport_protocol import create_frames, pack_projects_page
from assistant import PassportAssistant, MessageAlerts


class ProjectSyncTests(unittest.TestCase):
    def test_alerts_follow_identity_and_turn_not_count(self):
        a = MessageAlerts()
        def message(tid, status=2, turn="one"):
            return dict(id=tid, status=status, event=(turn, ()))
        self.assertFalse(a.update([message("old")]))
        self.assertFalse(a.update([message("old")]))
        self.assertTrue(a.update([message("new")]))  # same count
        self.assertFalse(a.update([message("new")]))
        self.assertFalse(a.update([message("new", 4)]))  # running
        self.assertTrue(a.update([message("new", 1)]))  # input needed
        self.assertTrue(a.update([message("new", 3)]))  # failed
        self.assertTrue(a.update([message("new", 2, "two")]))
        self.assertFalse(a.update([], False))
        self.assertFalse(a.update([message("new", 2, "two")]))
        self.assertFalse(a.update([]))  # read/removal

    def test_transcripts_recovery_parallel_partial_and_terminals(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def append(name, kind, payload, newline=True):
                record = dict(timestamp=datetime.now(timezone.utc).isoformat(), type=kind, payload=payload)
                with (root / name).open("a") as stream:
                    stream.write(json.dumps(record) + ("\n" if newline else ""))
            for name in ("one", "two", "child"):
                name += ".jsonl"
                append(name, "session_meta", dict(id=name, cwd=folder,
                       source={"subagent": "test"} if name.startswith("child") else "vscode"))
                append(name, "event_msg", dict(type="task_started", turn_id="t1"))
            watcher = TranscriptWatcher(root)
            msgs, state, sync_err = watcher.poll()
            self.assertEqual(len(msgs), 2)
            self.assertTrue(all(m["status"] == 4 for m in msgs))
            self.assertEqual(state["state_name"], "RUN")
            with patch("codex_task_state.time.time", return_value=time.time() + 120):
                self.assertEqual(watcher.poll()[1]["state_name"], "RUN")
            append("one.jsonl", "event_msg", dict(type="item_completed"))
            self.assertEqual(watcher.poll()[1]["state_name"], "RUN")
            append("one.jsonl", "event_msg", dict(type="task_complete", turn_id="old"))
            self.assertEqual(watcher.poll()[1]["state_name"], "RUN")
            append("one.jsonl", "response_item", dict(type="function_call", name="functions.request_user_input_async", call_id="q"))
            append("one.jsonl", "response_item", dict(type="function_call_output", call_id="q"))
            msgs, _, _ = watcher.poll()
            self.assertEqual(sorted(m["status"] for m in msgs), [1, 4])
            append("one.jsonl", "event_msg", dict(type="user_message"))
            self.assertEqual(sorted(m["status"] for m in watcher.poll()[0]), [1, 4])
            reply = "<send_user_message_question_reply>" + json.dumps([
                dict(questionItemId=json.dumps(["request_user_input_async", "q", 0]), answer="yes")
            ]) + "</send_user_message_question_reply>"
            append("one.jsonl", "response_item", dict(type="message", role="user", content=[dict(type="input_text", text=reply)]))
            msgs, _, _ = watcher.poll()
            self.assertTrue(all(m["status"] == 4 for m in msgs))
            append("one.jsonl", "event_msg", dict(type="task_complete", turn_id="t1"), newline=False)
            self.assertTrue(all(m["status"] == 4 for m in watcher.poll()[0]))
            with (root / "one.jsonl").open("a") as stream:
                stream.write("\n")
            append("two.jsonl", "event_msg", dict(type="turn_aborted", turn_id="t1"))
            append("two.jsonl", "event_msg", dict(type="turn_failed", turn_id="t1"))
            with patch("codex_task_state.get_unread_state", return_value=(1, {"one.jsonl"})):
                msgs, _, _ = TranscriptWatcher(root).poll()
                self.assertEqual(len(msgs), 2)
                self.assertEqual([m["status"] for m in msgs], [3, 2])

    def test_message_filtering_and_edge_cases(self):
        """Verify unread completed, waiting input, failed filtering rules."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def append(name, kind, payload):
                record = dict(timestamp=datetime.now(timezone.utc).isoformat(), type=kind, payload=payload)
                with (root / name).open("a") as stream:
                    stream.write(json.dumps(record) + "\n")

            # Task 1: completed, read (NOT in unread) -> should be excluded
            append("read_done.jsonl", "session_meta", dict(id="t_read_done", cwd="/path/proj1", source="vscode"))
            append("read_done.jsonl", "event_msg", dict(type="task_started", turn_id="t1"))
            append("read_done.jsonl", "event_msg", dict(type="task_complete", turn_id="t1"))

            # Task 2: completed, unread -> should be included (status 2)
            append("unread_done.jsonl", "session_meta", dict(id="t_unread_done", parent_thread_id="t_parent", cwd="/path/proj1", source="vscode"))
            append("unread_done.jsonl", "event_msg", dict(type="task_started", turn_id="t1"))
            append("unread_done.jsonl", "event_msg", dict(type="task_complete", turn_id="t1"))

            # Task 3: failed -> should be included (status 3), even if read
            append("failed.jsonl", "session_meta", dict(id="t_failed", cwd="/path/proj2", source="vscode"))
            append("failed.jsonl", "event_msg", dict(type="task_started", turn_id="t1"))
            append("failed.jsonl", "event_msg", dict(type="turn_failed", turn_id="t1"))

            # Task 4: waiting input -> should be included (status 1)
            append("wait.jsonl", "session_meta", dict(id="t_wait", cwd="/path/proj1", source="vscode"))
            append("wait.jsonl", "event_msg", dict(type="task_started", turn_id="t1"))
            append("wait.jsonl", "response_item", dict(type="function_call", name="functions.request_user_input_async", call_id="q1"))
            append("wait.jsonl", "response_item", dict(type="function_call_output", call_id="q1"))

            # Task 5: running -> excluded
            # Task 5: running uses latest user prompt
            append("running.jsonl", "session_meta", dict(id="t_running", cwd="/path/proj3", source="vscode"))
            append("running.jsonl", "event_msg", dict(type="task_started", turn_id="t1"))
            append("running.jsonl", "response_item", dict(type="message", role="user", content=[dict(type="input_text", text="最新用户消息内容")]))

            # Task 6: aborted / stop -> excluded
            append("stop.jsonl", "session_meta", dict(id="t_stop", cwd="/path/proj3", source="vscode"))
            append("stop.jsonl", "event_msg", dict(type="task_started", turn_id="t1"))
            append("stop.jsonl", "event_msg", dict(type="turn_aborted", turn_id="t1"))

            append("sub.jsonl", "session_meta", dict(id="t_sub", session_id="t_parent_user", parent_thread_id="t_parent_user", thread_source="subagent", source={"subagent": {}}, cwd="/path/proj1"))
            append("sub.jsonl", "session_meta", dict(id="t_parent_user", session_id="t_parent_user", thread_source="user", source="vscode", cwd="/path/proj1"))
            append("sub.jsonl", "event_msg", dict(type="task_started", turn_id="t1"))
            append("sub.jsonl", "event_msg", dict(type="task_complete", turn_id="t1"))

            # Case A: unread source normal with t_unread_done in unread_ids
            with patch("codex_task_state.get_unread_state", return_value=(2, {"t_unread_done", "t_sub"})):
                w = TranscriptWatcher(root)
                w._get_titles = lambda: {"t_parent": "Real Title"}
                msgs, status, sync_err = w.poll()
                self.assertFalse(sync_err)
                msg_ids = {m["id"]: m["status"] for m in msgs}
                self.assertNotIn("t_read_done", msg_ids)
                self.assertNotIn("t_sub", msg_ids)
                self.assertEqual(msg_ids.get("t_unread_done"), 2)
                m_unread = next(m for m in msgs if m["id"] == "t_unread_done")
                self.assertEqual(m_unread["title"], "Real Title")
                self.assertEqual(msg_ids.get("t_failed"), 3)
                self.assertEqual(msg_ids.get("t_wait"), 1)
                self.assertEqual(msg_ids.get("t_running"), 4)
                self.assertEqual(next(m for m in msgs if m["id"] == "t_running")["title"], "最新用户消息内容")
                self.assertNotIn("t_stop", msg_ids)

            # Case B: re-run replaces failed with in-progress
            append("failed.jsonl", "event_msg", dict(type="task_started", turn_id="t2"))
            with patch("codex_task_state.get_unread_state", return_value=(1, {"t_unread_done"})):
                w = TranscriptWatcher(root)
                msgs, _, _ = w.poll()
                msg_ids = {m["id"]: m["status"] for m in msgs}
                self.assertEqual(msg_ids.get("t_failed"), 4)

            # Case C: unread source failure (sync_err = True)
            with patch("codex_task_state.get_unread_state", return_value=(UNKNOWN_UNREAD, None)):
                w = TranscriptWatcher(root)
                msgs, status, sync_err = w.poll()
                self.assertTrue(sync_err)
                msg_ids = {m["id"]: m["status"] for m in msgs}
                self.assertNotIn("t_unread_done", msg_ids)
                self.assertEqual(msg_ids.get("t_wait"), 1)

            # Case D: subagent is in unread_ids -> parent thread is recognized as unread completed (status 2)
            append("parent_task.jsonl", "session_meta", dict(id="t_parent_only", cwd="/path/proj4", source="vscode"))
            append("parent_task.jsonl", "event_msg", dict(type="task_started", turn_id="t1"))
            append("parent_task.jsonl", "event_msg", dict(type="task_complete", turn_id="t1"))
            append("child_agent.jsonl", "session_meta", dict(id="t_sub_agent", parent_thread_id="t_parent_only", thread_source="subagent", cwd="/path/proj4"))
            append("child_agent.jsonl", "event_msg", dict(type="task_started", turn_id="t1"))
            append("child_agent.jsonl", "event_msg", dict(type="task_complete", turn_id="t1"))
            with patch("codex_task_state.get_unread_state", return_value=(1, {"t_sub_agent"})):
                w = TranscriptWatcher(root)
                msgs, _, _ = w.poll()
                msg_ids = {m["id"]: m["status"] for m in msgs}
                self.assertEqual(msg_ids.get("t_parent_only"), 2)
                self.assertNotIn("t_sub_agent", msg_ids)

    def test_python_frames_are_accepted_by_firmware(self):
        main = Path(__file__).resolve().parents[1] / "main"
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "check.c"
            source.write_text('''#include "passport_protocol.h"
#include "passport_ui.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv) {
    assert(argc == 3);
    assert(PAGE_PROJECTS < PAGE_CYCLE && PAGE_QR_CODE >= PAGE_CYCLE);
    passport_reassembler_t r; passport_reassembler_init(&r);
    uint8_t type, *payload; size_t length;
    for (int i = 1; i <= 2; i++) {
        FILE *f = fopen(argv[i], "rb"); assert(f);
        unsigned char frame[260]; size_t n = fread(frame, 1, sizeof(frame), f); fclose(f);
        bool ok = passport_reassembler_feed(&r, frame, n, &type, &payload, &length);
        if (i == 1) assert(!ok);
        if (i == 2) assert(ok);
    }
    assert(type == MSG_TYPE_PROJECTS && length <= sizeof(passport_messages_page_t));
    passport_messages_page_t *p = (passport_messages_page_t *)payload;
    assert(p->count == 1 && p->page_index == 0 && p->total_pages == 1);
    assert(strcmp(p->items[0].title, "Task title") == 0);
    assert(strcmp(p->items[0].project, "my-project") == 0);
    assert(p->items[0].status == 1);
    return 0;
}
''')
            binary = Path(folder) / "check"
            subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-I" + str(main), str(source), str(main / "passport_protocol.c"),
                            "-o", str(binary)], check=True)
            raw = pack_projects_page(0, 1, [dict(title="Task title", project="my-project", status=1)])
            frames = create_frames(9, raw)
            assert len(frames) == 2
            f1 = Path(folder) / "frame1"
            f2 = Path(folder) / "frame2"
            f1.write_bytes(frames[0])
            f2.write_bytes(frames[1])
            subprocess.run([str(binary), str(f1), str(f2)], check=True)

    def test_event_alert_after_page_ack_and_no_replay(self):
        class Watcher:
            calls = 0
            def poll(self):
                self.calls += 1
                tid = "old" if self.calls == 1 else "new"
                return [dict(id=tid, title=tid, project="p", status=2)], dict(state=3, state_name="DONE"), False
        class Device:
            is_connected = True
            events = []
            async def read_gatt_char(self, uuid):
                return b"\x01P\x01\x00\x01\x01"
            async def start_notify(self, uuid, callback):
                self.callback = callback
            async def write_gatt_char(self, uuid, data, response):
                if data[:3] == b"PT\x01" and data[4] == data[5] - 1:
                    kind = data[3]
                    self.events.append(kind)
                    self.callback(None, create_frames(7, bytes([kind, 0]))[0])
        device = Device()
        service = PassportAssistant.__new__(PassportAssistant)
        service.watcher = Watcher()
        service.prepare_sync_payloads = lambda: {}
        async def tick(_):
            if service.watcher.calls >= 3:
                device.is_connected = False
        with patch("assistant.unread_count", return_value=1), patch("assistant.asyncio.sleep", side_effect=tick):
            asyncio.run(service._session_loop(device, 60))
        self.assertEqual(device.events, [10, 9, 9, 12])

    def test_live_service_sends_projects_and_requires_ack(self):
        class Watcher:
            def poll(self):
                return [dict(title="title", project="project", status=1)], dict(state=1, project="project", state_name="RUN"), False
        class Device:
            is_connected = True
            sent = []
            unread = []
            async def read_gatt_char(self, uuid):
                return b"\x01P\x01\x00\x01"
            async def start_notify(self, uuid, callback):
                self.callback = callback
            async def write_gatt_char(self, uuid, data, response):
                if data[:4] == b"PT\x01\x0a":
                    self.unread.append(int.from_bytes(data[8:12], "little"))
                    self.callback(None, create_frames(7, b"\x0a\x00")[0])
                if data[:4] == b"PT\x01\x09":
                    self.sent.append(data)
                    if data[4] == data[5] - 1:
                        self.callback(None, create_frames(7, b"\x09\x00")[0])
                    self.is_connected = False
        service = PassportAssistant.__new__(PassportAssistant)
        service.watcher = Watcher()
        service.prepare_sync_payloads = lambda: {}
        device = Device()
        with patch("assistant.unread_count", return_value=7):
            asyncio.run(service._session_loop(device, 60))
        self.assertEqual(device.unread, [7])
        self.assertEqual(len(device.sent), 2)


if __name__ == "__main__":
    unittest.main()
