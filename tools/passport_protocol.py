#!/usr/bin/env python3
import struct
from pathlib import Path
from functools import lru_cache
from typing import Any, Dict, List, Tuple

PASSPORT_MAGIC_0 = 0x50  # 'P'
PASSPORT_MAGIC_1 = 0x54  # 'T'
PASSPORT_PROTOCOL_VER = 0x01

MSG_TYPE_PROFILE = 0x01
MSG_TYPE_STATS = 0x02
MSG_TYPE_HEATMAP = 0x03
MSG_TYPE_FOOTPRINTS = 0x04
MSG_TYPE_DIRECTIONS = 0x05
MSG_TYPE_REALTIME = 0x06
MSG_TYPE_ACK = 0x07
MSG_TYPE_QUOTA = 0x08
MSG_TYPE_PROJECTS = 0x09
MSG_TYPE_MESSAGES = 0x09
MSG_TYPE_TASKS = 0x0A
MSG_TYPE_ACTION_READ = 0x0B
MSG_TYPE_ALERT = 0x0C

@lru_cache(maxsize=1)
def supported_chars():
    return frozenset((Path(__file__).resolve().parents[1] / "assets/fonts/charset.txt").read_text(encoding="utf-8"))


def encode_text(text: str, limit: int) -> bytes:
    text = "".join(c if c.isprintable() else " " for c in str(text))
    text = "".join(c if c in supported_chars() else "?" for c in text)
    return text.encode("utf-8", errors="replace")[:limit].decode("utf-8", errors="ignore").encode("utf-8")

def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= (b << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc

def pack_projects_page(page_index: int, total_pages: int, items: List[Dict[str, Any]]) -> bytes:
    count = min(len(items), 3)
    header = struct.pack('>BBB', count, page_index, total_pages)
    item_bytes = bytearray()
    for i in range(3):
        if i < count:
            it = items[i]
            title = encode_text(it.get('title') or it.get('name') or '', 63)
            project = encode_text(it.get('project') or '', 31)
            status = int(it.get('status', 0)) & 0xFF
            item_bytes += struct.pack('>64s32sB', title, project, status)
        else:
            item_bytes += struct.pack('>64s32sB', b'', b'', 0)
    return header + bytes(item_bytes)

pack_messages_page = pack_projects_page

def pack_tasks_page(project_name: str, items: List[Dict[str, Any]]) -> bytes:
    proj = project_name.encode('utf-8')[:31].decode('utf-8', errors='ignore').encode('utf-8')
    count = min(len(items), 4)
    header = struct.pack('>32sB', proj, count)
    item_bytes = bytearray()
    for i in range(4):
        if i < count:
            it = items[i]
            short_id = (it.get('short_id') or '').encode('utf-8')[:15]
            state = it.get('state', 0) & 0xFF
            is_read = 1 if it.get('is_read') else 0
            dur = it.get('duration_sec', 0) & 0xFFFF
            label = (it.get('status_label') or '').encode('utf-8')[:23]
            item_bytes += struct.pack('<16sBBH24s', short_id, state, is_read, dur, label)
        else:
            item_bytes += struct.pack('<16sBBH24s', b'', 0, 0, 0, b'')
    return header + bytes(item_bytes)

def create_frames(msg_type: int, payload: bytes, max_chunk_len: int = 240) -> List[bytes]:
    if not 1 <= max_chunk_len <= 240 or len(payload) > 1024:
        raise ValueError("Invalid Passport payload or chunk size")
    total_seq = max(1, (len(payload) + max_chunk_len - 1) // max_chunk_len)
    frames = []
    for seq in range(total_seq):
        chunk = payload[seq * max_chunk_len:(seq + 1) * max_chunk_len]
        header = struct.pack('>BBBBBBH', PASSPORT_MAGIC_0, PASSPORT_MAGIC_1,
                             PASSPORT_PROTOCOL_VER, msg_type, seq, total_seq, len(chunk))
        frame = header + chunk
        frames.append(frame + struct.pack('>H', crc16_ccitt(frame)))
    return frames
