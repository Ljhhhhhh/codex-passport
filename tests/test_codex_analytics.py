#!/usr/bin/env python3
"""Comprehensive host test suite for Codex usage analytics and realtime watcher."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import os
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Add tools to import path
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from codex_collector import (
    STATE_COMPLETED,
    STATE_ERROR,
    STATE_IDLE,
    STATE_RUNNING,
    RealtimeWatcher,
    UsageCollector,
    accounts_from_codex_auth,
    accounts_from_quota_cache,
    classify_topic,
    load_opencodex_quota,
    parse_timestamp_to_local_date,
)
from assistant import (
    create_frames,
    crc16_ccitt,
    serialize_directions,
    serialize_footprints,
    serialize_heatmap,
    serialize_profile,
    serialize_quota,
    serialize_realtime,
    serialize_stats,
)


class TestCodexUsageCollector(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sessions_dir = os.path.join(self.temp_dir.name, "sessions")
        self.archived_dir = os.path.join(self.temp_dir.name, "archived")
        os.makedirs(self.sessions_dir, exist_ok=True)
        os.makedirs(self.archived_dir, exist_ok=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_token_deduplication_by_response_id(self) -> None:
        """Verify duplicate response_ids are counted once, ignoring cumulative totals."""
        session_file = os.path.join(self.sessions_dir, "test_session_1.jsonl")

        records = [
            # Turn context
            {"type": "turn_context", "payload": {"cwd": "/workspace/projects/open-webui"}},
            # Response 1 - first emission (3000 tokens)
            {
                "timestamp": "2026-09-01T10:00:00Z",
                "type": "token_usage_record",
                "ordinal": 1,
                "payload": {
                    "response_id": "resp_abc123",
                    "session_id": "sess_1",
                    "turn_id": "turn_1",
                    "usage": {"total_tokens": 3000, "input_tokens": 2800, "output_tokens": 200},
                    "turn_token_usage": {"total_tokens": 3000},
                    "thread_token_usage": {"total_tokens": 3000},
                },
            },
            # Duplicate emission of Response 1 (e.g. streaming update or resume)
            {
                "timestamp": "2026-09-01T10:00:05Z",
                "type": "token_usage_record",
                "ordinal": 2,
                "payload": {
                    "response_id": "resp_abc123",
                    "session_id": "sess_1",
                    "turn_id": "turn_1",
                    "usage": {"total_tokens": 3000, "input_tokens": 2800, "output_tokens": 200},
                    "turn_token_usage": {"total_tokens": 3000},
                    "thread_token_usage": {"total_tokens": 3000},
                },
            },
            # Response 2 - distinct emission (2500 tokens)
            {
                "timestamp": "2026-09-01T10:05:00Z",
                "type": "token_usage_record",
                "ordinal": 3,
                "payload": {
                    "response_id": "resp_def456",
                    "session_id": "sess_1",
                    "turn_id": "turn_1",
                    "usage": {"total_tokens": 2500, "input_tokens": 2400, "output_tokens": 100},
                    # Notice cumulative fields are 5500, but collector MUST sum only incremental 3000 + 2500 = 5500
                    "turn_token_usage": {"total_tokens": 5500},
                    "thread_token_usage": {"total_tokens": 5500},
                },
            },
        ]

        with open(session_file, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        collector = UsageCollector(sessions_dir=self.sessions_dir, archived_dir=self.archived_dir, cache_path=None)
        summary = collector.scan(use_cache=False)

        self.assertEqual(summary["stats"]["total_tokens"], 5500)
        self.assertEqual(collector.processed_records, 2)  # 2 unique records out of 3 emitted
        self.assertIn("2026-09-01", collector.daily_tokens)
        self.assertEqual(collector.daily_tokens["2026-09-01"], 5500)

    def test_cross_day_token_aggregation(self) -> None:
        """Verify tokens across multiple calendar days group into proper dates."""
        session_file = os.path.join(self.sessions_dir, "multi_day.jsonl")

        records = [
            {"type": "turn_context", "payload": {"cwd": "/workspace/iot/ai-passport"}},
            # Day 1: 10,000 tokens
            {
                "timestamp": "2026-09-01T12:00:00Z",
                "type": "token_usage_record",
                "payload": {"response_id": "r1", "usage": {"total_tokens": 10000}},
            },
            # Day 2: 25,000 tokens
            {
                "timestamp": "2026-09-02T12:00:00Z",
                "type": "token_usage_record",
                "payload": {"response_id": "r2", "usage": {"total_tokens": 25000}},
            },
            # Day 3: 15,000 tokens
            {
                "timestamp": "2026-09-03T12:00:00Z",
                "type": "token_usage_record",
                "payload": {"response_id": "r3", "usage": {"total_tokens": 15000}},
            },
        ]

        with open(session_file, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        collector = UsageCollector(sessions_dir=self.sessions_dir, archived_dir=self.archived_dir, cache_path=None)
        summary = collector.scan(use_cache=False)

        self.assertEqual(summary["stats"]["total_tokens"], 50000)
        self.assertEqual(collector.daily_tokens.get("2026-09-01"), 10000)
        self.assertEqual(collector.daily_tokens.get("2026-09-02"), 25000)
        self.assertEqual(collector.daily_tokens.get("2026-09-03"), 15000)


    def test_directions_nested_session_layout(self) -> None:
        """YYYY/MM/DD session folders still yield top-5 projects in the last 30 days."""
        now = datetime.now()
        projects = [
            ("open-webui", 10000),
            ("ai-passport", 7000),
            ("gf-ai-server", 5000),
            ("frontend", 3000),
            ("hermes", 1000),
        ]
        for i, (name, tok) in enumerate(projects):
            day = now - timedelta(days=i)
            folder = os.path.join(
                self.sessions_dir,
                day.strftime("%Y"),
                day.strftime("%m"),
                day.strftime("%d"),
            )
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"{name}.jsonl")
            records = [
                {"type": "turn_context", "payload": {"cwd": f"/workspace/{name}"}},
                {
                    "timestamp": day.strftime("%Y-%m-%dT12:00:00Z"),
                    "type": "token_usage_record",
                    "payload": {"response_id": f"r-{name}", "usage": {"total_tokens": tok}},
                },
            ]
            with open(path, "w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r) + "\n")

        collector = UsageCollector(
            sessions_dir=self.sessions_dir, archived_dir=self.archived_dir, cache_path=None
        )
        summary = collector.scan(use_cache=False)
        names = [d["name"] for d in summary["directions"]]
        self.assertEqual(names, ["open-webui", "ai-passport", "gf-ai-server", "frontend", "hermes"])
        self.assertEqual(len(summary["directions"]), 5)


    def test_streak_calculation(self) -> None:
        """Verify active streak counting rules."""
        collector = UsageCollector(sessions_dir=self.sessions_dir, archived_dir=self.archived_dir, cache_path=None)

        today_str = datetime.now().strftime("%Y-%m-%d")
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        day_before_str = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")

        # Case 1: Active today + yesterday + day before -> 3 days
        collector.daily_tokens = {
            today_str: 5000,
            yesterday_str: 12000,
            day_before_str: 8000,
        }
        collector.total_tokens = 25000
        stats = collector.calculate_stats()
        self.assertEqual(stats["streak_days"], 3)

        # Case 2: Today not yet active, but yesterday + day before active -> 2 days streak preserved
        collector.daily_tokens = {
            yesterday_str: 12000,
            day_before_str: 8000,
        }
        stats = collector.calculate_stats()
        self.assertEqual(stats["streak_days"], 2)

        # Case 3: Gap yesterday -> streak broken (0 days)
        collector.daily_tokens = {
            day_before_str: 8000,
        }
        stats = collector.calculate_stats()
        self.assertEqual(stats["streak_days"], 0)

    def test_week_tokens_are_rolling_seven_days(self) -> None:
        collector = UsageCollector(
            sessions_dir=self.sessions_dir, archived_dir=self.archived_dir, cache_path=None
        )
        today = datetime.now().date()
        collector.daily_tokens = {
            today.strftime("%Y-%m-%d"): 100,
            (today - timedelta(days=6)).strftime("%Y-%m-%d"): 50,
            (today - timedelta(days=7)).strftime("%Y-%m-%d"): 999,
        }
        stats = collector.calculate_stats()
        self.assertEqual(stats["week_tokens"], 150)


    def test_heatmap_91d(self) -> None:
        """Verify 13-week heatmap produces exactly 91 days and valid intensity levels."""
        collector = UsageCollector(sessions_dir=self.sessions_dir, archived_dir=self.archived_dir, cache_path=None)

        ref_end_date = date(2026, 9, 6)  # Sunday
        day_str = ref_end_date.strftime("%Y-%m-%d")
        collector.daily_tokens[day_str] = 500_000

        heatmap = collector.calculate_heatmap_91d(end_date=ref_end_date)
        levels = heatmap["levels"]

        self.assertEqual(len(levels), 91)
        self.assertEqual(heatmap["end_date"], "2026-09-06")
        self.assertEqual(heatmap["active_days"], 1)
        self.assertEqual(heatmap["max_daily_tokens"], 500_000)

        # Level on the active day must be 3 (between 300k and 1.5M)
        self.assertEqual(levels[-1], 3)
        # Inactive days must be level 0
        self.assertEqual(levels[0], 0)

    def test_topic_classification(self) -> None:
        """Verify deterministic rule-based topic categorizations."""
        self.assertEqual(classify_topic("ai-passport", "/home/user/ai-passport"), "IoT & Hardware")
        self.assertEqual(classify_topic("open-webui", "/home/user/open-webui"), "Frontend & Web")
        self.assertEqual(classify_topic("chatcli", "/app/chatcli"), "AI Systems")
        self.assertEqual(classify_topic("gf-ai-server", "/projects/gf-ai-server"), "Backend & Cloud")
        self.assertEqual(classify_topic("my-custom-tool", "/tools/my-custom-tool"), "My Custom Tool")


class TestOpenCodexUsageCollector(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.usage_path = os.path.join(self.temp_dir.name, "usage.jsonl")
        self.sessions_dir = os.path.join(self.temp_dir.name, "sessions")
        os.makedirs(self.sessions_dir, exist_ok=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _ms(self, dt: datetime) -> int:
        return int(dt.timestamp() * 1000)

    def _write(self, records: list) -> None:
        with open(self.usage_path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")

    def _collector(self) -> UsageCollector:
        return UsageCollector(
            sessions_dir=self.sessions_dir,
            archived_dir=self.sessions_dir,
            cache_path=None,
            opencodex_usage_path=self.usage_path,
        )

    def test_request_id_dedup_and_today_total(self) -> None:
        now = datetime.now()
        rec = {
            "requestId": "ocx-1",
            "timestamp": self._ms(now),
            "provider": "openai",
            "model": "gpt-5.6-sol",
            "status": 200,
            "usage": {"inputTokens": 900, "outputTokens": 100, "totalTokens": 1000},
            "totalTokens": 1000,
        }
        dup = dict(rec)
        dup["totalTokens"] = 99999
        dup["usage"] = {"totalTokens": 99999}
        second = dict(rec)
        second["requestId"] = "ocx-2"
        second["totalTokens"] = 400
        second["usage"] = {"totalTokens": 400}
        self._write([rec, dup, second])

        summary = self._collector().scan(use_cache=False)
        self.assertEqual(summary["stats"]["total_tokens"], 1400)
        self.assertEqual(summary["stats"]["today_tokens"], 1400)

    def test_directions_are_top_models_last_30d(self) -> None:
        now = datetime.now()
        rows = [
            ("gpt-5.6-sol", "openai", 10000),
            ("gemini-3.8-flash", "google-antigravity", 7000),
            ("grok-4.6", "xai", 5000),
            ("gpt-5.6-luna", "openai", 3000),
            ("gpt-6-astra", "openai", 1000),
            ("stale-model", "openai", 99999),
        ]
        records = []
        for i, (model, provider, tok) in enumerate(rows):
            ts = now if model != "stale-model" else now - timedelta(days=40)
            records.append({
                "requestId": f"ocx-{i}",
                "timestamp": self._ms(ts),
                "provider": provider,
                "model": model,
                "status": 200,
                "usage": {"totalTokens": tok},
                "totalTokens": tok,
            })
        self._write(records)

        summary = self._collector().scan(use_cache=False)
        names = [d["name"] for d in summary["directions"]]
        self.assertEqual(
            names,
            ["gpt-5.6-sol", "gemini-3.8-flash", "grok-4.6", "gpt-5.6-luna", "gpt-6-astra"],
        )
        topics = [fp["topic"] for fp in summary["footprints"]]
        self.assertIn("OpenAI / Codex", topics)
        self.assertIn("Gemini", topics)
        self.assertIn("xAI Grok", topics)

    def test_heatmap_relative_intensity(self) -> None:
        peak = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        quiet = peak - timedelta(days=1)
        self._write([
            {
                "requestId": "ocx-peak",
                "timestamp": self._ms(peak),
                "provider": "openai",
                "model": "gpt-5.6-sol",
                "status": 200,
                "usage": {"totalTokens": 1_000_000},
                "totalTokens": 1_000_000,
            },
            {
                "requestId": "ocx-quiet",
                "timestamp": self._ms(quiet),
                "provider": "openai",
                "model": "gpt-5.6-luna",
                "status": 200,
                "usage": {"totalTokens": 50_000},
                "totalTokens": 50_000,
            },
        ])
        collector = self._collector()
        collector.scan(use_cache=False)
        heatmap = collector.calculate_heatmap_91d()
        self.assertEqual(len(heatmap["levels"]), 91)
        self.assertTrue(all(0 <= lv <= 4 for lv in heatmap["levels"]))
        self.assertIn(4, heatmap["levels"])
        self.assertIn(1, heatmap["levels"])


class TestOpenCodexRealtimeWatcher(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.usage_path = os.path.join(self.temp_dir.name, "usage.jsonl")
        open(self.usage_path, "w", encoding="utf-8").close()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_completed_then_idle_timeout(self) -> None:
        watcher = RealtimeWatcher(
            sessions_dir=self.temp_dir.name,
            idle_timeout_sec=0.2,
            opencodex_usage_path=self.usage_path,
        )
        status = watcher.poll()
        self.assertEqual(status["state"], STATE_IDLE)

        rec = {
            "requestId": "ocx-live",
            "timestamp": int(time.time() * 1000),
            "provider": "xai",
            "model": "grok-4.6",
            "status": 200,
            "usage": {"totalTokens": 321},
            "totalTokens": 321,
        }
        with open(self.usage_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

        status = watcher.poll()
        self.assertEqual(status["state"], STATE_COMPLETED)
        self.assertEqual(status["project"], "grok-4.6")
        self.assertEqual(status["turn_tokens"], 321)

        time.sleep(0.3)
        status = watcher.poll()
        self.assertEqual(status["state"], STATE_IDLE)



class TestRealtimeWatcher(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.session_file = os.path.join(self.temp_dir.name, "active_session.jsonl")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_watcher_transitions_and_timeout(self) -> None:
        """Verify state updates: IDLE -> RUNNING -> COMPLETED -> IDLE (on timeout)."""
        watcher = RealtimeWatcher(sessions_dir=self.temp_dir.name, idle_timeout_sec=0.2)

        # Initially idle
        status = watcher.poll()
        self.assertEqual(status["state"], STATE_IDLE)

        # Emit task_started
        with open(self.session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "turn_context", "payload": {"cwd": "/workspace/ai-passport"}}) + "\n")
            f.write(json.dumps({"type": "event_msg", "payload": {"type": "task_started"}}) + "\n")

        status = watcher.poll()
        self.assertEqual(status["state"], STATE_RUNNING)
        self.assertEqual(status["project"], "ai-passport")

        # Emit task_complete
        with open(self.session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "event_msg", "payload": {"type": "task_complete"}}) + "\n")

        status = watcher.poll()
        self.assertEqual(status["state"], STATE_COMPLETED)

        # Emit running again, then let it time out
        with open(self.session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "event_msg", "payload": {"type": "user_message"}}) + "\n")

        status = watcher.poll()
        self.assertEqual(status["state"], STATE_RUNNING)

        # Sleep past timeout
        time.sleep(0.3)
        status = watcher.poll()
        self.assertEqual(status["state"], STATE_IDLE)


class TestProtocolSerialization(unittest.TestCase):
    def test_serialization_and_frames(self) -> None:
        """Verify struct serialization and CRC16 frame generation."""
        prof = {
            "name": "GuanMo",
            "interests": "读书 / 开发 / 运动",
            "signature": "难，是幸福的开始",
            "homepage": "https://github.com/Ljhhhhhh",
            "issue_date": "2026-09-08",
        }
        prof_bytes = serialize_profile(prof)
        self.assertEqual(len(prof_bytes), 384)  # 48 + 96 + 96 + 128 + 16

        stats_bytes = serialize_stats({
            "total_tokens": 100,
            "today_tokens": 10,
            "week_tokens": 20,
            "streak_days": 2,
            "synced_at": "09-09 14:32",
        })
        self.assertEqual(len(stats_bytes), 34)
        stamp = struct.unpack_from("<16s", stats_bytes, 18)[0].split(b"\0", 1)[0]
        self.assertEqual(stamp, b"09-09 14:32")


        frames = create_frames(0x01, prof_bytes)
        self.assertEqual(len(frames), 2)  # 240 + 144 bytes payload

        # Check CRC on frame 0
        crc0 = crc16_ccitt(frames[0][:-2])
        expected_crc0 = struct.unpack(">H", frames[0][-2:])[0]
        self.assertEqual(crc0, expected_crc0)

        # Check CRC on frame 1
        crc1 = crc16_ccitt(frames[1][:-2])
        expected_crc1 = struct.unpack(">H", frames[1][-2:])[0]
        self.assertEqual(crc1, expected_crc1)

        quota = {
            "short_window_hours": 5,
            "accounts": [
                {
                    "name": "MAIN",
                    "short_percent": 0,
                    "weekly_percent": 27,
                    "short_remaining_sec": 1300,
                    "weekly_remaining_sec": 500000,
                },
                {
                    "name": "p47b4b2",
                    "short_percent": 0,
                    "weekly_percent": 31,
                    "short_remaining_sec": 2000,
                    "weekly_remaining_sec": 400000,
                },
                {
                    "name": "pbf90e3",
                    "short_percent": 12,
                    "weekly_percent": 27,
                    "short_remaining_sec": 800,
                    "weekly_remaining_sec": 500000,
                },
            ],
        }
        q_bytes = serialize_quota(quota)
        self.assertEqual(len(q_bytes), 68)
        count, hours = struct.unpack_from("<BB", q_bytes, 0)
        self.assertEqual((count, hours), (3, 5))
        name, sp, wp, sr, wr = struct.unpack_from("<12sBBII", q_bytes, 2)
        self.assertEqual(name.split(b"\0", 1)[0], b"MAIN")
        self.assertEqual((sp, wp, sr, wr), (0, 27, 1300, 500000))
        q_frames = create_frames(0x08, q_bytes)
        self.assertEqual(len(q_frames), 1)


class TestOpenCodexQuota(unittest.TestCase):
    def test_three_codex_accounts_from_auth_payload(self) -> None:
        now = 1_000_000.0
        payload = {
            "accounts": [
                {
                    "id": "__main__",
                    "isMain": True,
                    "logLabel": "main",
                    "quota": {
                        "shortPercent": 0,
                        "weeklyPercent": 27,
                        "shortResetAt": now + 1300,
                        "weeklyResetAt": now + 500000,
                        "shortWindowSeconds": 18000,
                    },
                },
                {
                    "id": "chatgpt-1787041356764",
                    "isMain": False,
                    "logLabel": "p47b4b2",
                    "quota": {
                        "shortPercent": 0,
                        "weeklyPercent": 31,
                        "shortResetAt": now + 2000,
                        "weeklyResetAt": now + 400000,
                        "shortWindowSeconds": 18000,
                    },
                },
                {
                    "id": "chatgpt-1787041433585",
                    "isMain": False,
                    "logLabel": "pbf90e3",
                    "quota": {
                        "shortPercent": 12,
                        "weeklyPercent": 27,
                        "shortResetAt": now + 800,
                        "weeklyResetAt": now + 500000,
                        "shortWindowSeconds": 18000,
                    },
                },
            ]
        }
        rows = accounts_from_codex_auth(payload, now=now)
        self.assertEqual([r["name"] for r in rows], ["MAIN", "p47b4b2", "pbf90e3"])
        self.assertEqual(rows[0]["weekly_percent"], 27)
        self.assertEqual(rows[1]["weekly_percent"], 31)
        self.assertEqual(rows[2]["short_percent"], 12)
        self.assertEqual(rows[0]["short_remaining_sec"], 1300)

    def test_duplicate_main_is_skipped_and_aliases_are_used(self) -> None:
        now = 1_000_000.0
        quota_a = {
            "shortPercent": 17, "weeklyPercent": 38,
            "shortResetAt": now + 100, "weeklyResetAt": now + 200, "shortWindowSeconds": 18000,
        }
        payload = {
            "accounts": [
                {"id": "__main__", "isMain": True, "email": "a@x.com", "logLabel": "main", "quota": dict(quota_a)},
                {"id": "chatgpt-1", "alias": "pipilu", "email": "a@x.com", "logLabel": "p47179b", "quota": dict(quota_a)},
                {"id": "chatgpt-2", "alias": "GuanMo", "email": "b@x.com", "logLabel": "p69ec00",
                 "quota": {"shortPercent": 100, "weeklyPercent": 73, "shortResetAt": now + 1, "weeklyResetAt": now + 2, "shortWindowSeconds": 18000}},
                {"id": "chatgpt-3", "alias": "Guanmo2", "email": "c@x.com", "logLabel": "paf0639",
                 "quota": {"shortPercent": 0, "weeklyPercent": 56, "shortResetAt": now + 3, "weeklyResetAt": now + 4, "shortWindowSeconds": 18000}},
            ]
        }
        rows = accounts_from_codex_auth(payload, now=now)
        self.assertEqual([r["name"] for r in rows], ["pipilu", "GuanMo", "Guanmo2"])
        self.assertEqual([r["short_percent"] for r in rows], [17, 100, 0])
        self.assertEqual([r["weekly_percent"] for r in rows], [38, 73, 56])

    def test_quota_cache_keeps_three_codex_keys(self) -> None:
        now = 1_000_000.0
        data = {
            "quotas": {
                "__main__": {
                    "shortPercent": 1,
                    "weeklyPercent": 10,
                    "shortResetAt": now + 10,
                    "weeklyResetAt": now + 20,
                    "shortWindowSeconds": 18000,
                },
                "chatgpt-aaa": {
                    "shortPercent": 2,
                    "weeklyPercent": 20,
                    "shortResetAt": now + 10,
                    "weeklyResetAt": now + 20,
                    "shortWindowSeconds": 18000,
                },
                "chatgpt-bbb": {
                    "shortPercent": 3,
                    "weeklyPercent": 30,
                    "shortResetAt": now + 10,
                    "weeklyResetAt": now + 20,
                    "shortWindowSeconds": 18000,
                },
            }
        }
        rows = accounts_from_quota_cache(data, now=now)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["name"], "MAIN")
        self.assertEqual([r["weekly_percent"] for r in rows], [10, 20, 30])

    def test_quota_cache_skips_main_when_same_as_pool(self) -> None:
        now = 1_000_000.0
        shared = {"shortPercent": 17, "weeklyPercent": 38, "shortResetAt": now + 10, "weeklyResetAt": now + 20, "shortWindowSeconds": 18000}
        data = {
            "quotas": {
                "chatgpt-1788945861659": dict(shared),
                "__main__": dict(shared),
                "chatgpt-1788952865927": {"shortPercent": 100, "weeklyPercent": 73, "shortResetAt": now + 11, "weeklyResetAt": now + 21, "shortWindowSeconds": 18000},
                "chatgpt-1788997492879": {"shortPercent": 0, "weeklyPercent": 56, "shortResetAt": now + 12, "weeklyResetAt": now + 22, "shortWindowSeconds": 18000},
            }
        }
        rows = accounts_from_quota_cache(data, now=now)
        self.assertEqual(len(rows), 3)
        self.assertNotIn("MAIN", [r["name"] for r in rows])
        self.assertEqual([r["short_percent"] for r in rows], [17, 100, 0])

    def test_missing_quota_file_is_zeros(self) -> None:
        q = load_opencodex_quota("/tmp/does-not-exist-opencodex-quota.json")
        self.assertEqual(q["short_percent"], 0)
        self.assertEqual(q["weekly_percent"], 0)
        self.assertEqual(q["short_window_hours"], 5)




def main() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)


if __name__ == "__main__":
    main()
