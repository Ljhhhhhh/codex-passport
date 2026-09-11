import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple
from codex_unread import get_unread_state, UNKNOWN_UNREAD

TASK_STATE_IDLE = 0
TASK_STATE_RUNNING = 1
TASK_STATE_WAITING_INPUT = 2
TASK_STATE_WAITING_APPROVAL = 3
TASK_STATE_COMPLETED = 4
TASK_STATE_INTERRUPTED = 5
TASK_STATE_ERROR = 6
TASK_STATE_UNKNOWN = 7

TASK_STATE_NAMES = {
    TASK_STATE_IDLE: "IDLE",
    TASK_STATE_RUNNING: "RUNNING",
    TASK_STATE_WAITING_INPUT: "WAITING_INPUT",
    TASK_STATE_WAITING_APPROVAL: "WAITING_APPROVAL",
    TASK_STATE_COMPLETED: "COMPLETED",
    TASK_STATE_INTERRUPTED: "INTERRUPTED",
    TASK_STATE_ERROR: "ERROR",
    TASK_STATE_UNKNOWN: "UNKNOWN",
}

class TaskStateMachine:
    """Manages task lifecycle states per (session_id, turn_id)."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    project_name TEXT NOT NULL,
                    cwd TEXT NOT NULL,
                    state INTEGER NOT NULL,
                    is_read INTEGER NOT NULL DEFAULT 0,
                    pending_request_id TEXT,
                    start_time REAL NOT NULL,
                    last_event_time REAL NOT NULL,
                    PRIMARY KEY (session_id, turn_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT,
                    created_at REAL NOT NULL
                )
            """)
            conn.commit()

    def handle_event(
        self,
        event_type: str,
        session_id: str,
        turn_id: str,
        project_name: str = "",
        cwd: str = "",
        now: Optional[float] = None,
        request_id: Optional[str] = None,
    ) -> int:
        ts = now if now is not None else time.time()
        proj = project_name or (os.path.basename(cwd.rstrip("/")) if cwd else "default")

        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT state, pending_request_id, start_time, is_read FROM tasks WHERE session_id=? AND turn_id=?",
                (session_id, turn_id),
            )
            row = cur.fetchone()
            current_state = row[0] if row else TASK_STATE_IDLE
            pending_req = row[1] if row else None
            start_time = row[2] if row else ts
            is_read = row[3] if row else 0

            new_state = current_state
            if event_type in ("task_started", "user_prompt_submit", "turn_start"):
                new_state = TASK_STATE_RUNNING
                is_read = 0
            elif event_type in ("request_user_input", "input_wait"):
                new_state = TASK_STATE_WAITING_INPUT
                pending_req = request_id
                is_read = 0
            elif event_type in ("input_resolved",):
                if current_state == TASK_STATE_WAITING_INPUT and (not request_id or request_id == pending_req):
                    new_state = TASK_STATE_RUNNING
                    pending_req = None
            elif event_type in ("permission_request",):
                new_state = TASK_STATE_WAITING_APPROVAL
                pending_req = request_id
                is_read = 0
            elif event_type in ("permission_resolved",):
                if current_state == TASK_STATE_WAITING_APPROVAL and (not request_id or request_id == pending_req):
                    new_state = TASK_STATE_RUNNING
                    pending_req = None
            elif event_type in ("task_complete", "stop"):
                new_state = TASK_STATE_COMPLETED
            elif event_type in ("interrupt",):
                new_state = TASK_STATE_INTERRUPTED
            elif event_type in ("error", "turn_aborted"):
                new_state = TASK_STATE_ERROR

            cur.execute("""
                INSERT INTO tasks (session_id, turn_id, project_name, cwd, state, is_read, pending_request_id, start_time, last_event_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, turn_id) DO UPDATE SET
                    project_name=excluded.project_name,
                    cwd=excluded.cwd,
                    state=excluded.state,
                    is_read=excluded.is_read,
                    pending_request_id=excluded.pending_request_id,
                    last_event_time=excluded.last_event_time
            """, (session_id, turn_id, proj, cwd, new_state, is_read, pending_req, start_time, ts))

            cur.execute(
                "INSERT INTO events (session_id, turn_id, event_type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, turn_id, event_type, request_id or "", ts),
            )
            conn.commit()
            return new_state

    def mark_read(self, session_id: str, turn_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE tasks SET is_read=1 WHERE session_id=? AND turn_id=?",
                (session_id, turn_id),
            )
            conn.commit()

    def get_summary(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT session_id, turn_id, project_name, state, is_read, start_time, last_event_time FROM tasks")
            rows = cur.fetchall()

        projects: Dict[str, List[Dict[str, Any]]] = {}
        active_count = 0
        pending_count = 0

        for s_id, t_id, proj, st, rd, s_tm, l_tm in rows:
            if st == TASK_STATE_RUNNING:
                active_count += 1
            elif st in (TASK_STATE_WAITING_INPUT, TASK_STATE_WAITING_APPROVAL) or (st == TASK_STATE_COMPLETED and not rd):
                pending_count += 1

            if proj not in projects:
                projects[proj] = []
            projects[proj].append({
                "session_id": s_id,
                "turn_id": t_id,
                "state": st,
                "state_name": TASK_STATE_NAMES.get(st, "UNKNOWN"),
                "is_read": bool(rd),
                "duration_sec": int(l_tm - s_tm),
            })

        return {
            "active_count": active_count,
            "pending_count": pending_count,
            "projects": projects,
        }


class TranscriptWatcher:
    """Incrementally replay local transcripts; API usage is never task completion."""

    def __init__(self, sessions_dir=None):
        from pathlib import Path
        self.root = Path(sessions_dir or os.path.expanduser("~/.codex/sessions"))
        self.files = {}
        self.repositories = {}
        self.global_state_path = Path(os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))) / ".codex-global-state.json"

    def _get_titles(self):
        try:
            if self.global_state_path.is_file():
                data = json.loads(self.global_state_path.read_text())
                desc = data.get("electron-persisted-atom-state", {}).get("thread-descriptions-v1")
                if isinstance(desc, dict):
                    return desc
        except Exception:
            pass
        return {}

    def _prompt_title(self, text):
        if not text or text.startswith("<send_user_message_question_reply>"):
            return ""
        lines = []
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("<") or s.startswith("#") or s.startswith("`" * 3):
                continue
            lines.append(s)
        return lines[-1] if lines else ""

    def _project(self, cwd):
        import subprocess
        if cwd not in self.repositories:
            try:
                result = subprocess.run(
                    ["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                    capture_output=True, text=True, timeout=2, check=True)
                key = os.path.dirname(result.stdout.strip())
            except (OSError, subprocess.SubprocessError):
                key = os.path.realpath(cwd)
            self.repositories[cwd] = key
        return self.repositories[cwd]

    def _record(self, task, record):
        from datetime import datetime
        payload = record.get("payload", {})
        if not isinstance(payload, dict):
            return
        kind = record.get("type")
        try:
            stamp = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00")).timestamp()
        except (KeyError, ValueError, TypeError):
            stamp = 0
        if kind == "session_meta":
            if not task.get("id"):
                task["id"] = payload.get("id", "") or payload.get("session_id", "")
            if not task.get("parent_id"):
                task["parent_id"] = payload.get("parent_thread_id") or payload.get("forked_from_id") or ""
            task["cwd"] = payload.get("cwd", "")
            source = payload.get("source")
            if payload.get("thread_source") == "subagent" or (isinstance(source, dict) and "subagent" in source):
                task["child"] = True
        elif kind == "turn_context":
            task["cwd"] = payload.get("cwd") or task["cwd"]
        elif kind == "event_msg":
            event = payload.get("type")
            turn = payload.get("turn_id")
            if event == "task_started":
                task.update(turn=turn, state="RUN", started=stamp, updated=stamp, pending={})
            elif event in ("task_complete", "turn_aborted", "turn_failed"):
                if turn and turn != task.get("turn"):
                    return
                pending = {k: v for k, v in task["pending"].items() if isinstance(v, set)} if event == "task_complete" else {}
                task.update(state={"task_complete": "DONE", "turn_aborted": "STOP",
                                   "turn_failed": "ERR"}[event], updated=stamp, pending=pending)
        elif kind == "response_item" and payload.get("role") == "user":
            for content in payload.get("content", []):
                text = content.get("text", "") if isinstance(content, dict) else ""
                if not text.startswith("<send_user_message_question_reply>"):
                    title = self._prompt_title(text)
                    if title:
                        task["prompt"] = title
                    continue
                try:
                    replies = json.loads(text.split(">", 1)[1].split("</send_user_message_question_reply>", 1)[0])
                    for reply in replies:
                        identifier = json.loads(reply["questionItemId"])
                        call_id, index = identifier[1], identifier[2]
                        pending = task["pending"].get(call_id)
                        if isinstance(pending, set):
                            pending.discard(index)
                            if not pending:
                                task["pending"].pop(call_id)
                except (ValueError, KeyError, IndexError, TypeError):
                    continue
        elif kind == "response_item" and task.get("state") == "RUN":
            item_type = payload.get("type")
            name = payload.get("name", "").split(".")[-1]
            call_id = payload.get("call_id")
            if item_type == "function_call" and name in ("request_user_input", "request_user_input_async"):
                if name.endswith("_async"):
                    try:
                        questions = json.loads(payload.get("arguments", "{}")).get("questions", [])
                    except (ValueError, TypeError):
                        questions = []
                    task["pending"][call_id] = set(range(max(1, len(questions))))
                else:
                    task["pending"][call_id] = "sync"
            elif item_type == "function_call_output" and task["pending"].get(call_id) == "sync":
                task["pending"].pop(call_id)

    def poll(self):
        from datetime import datetime
        now = time.time()
        today = datetime.fromtimestamp(now).date()
        unread_cnt, unread_ids = get_unread_state(self.global_state_path)
        sync_error = (unread_cnt == UNKNOWN_UNREAD or unread_ids is None)

        candidate_paths = set()
        for path in self.root.rglob("*.jsonl"):
            try:
                stat = path.stat()
                if path in self.files or datetime.fromtimestamp(stat.st_mtime).date() >= today:
                    candidate_paths.add(path)
            except OSError:
                continue

        if unread_ids:
            tracked_ids = {t["id"] for t in self.files.values() if t.get("id")}
            missing_unread = unread_ids - tracked_ids
            for uid in missing_unread:
                for p in self.root.glob(f"**/rollout-*-{uid}.jsonl"):
                    candidate_paths.add(p)

        for path in candidate_paths:
            try:
                stat = path.stat()
                task = self.files.get(path)
                if task is None or stat.st_size < task["pos"] or stat.st_ino != task["inode"]:
                    task = dict(pos=0, inode=stat.st_ino, id="", cwd="", state="UNKNOWN",
                                started=0, updated=0, pending={}, child=False)
                    self.files[path] = task
                with path.open("rb") as stream:
                    stream.seek(task["pos"])
                    while True:
                        line = stream.readline()
                        if not line.endswith(b"\n"):
                            break
                        task["pos"] = stream.tell()
                        try:
                            record = json.loads(line)
                            if isinstance(record, dict):
                                self._record(task, record)
                        except (ValueError, TypeError):
                            continue
            except OSError:
                continue

        effective_unread = set(unread_ids) if unread_ids is not None else set()
        for t in self.files.values():
            if t.get("id") in effective_unread and t.get("parent_id"):
                effective_unread.add(t["parent_id"])

        titles_map = self._get_titles()
        task_messages = []

        for task in self.files.values():
            if task["child"] or not task["cwd"] or not task.get("turn"):
                continue

            tid = task.get("id", "")
            t_state = task.get("state", "UNKNOWN")
            has_pending = bool(task.get("pending"))

            msg_status = 0
            if has_pending:
                msg_status = 1
            elif t_state == "ERR":
                msg_status = 3
            elif t_state == "RUN":
                msg_status = 4
            elif t_state == "DONE":
                if not sync_error and unread_ids is not None and tid in effective_unread:
                    msg_status = 2

            if msg_status == 0:
                continue

            key = self._project(task["cwd"])
            proj_name = os.path.basename(key)
            parent_id = task.get("parent_id", "")
            title = task.get("prompt") or titles_map.get(tid) or (titles_map.get(parent_id) if parent_id else "")
            if not title:
                title = tid[:8] if len(tid) >= 8 else (tid or "task")
            if len(title) > 20:
                title = title[:19] + "…"

            task_messages.append({
                "id": tid,
                "event": (task["turn"], tuple(sorted(task.get("pending", {})))),
                "title": title,
                "project": proj_name,
                "status": msg_status,
                "status_name": {1: "WAIT", 2: "DONE", 3: "ERR", 4: "RUN"}.get(msg_status, ""),
                "updated": task["updated"],
                "started": task["started"],
            })

        task_messages.sort(key=lambda m: m["updated"], reverse=True)

        # Deduplicate transcript records by task identity; equal titles are distinct tasks.
        deduped = []
        seen_keys = set()
        for m in task_messages:
            k = m["id"]
            if k not in seen_keys:
                seen_keys.add(k)
                deduped.append(m)
        task_messages = deduped

        status = dict(state=0, state_name="IDLE", project="", duration_sec=0)
        active_tasks = [t for t in self.files.values() if not t["child"] and t.get("cwd") and t.get("turn")]
        if active_tasks:
            best_task = max(active_tasks, key=lambda t: (bool(t["pending"]), t["state"] == "RUN", t["updated"]))
            b_state = "WAIT" if best_task["pending"] else best_task["state"]
            if b_state in ("RUN", "WAIT", "DONE", "ERR"):
                b_proj = os.path.basename(self._project(best_task["cwd"]))
                status.update(
                    state={"RUN": 1, "WAIT": 2, "DONE": 3, "ERR": 4}.get(b_state, 0),
                    state_name=b_state,
                    project=b_proj,
                    duration_sec=min(65535, max(0, int(now - best_task["started"]))) if b_state in ("RUN", "WAIT") else 0
                )
        return task_messages, status, sync_error
