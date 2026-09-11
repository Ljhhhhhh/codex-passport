#!/usr/bin/env python3
import json
import os
import sys
import time

# Lightweight hook script invoked by Codex lifecycle events.
# Fast, non-blocking, exits immediately after appending to SQLite DB.

DB_DIR = os.path.expanduser('~/.codex-passport')
DB_PATH = os.path.join(DB_DIR, 'tasks.db')

def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        data = json.loads(raw)
    except Exception:
        sys.exit(0)

    event_type = sys.argv[1] if len(sys.argv) > 1 else 'unknown'
    session_id = data.get('session_id') or data.get('payload', {}).get('id') or ''
    turn_id = data.get('turn_id') or ''
    cwd = data.get('cwd') or ''

    if not session_id:
        sys.exit(0)

    try:
        os.makedirs(DB_DIR, exist_ok=True)
        sys.path.insert(0, os.path.dirname(__file__))
        from codex_task_state import TaskStateMachine
        sm = TaskStateMachine(DB_PATH)
        sm.handle_event(event_type, session_id, turn_id, cwd=cwd)
    except Exception:
        pass

    sys.exit(0)

if __name__ == '__main__':
    main()
