#!/usr/bin/env python3
"""Codex Passport Host Assistant.

Gathers local profile information and Codex session usage analytics.
Packages data into fragmented binary frames with CRC16 checksums.
Synchronizes credentials and analytics to FoloToy AI Passport via BLE (NimBLE).
Streams project states from local Codex transcripts independently of usage scans.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
import os
import struct
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from codex_task_state import TranscriptWatcher
from codex_unread import unread_count, UNKNOWN_UNREAD
from passport_protocol import encode_text, create_frames, crc16_ccitt, pack_projects_page, MSG_TYPE_PROJECTS, MSG_TYPE_ALERT

from codex_collector import (
    STATE_IDLE,
    UsageCollector,
    load_codex_account_quotas,
)

# Optional Bleak import for Bluetooth LE
try:
    import bleak
    from bleak import BleakClient, BleakScanner
except ImportError:
    bleak = None

# Protocol constants matching passport_protocol.h
PASSPORT_MAGIC_0 = 0x50  # 'P'
PASSPORT_MAGIC_1 = 0x54  # 'T'
PASSPORT_PROTOCOL_VER = 0x01
PASSPORT_MAX_CHUNK_LEN = 240

MSG_TYPE_PROFILE = 0x01
MSG_TYPE_STATS = 0x02
MSG_TYPE_HEATMAP = 0x03
MSG_TYPE_FOOTPRINTS = 0x04
MSG_TYPE_DIRECTIONS = 0x05
MSG_TYPE_REALTIME = 0x06
MSG_TYPE_ACK = 0x07
MSG_TYPE_QUOTA = 0x08
MSG_TYPE_UNREAD = 0x0A

# BLE UUIDs
PASSPORT_SVC_UUID = "0000cd00-0000-1000-8000-00805f9b34fb"
PASSPORT_CHR_RX_UUID = "0000cd01-0000-1000-8000-00805f9b34fb"
PASSPORT_CHR_TX_UUID = "0000cd02-0000-1000-8000-00805f9b34fb"
PASSPORT_CHR_LIVE_UUID = "0000cd03-0000-1000-8000-00805f9b34fb"

DEFAULT_PROFILE = {
    "name": "GuanMo",
    "interests": "读书 / 开发 / 运动",
    "signature": "In me the tiger sniffs the rose.",
    "homepage": "https://github.com/Ljhhhhhh",
    "issue_date": "2026-09-08",
}


def serialize_profile(prof: Dict[str, str]) -> bytes:
    name_b = encode_text(prof.get("name", "GuanMo"), 47)
    int_b = encode_text(prof.get("interests", "读书 / 开发 / 运动"), 95)
    sig_b = encode_text(prof.get("signature", "In me the tiger sniffs the rose."), 95)
    hp_b = encode_text(prof.get("homepage", "https://github.com/Ljhhhhhh"), 127)
    date_b = encode_text(prof.get("issue_date", "2026-09-08"), 15)

    return struct.pack(
        "<48s96s96s128s16s",
        name_b,
        int_b,
        sig_b,
        hp_b,
        date_b,
    )


def serialize_stats(stats: Dict[str, Any]) -> bytes:
    stamp = encode_text(str(stats.get("synced_at") or datetime.now().strftime("%m-%d %H:%M")), 15)
    return struct.pack(
        "<QIIH16s",
        int(stats.get("total_tokens", 0)),
        int(stats.get("today_tokens", 0)),
        int(stats.get("week_tokens", 0)),
        int(stats.get("streak_days", 0)),
        stamp,
    )



def serialize_heatmap(heatmap: Dict[str, Any]) -> bytes:
    levels = bytes(heatmap.get("levels", [0] * 91)[:91])
    if len(levels) < 91:
        levels = levels + b"\x00" * (91 - len(levels))

    start_date_b = encode_text(heatmap.get("start_date", "2026-06-14"), 15)
    end_date_b = encode_text(heatmap.get("end_date", "2026-09-13"), 15)
    active_days = int(heatmap.get("active_days", 0))
    max_tokens = int(heatmap.get("max_daily_tokens", 0))

    return struct.pack(
        "<91s16s16sHI",
        levels,
        start_date_b,
        end_date_b,
        active_days,
        max_tokens,
    )


def serialize_footprints(footprints: List[Dict[str, Any]]) -> bytes:
    count = min(6, len(footprints))
    items_bytes = bytearray()

    for i in range(6):
        if i < count:
            fp = footprints[i]
            top_b = encode_text(fp.get("topic", ""), 31)
            dt_b = encode_text(fp.get("first_date", ""), 15)
            tok = int(fp.get("total_tokens", 0))
        else:
            top_b = b""
            dt_b = b""
            tok = 0
        items_bytes.extend(struct.pack("<32s16sQ", top_b, dt_b, tok))

    return struct.pack("<B", count) + bytes(items_bytes)


def serialize_directions(directions: List[Dict[str, Any]]) -> bytes:
    count = min(5, len(directions))
    items_bytes = bytearray()

    for i in range(5):
        if i < count:
            d = directions[i]
            nm_b = encode_text(d.get("name", ""), 31)
            tok = int(d.get("tokens", 0))
            pct = int(d.get("percent", 0))
        else:
            nm_b = b""
            tok = 0
            pct = 0
        items_bytes.extend(struct.pack("<32sIB", nm_b, tok, pct))

    return struct.pack("<B", count) + bytes(items_bytes)

def serialize_quota(quota: Dict[str, Any]) -> bytes:
    accounts = list(quota.get("accounts") or [])[:3]
    hours = int(quota.get("short_window_hours", 5)) & 0xFF
    count = min(3, len(accounts))
    body = bytearray(struct.pack("<BB", count, hours))
    for i in range(3):
        if i < count:
            acc = accounts[i]
            name_b = encode_text(str(acc.get("name", "")), 11)
            body.extend(
                struct.pack(
                    "<12sBBII",
                    name_b,
                    int(acc.get("short_percent", 0)) & 0xFF,
                    int(acc.get("weekly_percent", 0)) & 0xFF,
                    int(acc.get("short_remaining_sec", 0)) & 0xFFFFFFFF,
                    int(acc.get("weekly_remaining_sec", 0)) & 0xFFFFFFFF,
                )
            )
        else:
            body.extend(struct.pack("<12sBBII", b"", 0, 0, 0, 0))
    return bytes(body)




def serialize_realtime(rt: Dict[str, Any]) -> bytes:
    state = int(rt.get("state", STATE_IDLE))
    duration = int(rt.get("duration_sec", 0))
    turn_tokens = int(rt.get("turn_tokens", 0))
    today_tokens = int(rt.get("today_tokens", 0))
    proj_b = encode_text(rt.get("project", ""), 31)

    return struct.pack("<BHII32s", state, duration, turn_tokens, today_tokens, proj_b)


def load_profile(custom_path: Optional[str] = None) -> Dict[str, str]:
    candidate_paths = [
        custom_path,
        os.path.expanduser("~/.codex-passport/config.json"),
        os.path.join(os.path.dirname(__file__), "..", "profile.json"),
    ]

    for path in candidate_paths:
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                profile = dict(DEFAULT_PROFILE)
                profile.update(data)
                print(f"[+] Loaded profile from: {path}")
                return profile
            except Exception as e:
                print(f"[!] Warning: failed to parse {path}: {e}")

    print("[*] Using default GuanMo credentials.")
    return dict(DEFAULT_PROFILE)


class MessageAlerts:
    """One chime per newly observed actionable task event; snapshots are silent."""
    def __init__(self):
        self.previous = None

    def update(self, items, valid=True):
        if not valid:
            self.previous = None
            return False
        current = {m["id"]: (m.get("event"), m["status"])
                   for m in items if m.get("id") and m["status"] in (1, 2, 3)}
        changed = self.previous is not None and any(
            self.previous.get(key) != event for key, event in current.items())
        self.previous = current
        return changed


class PassportAssistant:
    def __init__(self, profile_path: Optional[str] = None) -> None:
        self.profile = load_profile(profile_path)
        self.collector = UsageCollector()
        self.watcher = TranscriptWatcher()

    def prepare_sync_payloads(self) -> Dict[int, bytes]:
        summary = self.collector.scan(use_cache=True)
        stats = dict(summary["stats"])
        stats["synced_at"] = datetime.now().strftime("%m-%d %H:%M")

        return {
            MSG_TYPE_PROFILE: serialize_profile(self.profile),
            MSG_TYPE_STATS: serialize_stats(stats),
            MSG_TYPE_HEATMAP: serialize_heatmap(summary["heatmap"]),
            MSG_TYPE_FOOTPRINTS: serialize_footprints(summary["footprints"]),
            MSG_TYPE_DIRECTIONS: serialize_directions(summary["directions"]),
            MSG_TYPE_QUOTA: serialize_quota(load_codex_account_quotas()),
        }

    async def _push_payloads(self, client: Any, include_profile: bool) -> None:
        payloads = await asyncio.to_thread(self.prepare_sync_payloads)
        for msg_type, raw_payload in payloads.items():
            if not include_profile and msg_type == MSG_TYPE_PROFILE:
                continue
            frames = create_frames(msg_type, raw_payload)
            print(f"[*] Sending msg_type 0x{msg_type:02X} in {len(frames)} chunk(s)...")
            for frame in frames:
                await client.write_gatt_char(PASSPORT_CHR_RX_UUID, frame, response=False)
                await asyncio.sleep(0.04)

    async def _find_device(self, device_address: Optional[str]) -> Any:
        if device_address:
            return await BleakScanner.find_device_by_address(device_address, timeout=10.0)
        devices = await BleakScanner.discover(timeout=6.0)
        for d in devices:
            if d.name and "Codex-Passport" in d.name:
                return d
        return None

    async def _session_loop(self, client: Any, interval_sec: float) -> None:
        caps = bytes(await client.read_gatt_char(PASSPORT_CHR_TX_UUID))
        projects_supported = len(caps) >= 4 and caps[1:3] == b"\x50\x01"
        unread_supported = len(caps) >= 5 and caps[4] == 1
        if not unread_supported:
            print("[!] Firmware lacks unread screen control; update firmware")
        if not projects_supported:
            print("[!] Firmware lacks Projects support: flash build/codex-passport-full.bin")
        ack_queue = asyncio.Queue()
        def on_notify(_sender, data):
            data = bytes(data)
            if (len(data) == 12 and data[:4] == b"PT\x01\x07" and
                    crc16_ccitt(data[:-2]) == int.from_bytes(data[-2:], "big")):
                ack_queue.put_nowait(data[8:10])
        await client.start_notify(PASSPORT_CHR_TX_UUID, on_notify)
        alerts = MessageAlerts()
        alert_sequence = 0
        alerts_supported = len(caps) >= 6 and caps[5] == 1
        last_projects = None
        last_unread = None
        analytics = asyncio.create_task(asyncio.to_thread(self.prepare_sync_payloads))
        last_full = time.monotonic()
        try:
            while client.is_connected:
                if unread_supported:
                    count = await asyncio.to_thread(unread_count)
                    if count != last_unread:
                        while not ack_queue.empty():
                            ack_queue.get_nowait()
                        for frame in create_frames(MSG_TYPE_UNREAD, struct.pack("<I", count)):
                            await client.write_gatt_char(PASSPORT_CHR_RX_UUID, frame, response=True)
                        ack = await asyncio.wait_for(ack_queue.get(), timeout=3)
                        if ack != bytes([MSG_TYPE_UNREAD, 0]):
                            raise RuntimeError("Unread count rejected by device")
                        last_unread = count
                        print(f"[+] Unread ACK: {count if count != UNKNOWN_UNREAD else 'unknown; screen stays on'}")
                poll_res = await asyncio.to_thread(self.watcher.poll)
                if len(poll_res) == 3:
                    items, status, sync_error = poll_res
                else:
                    items, status = poll_res
                    sync_error = False
                if projects_supported:
                    caps = bytes(await client.read_gatt_char(PASSPORT_CHR_TX_UUID))
                    page_count = max(1, (len(items) + 2) // 3)
                    page = min(caps[3] if len(caps) >= 4 else 0, page_count - 1)
                    raw = pack_projects_page(page, page_count, items[page * 3:page * 3 + 3])
                    if raw != last_projects:
                        while not ack_queue.empty():
                            ack_queue.get_nowait()
                        for frame in create_frames(MSG_TYPE_PROJECTS, raw):
                            await client.write_gatt_char(PASSPORT_CHR_RX_UUID, frame, response=True)
                        try:
                            ack = await asyncio.wait_for(ack_queue.get(), timeout=3)
                            if ack != bytes([MSG_TYPE_PROJECTS, 0]):
                                raise RuntimeError("Projects rejected by device")
                        except asyncio.TimeoutError as exc:
                            raise RuntimeError("Projects ACK missing; update firmware") from exc
                        last_projects = raw
                        print(f"[+] Projects ACK: page {page + 1}/{page_count}, "
                              f"projects={len(items)}, state={status['state_name']}")
                if alerts.update(items, not sync_error) and alerts_supported:
                    alert_sequence += 1
                    while not ack_queue.empty():
                        ack_queue.get_nowait()
                    for frame in create_frames(MSG_TYPE_ALERT, struct.pack("<I", alert_sequence)):
                        await client.write_gatt_char(PASSPORT_CHR_RX_UUID, frame, response=True)
                    ack = await asyncio.wait_for(ack_queue.get(), timeout=3)
                    if ack != bytes([MSG_TYPE_ALERT, 0]):
                        raise RuntimeError("Message alert rejected by device")
                    print("[+] Message alert ACK")
                await client.write_gatt_char(PASSPORT_CHR_LIVE_UUID, serialize_realtime(status), response=True)
                if analytics is not None and analytics.done():
                    for msg_type, raw in analytics.result().items():
                        for frame in create_frames(msg_type, raw):
                            await client.write_gatt_char(PASSPORT_CHR_RX_UUID, frame, response=True)
                    analytics = None
                    last_full = time.monotonic()
                    print("[+] Analytics sent.")
                if analytics is None and time.monotonic() - last_full >= interval_sec:
                    analytics = asyncio.create_task(asyncio.to_thread(self.prepare_sync_payloads))
                await asyncio.sleep(2)
        finally:
            if analytics is not None:
                await analytics

    async def run_sync_ble(
        self,
        device_address: Optional[str] = None,
        interval_sec: float = 60.0,
    ) -> None:
        if bleak is None:
            print("[-] Error: 'bleak' is not installed. Run 'pip install bleak' to enable BLE connectivity.")
            return

        while True:
            try:
                print("[*] Scanning for Codex-Passport BLE peripheral...")
                target_device = await self._find_device(device_address)
                if not target_device:
                    print("[-] Could not find 'Codex-Passport'. Retrying in 5s...")
                    await asyncio.sleep(5.0)
                    continue

                print(f"[+] Found device: {target_device.name} ({target_device.address})")
                print("[*] Connecting via BLE...")
                async with BleakClient(target_device) as client:
                    print("[+] Connected to Codex-Passport!")
                    await self._session_loop(client, interval_sec)
                print("[*] Disconnected.")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[-] BLE session ended: {exc}")
            print("[*] Reconnecting in 5s...")
            await asyncio.sleep(5.0)



def main() -> int:
    parser = argparse.ArgumentParser(description="Codex Passport Host Assistant")
    parser.add_argument("--config", help="Path to profile JSON configuration file")
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Connect via BLE, sync on an interval, stream live events, and reconnect on drop",
    )
    parser.add_argument("--device", help="Specific BLE device MAC address / UUID")
    parser.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="Seconds between usage/quota refreshes while connected (default: 60)",
    )
    parser.add_argument("--test", action="store_true", help="Perform offline serialization test and frame inspection")
    args = parser.parse_args()

    assistant = PassportAssistant(args.config)

    if args.test:
        print("[*] Running offline packaging test...")
        payloads = assistant.prepare_sync_payloads()
        total_bytes = 0
        total_frames = 0
        for mtype, raw in payloads.items():
            frames = create_frames(mtype, raw)
            total_frames += len(frames)
            total_bytes += sum(len(f) for f in frames)
            print(f"  Msg Type 0x{mtype:02X}: Payload {len(raw)} bytes -> {len(frames)} frame(s) with CRC16")

        print(f"\n[+] Total synchronization payload: {total_bytes} bytes in {total_frames} frames.")
        print("[+] Offline packaging test PASSED.")
        return 0

    if args.sync:
        if bleak is None:
            print("[-] Error: 'bleak' is required for BLE sync. Install it with: pip install bleak")
            return 1
        interval = args.interval if args.interval > 0 else 60.0
        try:
            asyncio.run(assistant.run_sync_ble(args.device, interval_sec=interval))
        except KeyboardInterrupt:
            print("\n[*] Stopped.")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
