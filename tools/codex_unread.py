"""Read the desktop app's persisted unread set without changing read receipts."""
import json
import os
from pathlib import Path
from typing import Optional, Set, Tuple

UNKNOWN_UNREAD = 0xFFFFFFFF


def get_unread_state(path=None) -> Tuple[int, Optional[Set[str]]]:
    """Returns (count, unread_ids_set). If reading fails, returns (UNKNOWN_UNREAD, None)."""
    path = Path(path) if path is not None else Path(
        os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
    ) / ".codex-global-state.json"
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return UNKNOWN_UNREAD, None
        ids = set()
        # 1. Primary current source: electron-thread-read-state-v1.unreadByIdentity
        read_state = data.get("electron-thread-read-state-v1")
        if isinstance(read_state, dict):
            by_identity = read_state.get("unreadByIdentity")
            if isinstance(by_identity, dict):
                total_count = 0
                for hosts in by_identity.values():
                    if not isinstance(hosts, dict):
                        return UNKNOWN_UNREAD, None
                    for tids in hosts.values():
                        if not isinstance(tids, list):
                            return UNKNOWN_UNREAD, None
                        clean = set()
                        for tid in tids:
                            if not isinstance(tid, str) or not tid:
                                return UNKNOWN_UNREAD, None
                            clean.add(tid)
                        total_count += len(clean)
                        ids.update(clean)
                return min(UNKNOWN_UNREAD - 1, total_count), ids

        # 2. Legacy fallback: electron-persisted-atom-state.unread-thread-ids-by-host-v1
        atom = data.get("electron-persisted-atom-state")
        if isinstance(atom, dict) and "unread-thread-ids-by-host-v1" in atom:
            hosts = atom["unread-thread-ids-by-host-v1"]
            if hosts is None or not isinstance(hosts, dict):
                return UNKNOWN_UNREAD, None
            total_count = 0
            for tids in hosts.values():
                if not isinstance(tids, list):
                    return UNKNOWN_UNREAD, None
                clean = set()
                for tid in tids:
                    if not isinstance(tid, str) or not tid:
                        return UNKNOWN_UNREAD, None
                    clean.add(tid)
                total_count += len(clean)
                ids.update(clean)
            return min(UNKNOWN_UNREAD - 1, total_count), ids

        return UNKNOWN_UNREAD, None
    except (OSError, ValueError, KeyError, TypeError):
        return UNKNOWN_UNREAD, None


def unread_count(path=None) -> int:
    count, _ = get_unread_state(path)
    return count
